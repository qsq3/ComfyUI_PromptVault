import asyncio
import copy
import json
import logging
import re

import httpx

logger = logging.getLogger("PromptVault")

TASK_TAGS = "tags"
TASK_TITLE = "title"
TASK_TITLE_TAGS = "title_tags"
PROMPT_TASKS = (TASK_TAGS, TASK_TITLE, TASK_TITLE_TAGS)

DEFAULT_PROMPTS_BY_TASK = {
    TASK_TAGS: [
        {
            "id": "tags_default",
            "task": TASK_TAGS,
            "name": "默认标签生成",
            "prompt": (
                "你是图像生成提示词分析专家。根据提供的正向和负向提示词，"
                "生成 5 到 15 个相关标签。"
                "标签应覆盖主题、风格、画质、场景、人物特征、光照、构图等维度。"
                "标签可用中文或英文，每个标签尽量简短。"
                "只返回 JSON 数组，不要输出其他文字。"
            ),
        },
        {
            "id": "tags_detailed",
            "task": TASK_TAGS,
            "name": "详细标签生成",
            "prompt": (
                "你是专业的图像提示词分析师。请根据提示词生成更细的标签集合，"
                "覆盖主题类型、艺术风格、画面质量、场景环境、人物特征、光照效果、构图方式和情绪氛围。"
                "标签尽量简洁明确，只返回 JSON 数组。"
            ),
        },
    ],
    TASK_TITLE: [
        {
            "id": "title_default",
            "task": TASK_TITLE,
            "name": "默认标题生成",
            "prompt": (
                "你是提示词命名助手。根据正向和负向提示词，为这条记录生成一个简洁、明确、适合归档检索的中文标题。"
                "标题长度控制在 6 到 18 个字，避免空泛词汇，优先突出主体、风格或场景。"
                "只返回 JSON 对象，例如 {\"title\":\"赛博霓虹街头少女\"}。"
            ),
        },
        {
            "id": "title_style_focused",
            "task": TASK_TITLE,
            "name": "风格导向标题",
            "prompt": (
                "你是图像提示词整理助手。请根据提示词生成一个更偏风格表达的中文标题，"
                "标题需要兼顾主体与视觉风格，适合做提示词库条目名。"
                "只返回 JSON 对象，例如 {\"title\":\"电影感逆光人像\"}。"
            ),
        },
    ],
    TASK_TITLE_TAGS: [
        {
            "id": "title_tags_default",
            "task": TASK_TITLE_TAGS,
            "name": "标题标签同时生成",
            "prompt": (
                "你是提示词库整理助手。请根据正向和负向提示词，同时生成一个中文标题和 5 到 12 个标签。"
                "标题要简洁明确，适合归档；标签要覆盖主体、风格、场景、光照、构图等维度。"
                "只返回 JSON 对象，例如 {\"title\":\"雨夜霓虹街景\",\"tags\":[\"赛博朋克\",\"雨夜\",\"霓虹\",\"街景\"]}。"
            ),
        }
    ],
}

DEFAULT_SYSTEM_PROMPTS = copy.deepcopy(DEFAULT_PROMPTS_BY_TASK[TASK_TAGS])
DEFAULT_SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPTS[0]["prompt"]


def _flatten_default_rules():
    rules = []
    for task in PROMPT_TASKS:
        rules.extend(copy.deepcopy(DEFAULT_PROMPTS_BY_TASK[task]))
    return rules


DEFAULT_LLM_CONFIG = {
    "enabled": False,
    "base_url": "http://localhost:1234",
    "model": "",
    "api_key": "",
    "timeout": 30,
    "system_prompt_id": DEFAULT_SYSTEM_PROMPTS[0]["id"],
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "custom_system_prompts": _flatten_default_rules(),
    "active_prompt_ids": {
        TASK_TAGS: DEFAULT_PROMPTS_BY_TASK[TASK_TAGS][0]["id"],
        TASK_TITLE: DEFAULT_PROMPTS_BY_TASK[TASK_TITLE][0]["id"],
        TASK_TITLE_TAGS: DEFAULT_PROMPTS_BY_TASK[TASK_TITLE_TAGS][0]["id"],
    },
}


def _json_from_text(text: str, opener: str, closer: str):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    pattern = re.escape(opener) + r".*?" + re.escape(closer)
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def _normalize_rule(rule: dict, fallback_task: str = TASK_TAGS) -> dict:
    normalized = dict(rule or {})
    normalized["id"] = str(normalized.get("id") or "").strip() or f"{fallback_task}_{len(json.dumps(rule or {}))}"
    normalized["name"] = str(normalized.get("name") or "未命名规则").strip() or "未命名规则"
    task = str(normalized.get("task") or fallback_task).strip() or fallback_task
    if task not in PROMPT_TASKS:
        task = fallback_task
    normalized["task"] = task
    normalized["prompt"] = str(normalized.get("prompt") or "").strip()
    return normalized


