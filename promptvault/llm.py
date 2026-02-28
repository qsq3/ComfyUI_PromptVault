import asyncio
import json
import logging
import re

import aiohttp

logger = logging.getLogger("PromptVault")

DEFAULT_SYSTEM_PROMPT = (
    "你是一个图像生成提示词分析专家。根据以下正向和负向提示词，生成5到15个相关标签。\n"
    "标签应涵盖：主题、风格、画质、场景、人物特征、光照、构图等维度。\n"
    "标签可以是中文或英文，每个标签2-4个字/单词。\n"
    "只返回 JSON 数组，不要其他文字。\n\n"
    '示例输出: ["人像", "电影感", "黄金时段", "浅景深", "portrait", "cinematic"]'
)

DEFAULT_LLM_CONFIG = {
    "enabled": False,
    "base_url": "http://localhost:1234",
    "model": "",
    "api_key": "",
    "timeout": 30,
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
}


def _build_user_prompt(positive: str, negative: str, existing_tags: list[str]) -> str:
    parts = []
    if positive.strip():
        parts.append(f"正向提示词:\n{positive.strip()}")
    if negative.strip():
        parts.append(f"负向提示词:\n{negative.strip()}")
    if existing_tags:
        parts.append(f"已有标签: {', '.join(existing_tags)}")
        parts.append("请在已有标签基础上补充新标签，避免重复。")
    return "\n\n".join(parts)


def _parse_tag_response(text: str) -> list[str]:
    """Extract a JSON array of tags from LLM response text."""
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [str(t).strip() for t in result if str(t).strip()]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(t).strip() for t in result if str(t).strip()]
        except json.JSONDecodeError:
            pass

    return []


class LLMClient:
    def __init__(self, config: dict):
        self.config = {**DEFAULT_LLM_CONFIG, **config}

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

    async def auto_tag(
        self,
        positive: str,
        negative: str,
        existing_tags: list[str] | None = None,
    ) -> list[str]:
        existing_tags = existing_tags or []
        system_prompt = self.config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
        user_prompt = _build_user_prompt(positive, negative, existing_tags)
        model = self.config.get("model") or ""

        body: dict = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        }
        if model:
            body["model"] = model

        timeout = aiohttp.ClientTimeout(total=self.config.get("timeout", 30))
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.post(
                    self._endpoint, json=body, headers=self._headers
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise RuntimeError(
                            f"LLM 返回错误 ({resp.status}): {text[:200] if text.strip() else '(空响应)'}"
                        )
                    data = await resp.json()
        except aiohttp.ClientConnectorError:
            raise RuntimeError(
                f"无法连接 LM Studio ({self._endpoint})，请检查地址和服务状态"
            )
        except asyncio.TimeoutError:
            raise RuntimeError("LLM 响应超时，请增大超时时间或检查模型是否已加载")

        content = ""
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"LLM 返回格式异常: {json.dumps(data, ensure_ascii=False)[:300]}")

        tags = _parse_tag_response(content)
        if not tags:
            raise RuntimeError(f"无法从 LLM 返回中解析标签: {content[:300]}")
        return tags

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

        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.post(
                    endpoint, json=body, headers=headers
                ) as resp:
                    logger.info("[LLM test] response status=%d", resp.status)
                    if resp.status != 200:
                        text = await resp.text()
                        logger.warning("[LLM test] error body: %s", text[:500])
                        raise RuntimeError(
                            f"服务返回 {resp.status}: {text[:200] if text.strip() else '(空响应，可能模型未加载)'}"
                        )
                    data = await resp.json()
                    logger.debug("[LLM test] response data keys=%s", list(data.keys()))
        except aiohttp.ClientConnectorError as e:
            logger.error("[LLM test] connect failed: %s", e)
            raise RuntimeError(
                f"无法连接 {endpoint}，请检查地址和 LM Studio 是否启动"
            )
        except asyncio.TimeoutError:
            logger.error("[LLM test] timeout after %ds", timeout_sec)
            raise RuntimeError("连接超时，请检查地址或增大超时时间")

        resp_model = data.get("model", model or "(unknown)")
        logger.info("[LLM test] success, model=%s", resp_model)
        return {"ok": True, "model": resp_model}