def normalize_config(config: dict | None) -> dict:
    incoming = dict(config or {})
    merged = {**DEFAULT_LLM_CONFIG, **incoming}

    rules_src = incoming.get("custom_system_prompts")
    if not isinstance(rules_src, list):
        rules_src = merged.get("custom_system_prompts")
    rules = []
    if isinstance(rules_src, list):
        for item in rules_src:
            if isinstance(item, dict):
                rules.append(_normalize_rule(item, item.get("task") or TASK_TAGS))

    if not rules:
        rules = _flatten_default_rules()

    existing_ids = {rule["id"] for rule in rules}
    for task in PROMPT_TASKS:
        for default_rule in DEFAULT_PROMPTS_BY_TASK[task]:
            if default_rule["id"] not in existing_ids:
                rules.append(copy.deepcopy(default_rule))
                existing_ids.add(default_rule["id"])

    active_prompt_ids = dict(DEFAULT_LLM_CONFIG["active_prompt_ids"])
    stored_active = incoming.get("active_prompt_ids")
    if isinstance(stored_active, dict):
        for task in PROMPT_TASKS:
            value = stored_active.get(task)
            if isinstance(value, str) and value.strip():
                active_prompt_ids[task] = value.strip()

    legacy_prompt_id = incoming.get("system_prompt_id")
    if isinstance(legacy_prompt_id, str) and legacy_prompt_id.strip():
        active_prompt_ids[TASK_TAGS] = legacy_prompt_id.strip()

    for task in PROMPT_TASKS:
        task_rules = [rule for rule in rules if rule["task"] == task]
        if not task_rules:
            task_rules = copy.deepcopy(DEFAULT_PROMPTS_BY_TASK[task])
            rules.extend(task_rules)
        active_id = active_prompt_ids.get(task)
        if not any(rule["id"] == active_id for rule in task_rules):
            active_prompt_ids[task] = task_rules[0]["id"]

    merged["custom_system_prompts"] = rules
    merged["active_prompt_ids"] = active_prompt_ids
    merged["system_prompt_id"] = active_prompt_ids[TASK_TAGS]
    merged["system_prompt"] = next(
        (rule["prompt"] for rule in rules if rule["id"] == active_prompt_ids[TASK_TAGS]),
        DEFAULT_SYSTEM_PROMPT,
    )
    return merged


def _build_user_prompt(
    task: str,
    positive: str,
    negative: str,
    existing_tags: list[str] | None = None,
    existing_title: str = "",
) -> str:
    parts = []
    if positive.strip():
        parts.append(f"正向提示词:\n{positive.strip()}")
    if negative.strip():
        parts.append(f"负向提示词:\n{negative.strip()}")
    if existing_title.strip():
        parts.append(f"已有标题: {existing_title.strip()}")
    if existing_tags:
        parts.append(f"已有标签: {', '.join(existing_tags)}")

    if task == TASK_TAGS:
        parts.append("请补充适合归档和检索的新标签，避免与已有标签重复。")
    elif task == TASK_TITLE:
        parts.append("请输出一个更适合提示词库归档的标题。")
    else:
        parts.append("请同时输出标题和标签，标签避免与已有标签重复。")
    return "\n\n".join(parts)


def _parse_tag_response(text: str) -> list[str]:
    result = _json_from_text(text, "[", "]")
    if isinstance(result, list):
        return [str(tag).strip() for tag in result if str(tag).strip()]
    return []


def _parse_title_response(text: str) -> str:
    obj = _json_from_text(text, "{", "}")
    if isinstance(obj, dict):
        title = str(obj.get("title") or "").strip()
        if title:
            return title
    text = (text or "").strip()
    if not text:
        return ""
    first_line = text.splitlines()[0].strip().strip('"').strip("'")
    return first_line


def _parse_title_tags_response(text: str) -> dict:
    obj = _json_from_text(text, "{", "}")
    if not isinstance(obj, dict):
        return {}
    title = str(obj.get("title") or "").strip()
    tags = obj.get("tags")
    if isinstance(tags, list):
        tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    else:
        tags = []
    return {"title": title, "tags": tags}


class LLMClient:
    def __init__(self, config: dict):
        self.config = normalize_config(config)

    def _get_rule(self, task: str) -> dict:
        rules = self.config.get("custom_system_prompts") or []
        active_prompt_ids = self.config.get("active_prompt_ids") or {}
        active_id = active_prompt_ids.get(task)
        for rule in rules:
            if rule.get("task") == task and rule.get("id") == active_id:
                return rule
        for rule in rules:
            if rule.get("task") == task:
                return rule
        return copy.deepcopy(DEFAULT_PROMPTS_BY_TASK[task][0])

    @property
    def _endpoint(self) -> str:
        base = self.config["base_url"].rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    @property
    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        api_key = self.config.get("api_key", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _transport(self):
        endpoint_lower = self._endpoint.lower()
        if (
            "localhost" in endpoint_lower
            or "127.0.0.1" in endpoint_lower
            or "10." in endpoint_lower
            or "192.168." in endpoint_lower
            or "172." in endpoint_lower
        ):
            return httpx.AsyncHTTPTransport(proxy=None, verify=False)
        return None

    async def _complete(self, task: str, user_prompt: str, max_tokens: int = 512) -> str:
        rule = self._get_rule(task)
        system_prompt = rule.get("prompt") or DEFAULT_PROMPTS_BY_TASK[task][0]["prompt"]
        model = self.config.get("model") or ""

        body: dict = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": max_tokens,
        }
        if model:
            body["model"] = model

        timeout = self.config.get("timeout", 30)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                transport=self._transport(),
                headers=self._headers,
            ) as client:
                resp = await client.post(self._endpoint, json=body)
                if resp.status_code != 200:
                    text = resp.text
                    raise RuntimeError(
                        f"LLM 返回错误 ({resp.status_code}): {text[:200] if text.strip() else '(空响应)'}"
                    )
                data = resp.json()
        except httpx.ConnectError:
            raise RuntimeError(f"无法连接 LLM 服务 ({self._endpoint})，请检查地址和服务状态")
        except asyncio.TimeoutError:
            raise RuntimeError("LLM 响应超时，请增大超时时间或检查模型是否已加载")

        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"LLM 返回格式异常: {json.dumps(data, ensure_ascii=False)[:300]}")

    async def auto_tag(
        self,
        positive: str,
        negative: str,
        existing_tags: list[str] | None = None,
    ) -> list[str]:
        user_prompt = _build_user_prompt(TASK_TAGS, positive, negative, existing_tags or [])
        content = await self._complete(TASK_TAGS, user_prompt, max_tokens=512)
        tags = _parse_tag_response(content)
        if not tags:
            raise RuntimeError(f"无法从 LLM 返回中解析标签: {content[:300]}")
        return tags

    async def auto_title(
        self,
        positive: str,
        negative: str,
        existing_title: str = "",
        existing_tags: list[str] | None = None,
    ) -> str:
        user_prompt = _build_user_prompt(
            TASK_TITLE,
            positive,
            negative,
            existing_tags or [],
            existing_title=existing_title,
        )
        content = await self._complete(TASK_TITLE, user_prompt, max_tokens=256)
        title = _parse_title_response(content)
        if not title:
            raise RuntimeError(f"无法从 LLM 返回中解析标题: {content[:300]}")
        return title

    async def auto_title_and_tags(
        self,
        positive: str,
        negative: str,
        existing_title: str = "",
        existing_tags: list[str] | None = None,
    ) -> dict:
        user_prompt = _build_user_prompt(
            TASK_TITLE_TAGS,
            positive,
            negative,
            existing_tags or [],
            existing_title=existing_title,
        )
        content = await self._complete(TASK_TITLE_TAGS, user_prompt, max_tokens=768)
        result = _parse_title_tags_response(content)
        if not result.get("title") and not result.get("tags"):
            raise RuntimeError(f"无法从 LLM 返回中解析标题和标签: {content[:300]}")
        return result

    async def test_connection(self) -> dict:
        body: dict = {
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 8,
        }
        model = self.config.get("model") or ""
        if model:
            body["model"] = model

        endpoint = self._endpoint
        headers = self._headers
        timeout_sec = min(self.config.get("timeout", 30), 15)
        logger.info("[LLM test] endpoint=%s model=%r timeout=%ds", endpoint, model, timeout_sec)
        logger.debug("[LLM test] headers=%s body=%s", headers, json.dumps(body, ensure_ascii=False))

        try:
            async with httpx.AsyncClient(
                timeout=timeout_sec,
                transport=self._transport(),
                headers=headers,
            ) as client:
                resp = await client.post(endpoint, json=body)
                logger.info("[LLM test] response status=%d", resp.status_code)
                if resp.status_code != 200:
                    text = resp.text
                    logger.warning("[LLM test] error body: %s", text[:500])
                    raise RuntimeError(
                        f"服务返回 {resp.status_code}: {text[:200] if text.strip() else '(空响应，可能模型未加载)'}"
                    )
                data = resp.json()
                logger.debug("[LLM test] response data keys=%s", list(data.keys()))
        except httpx.ConnectError as exc:
            logger.error("[LLM test] connect failed: %s", exc)
            raise RuntimeError(f"无法连接 {endpoint}，请检查地址或确认服务已经启动")
        except asyncio.TimeoutError:
            logger.error("[LLM test] timeout after %ds", timeout_sec)
            raise RuntimeError("连接超时，请检查地址或增加超时时间")

        resp_model = data.get("model", model or "(unknown)")
        logger.info("[LLM test] success, model=%s", resp_model)
        return {"ok": True, "model": resp_model}
