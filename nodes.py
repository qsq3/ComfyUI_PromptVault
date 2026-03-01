import asyncio
import io
import json
import logging
import os
import re
import threading
from collections import deque
from pathlib import Path

logger = logging.getLogger("PromptVault")

import numpy as np
from PIL import Image

from .promptvault.assemble import assemble_entry
from .promptvault.db import PromptVaultStore
from .promptvault.image_metadata import extract_comfyui_metadata
from .promptvault.llm import LLMClient, normalize_config


def _make_thumbnail_png(image_tensor, target_width=256):
    if image_tensor is None:
        raise ValueError("image is required")

    t = image_tensor
    if getattr(t, "ndim", None) == 4:
        t = t[0]
    if getattr(t, "ndim", None) != 3:
        raise ValueError("image tensor must be HWC or BHWC")

    arr = t.detach().cpu().numpy()
    arr = np.clip(arr, 0.0, 1.0)
    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=2)
    elif arr.shape[-1] > 3:
        arr = arr[:, :, :3]

    arr = (arr * 255.0).round().astype(np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError("invalid image size")

    if w != target_width:
        new_h = max(1, int(round(h * (target_width / float(w)))))
        img = img.resize((target_width, new_h), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue(), img.size[0], img.size[1]


def _linked_node_id(value):
    if isinstance(value, (list, tuple)) and value:
        nid = value[0]
        if isinstance(nid, (int, str)):
            return str(nid)
    return None


def _find_sampler_node(prompt):
    if not isinstance(prompt, dict):
        return None, {}
    sampler_types = {"KSampler", "KSamplerAdvanced"}
    best_id = None
    best_node = None
    for node_id, node in prompt.items():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") not in sampler_types:
            continue
        try:
            key = int(node_id)
        except Exception:
            key = -1
        if best_id is None or key > best_id:
            best_id = key
            best_node = node
    return best_id, (best_node or {})


def _extract_prompt_text(prompt, node_id, visited=None):
    if not node_id or not isinstance(prompt, dict):
        return ""
    if visited is None:
        visited = set()
    if node_id in visited:
        return ""
    visited.add(node_id)

    node = prompt.get(str(node_id))
    if not isinstance(node, dict):
        return ""
    inputs = node.get("inputs") or {}
    class_type = node.get("class_type") or ""

    if class_type == "CLIPTextEncode":
        return str(inputs.get("text", "") or "")
    if class_type in {"CLIPTextEncodeSDXL", "CLIPTextEncodeSDXLRefiner"}:
        tg = str(inputs.get("text_g", "") or "")
        tl = str(inputs.get("text_l", "") or "")
        return (tg + ", " + tl).strip(", ")

    for value in inputs.values():
        next_id = _linked_node_id(value)
        if next_id:
            text = _extract_prompt_text(prompt, next_id, visited)
            if text:
                return text
    return ""


def _extract_model_name(prompt, model_node_id):
    if not model_node_id or not isinstance(prompt, dict):
        return ""
    queue = deque([str(model_node_id)])
    visited = set()
    model_keys = ("ckpt_name", "model_name", "unet_name")

    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)

        node = prompt.get(node_id)
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        for key in model_keys:
            value = inputs.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for value in inputs.values():
            next_id = _linked_node_id(value)
            if next_id and next_id not in visited:
                queue.append(next_id)
    return ""


def _extract_generation_data(prompt):
    _, sampler_node = _find_sampler_node(prompt)
    inputs = sampler_node.get("inputs") or {}

    positive_node_id = _linked_node_id(inputs.get("positive"))
    negative_node_id = _linked_node_id(inputs.get("negative"))
    model_node_id = _linked_node_id(inputs.get("model"))

    def _safe_int(value, default):
        try:
            return int(value)
        except Exception:
            return int(default)

    def _safe_float(value, default):
        try:
            return float(value)
        except Exception:
            return float(default)

    def _resolve_linked_scalar(value, fallback=None):
        node_id = _linked_node_id(value)
        if not node_id or not isinstance(prompt, dict):
            return fallback
        node = prompt.get(str(node_id))
        if not isinstance(node, dict):
            return fallback
        n_inputs = node.get("inputs") or {}
        for key in ("seed", "value", "number", "int", "float"):
            if key in n_inputs and not isinstance(n_inputs.get(key), (list, tuple)):
                return n_inputs.get(key)
        widgets = node.get("widgets_values") or []
        if isinstance(widgets, list):
            for v in widgets:
                if isinstance(v, (int, float)):
                    return v
        return fallback

    seed_raw = inputs.get("seed", 0)
    if isinstance(seed_raw, (list, tuple)):
        seed_raw = _resolve_linked_scalar(seed_raw, 0)
    steps_raw = inputs.get("steps", 20)
    if isinstance(steps_raw, (list, tuple)):
        steps_raw = _resolve_linked_scalar(steps_raw, 20)
    cfg_raw = inputs.get("cfg", 7.0)
    if isinstance(cfg_raw, (list, tuple)):
        cfg_raw = _resolve_linked_scalar(cfg_raw, 7.0)

    return {
        "positive": _extract_prompt_text(prompt, positive_node_id),
        "negative": _extract_prompt_text(prompt, negative_node_id),
        "steps": _safe_int(steps_raw or 20, 20),
        "cfg": _safe_float(cfg_raw or 7.0, 7.0),
        "sampler": str(inputs.get("sampler_name", "euler") or "euler"),
        "scheduler": str(inputs.get("scheduler", "normal") or "normal"),
        "seed": _safe_int(seed_raw or 0, 0),
        "model_name": _extract_model_name(prompt, model_node_id),
    }


def _extract_prompt_from_pnginfo(extra_pnginfo):
    if not isinstance(extra_pnginfo, dict):
        return None
    prompt_obj = extra_pnginfo.get("prompt")
    if isinstance(prompt_obj, dict):
        return prompt_obj
    if isinstance(prompt_obj, str) and prompt_obj.strip():
        try:
            parsed = json.loads(prompt_obj)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    return None


def _parse_parameters_text(parameters_text):
    text = (parameters_text or "").strip()
    if not text:
        return {}

    positive = text
    negative = ""
    if "Negative prompt:" in text:
        positive, rest = text.split("Negative prompt:", 1)
        positive = positive.strip()
        negative = rest.strip()
        # Strip trailing key-value settings from negative section.
        parts = negative.rsplit("Steps:", 1)
        if len(parts) == 2:
            negative = parts[0].strip().rstrip(",")
            text = "Steps:" + parts[1]

    data = {"positive": positive, "negative": negative}
    patterns = {
        "steps": r"Steps:\s*(\d+)",
        "cfg": r"CFG scale:\s*([0-9]+(?:\.[0-9]+)?)",
        "sampler": r"Sampler:\s*([^,\n]+)",
        "scheduler": r"Schedule type:\s*([^,\n]+)",
        "seed": r"Seed:\s*(\d+)",
        "model_name": r"Model:\s*([^,\n]+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if not m:
            continue
        value = m.group(1).strip()
        if key in {"steps", "seed"}:
            data[key] = int(value)
        elif key == "cfg":
            data[key] = float(value)
        else:
            data[key] = value
    return data


def _extract_generation_data_from_pnginfo(extra_pnginfo):
    if not isinstance(extra_pnginfo, dict):
        return {}
    params_text = extra_pnginfo.get("parameters")
    if isinstance(params_text, str) and params_text.strip():
        return _parse_parameters_text(params_text)
    return {}


def _extract_workflow_from_pnginfo(extra_pnginfo):
    if not isinstance(extra_pnginfo, dict):
        return None
    workflow = extra_pnginfo.get("workflow")
    if isinstance(workflow, dict):
        return workflow
    if isinstance(workflow, str) and workflow.strip():
        try:
            parsed = json.loads(workflow)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    return None


def _extract_text_from_workflow_node(node):
    values = node.get("widgets_values") or []
    if not isinstance(values, list) or not values:
        return ""
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_from_workflow_obj(workflow):
    if not isinstance(workflow, dict):
        return {}

    nodes = workflow.get("nodes") or []
    links = workflow.get("links") or []
    if not isinstance(nodes, list):
        return {}

    node_by_id = {}
    for n in nodes:
        if isinstance(n, dict) and "id" in n:
            node_by_id[str(n.get("id"))] = n

    link_from = {}
    if isinstance(links, list):
        for link in links:
            if isinstance(link, (list, tuple)) and len(link) >= 5:
                # [link_id, from_node_id, from_slot, to_node_id, to_slot, type?]
                link_id = link[0]
                from_node = str(link[1])
                link_from[link_id] = from_node

    sampler = None
    sampler_id = -1
    for n in nodes:
        if not isinstance(n, dict):
            continue
        ntype = str(n.get("type", ""))
        if "KSampler" not in ntype and "Sampler" not in ntype:
            continue
        nid = int(n.get("id", -1))
        if nid > sampler_id:
            sampler_id = nid
            sampler = n

    if not sampler:
        return {}

    data = {
        "positive": "",
        "negative": "",
        "steps": 20,
        "cfg": 7.0,
        "sampler": "euler",
        "scheduler": "normal",
        "seed": 0,
        "model_name": "",
    }

    widgets = sampler.get("widgets_values") or []
    idx_map = (
        ((workflow.get("widget_idx_map") or {}).get(str(sampler.get("id"))) or {})
        if isinstance(workflow.get("widget_idx_map"), dict)
        else {}
    )
    if not isinstance(idx_map, dict):
        idx_map = {}

    def _widget_by_name(name, default_idx=None, default_val=None):
        idx = idx_map.get(name, default_idx)
        if isinstance(idx, int) and 0 <= idx < len(widgets):
            return widgets[idx]
        return default_val

    if isinstance(widgets, list):
        seed_v = _widget_by_name("seed", 0, None)
        steps_v = _widget_by_name("steps", 2, None)
        cfg_v = _widget_by_name("cfg", 3, None)
        sampler_v = _widget_by_name("sampler_name", 4, None)
        scheduler_v = _widget_by_name("scheduler", 5, None)
        if isinstance(seed_v, (int, float)):
            data["seed"] = int(seed_v)
        if isinstance(steps_v, (int, float)):
            data["steps"] = int(steps_v)
        if isinstance(cfg_v, (int, float)):
            data["cfg"] = float(cfg_v)
        if isinstance(sampler_v, str) and sampler_v.strip():
            data["sampler"] = sampler_v.strip()
        if isinstance(scheduler_v, str) and scheduler_v.strip():
            data["scheduler"] = scheduler_v.strip()

    def _resolve_input_source_node_id(target_node, input_name):
        for inp in target_node.get("inputs") or []:
            if not isinstance(inp, dict):
                continue
            if inp.get("name") != input_name:
                continue
            link_id = inp.get("link")
            if link_id is None:
                return None
            return link_from.get(link_id)
        return None

    pos_src = _resolve_input_source_node_id(sampler, "positive")
    neg_src = _resolve_input_source_node_id(sampler, "negative")
    model_src = _resolve_input_source_node_id(sampler, "model")

    def _find_text_by_backtrace(start_id):
        if not start_id:
            return ""
        queue = deque([str(start_id)])
        visited = set()
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            n = node_by_id.get(nid)
            if not isinstance(n, dict):
                continue
            ntype = str(n.get("type", ""))
            if "CLIPTextEncode" in ntype:
                text = _extract_text_from_workflow_node(n)
                if text:
                    return text
            for inp in n.get("inputs") or []:
                if not isinstance(inp, dict):
                    continue
                link_id = inp.get("link")
                if link_id is None:
                    continue
                src_id = link_from.get(link_id)
                if src_id and src_id not in visited:
                    queue.append(src_id)
        return ""

    if pos_src and pos_src in node_by_id:
        data["positive"] = _find_text_by_backtrace(pos_src) or _extract_text_from_workflow_node(node_by_id[pos_src])
    if neg_src and neg_src in node_by_id:
        data["negative"] = _find_text_by_backtrace(neg_src) or _extract_text_from_workflow_node(node_by_id[neg_src])

    def _find_model_by_backtrace(start_id):
        if not start_id:
            return ""
        queue = deque([str(start_id)])
        visited = set()
        keys = ("ckpt_name", "model_name", "unet_name")
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            n = node_by_id.get(nid)
            if not isinstance(n, dict):
                continue
            vals = n.get("widgets_values") or []
            if isinstance(vals, list):
                for v in vals:
                    if isinstance(v, str) and v.strip():
                        if any(x in v.lower() for x in (".safetensors", ".ckpt", ".pt")):
                            return v.strip()
            for inp in n.get("inputs") or []:
                if not isinstance(inp, dict):
                    continue
                link_id = inp.get("link")
                if link_id is None:
                    continue
                src_id = link_from.get(link_id)
                if src_id and src_id not in visited:
                    queue.append(src_id)
        return ""

    if model_src and model_src in node_by_id:
        data["model_name"] = _find_model_by_backtrace(model_src)

    return data


def _extract_from_workflow(extra_pnginfo):
    workflow = _extract_workflow_from_pnginfo(extra_pnginfo)
    return _extract_from_workflow_obj(workflow)


def _collect_loadimage_paths(prompt, extra_pnginfo):
    raw_paths = []

    if isinstance(prompt, dict):
        for node in prompt.values():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", ""))
            if "LoadImage" not in class_type:
                continue
            image_val = (node.get("inputs") or {}).get("image")
            if isinstance(image_val, str) and image_val.strip():
                raw_paths.append(image_val.strip())

    workflow = _extract_workflow_from_pnginfo(extra_pnginfo)
    if isinstance(workflow, dict):
        for node in workflow.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            ntype = str(node.get("type", ""))
            if "LoadImage" not in ntype:
                continue
            values = node.get("widgets_values") or []
            if isinstance(values, list) and values:
                first = values[0]
                if isinstance(first, str) and first.strip():
                    raw_paths.append(first.strip())

    return raw_paths


def _resolve_existing_image_path(raw_path):
    if not raw_path:
        return None

    cleaned = str(raw_path).strip()
    cleaned = cleaned.split(" [", 1)[0].strip()
    cleaned = cleaned.replace("\\", "/")

    p = Path(cleaned)
    if p.is_file():
        return str(p.resolve())

    bases = []
    try:
        import folder_paths  # type: ignore

        for fn_name in ("get_input_directory", "get_output_directory", "get_temp_directory"):
            fn = getattr(folder_paths, fn_name, None)
            if callable(fn):
                try:
                    v = fn()
                    if v:
                        bases.append(v)
                except Exception:
                    pass
    except Exception:
        pass

    bases.append(os.getcwd())

    for base in bases:
        candidate = Path(base) / cleaned
        if candidate.is_file():
            return str(candidate.resolve())

    return None


def _extract_from_source_image_metadata(prompt, extra_pnginfo):
    raw_paths = _collect_loadimage_paths(prompt, extra_pnginfo)
    seen = set()
    resolved_paths = []
    for raw in raw_paths:
        resolved = _resolve_existing_image_path(raw)
        if resolved and resolved not in seen:
            seen.add(resolved)
            resolved_paths.append(resolved)

    for image_path in resolved_paths:
        try:
            meta = extract_comfyui_metadata(image_path)
            found = meta.get("found") or {}
            data = {}

            prompt_obj = found.get("prompt")
            if isinstance(prompt_obj, str):
                try:
                    prompt_obj = json.loads(prompt_obj)
                except Exception:
                    prompt_obj = None
            if isinstance(prompt_obj, dict):
                data.update(_extract_generation_data(prompt_obj))

            workflow_obj = found.get("workflow")
            if isinstance(workflow_obj, str):
                try:
                    workflow_obj = json.loads(workflow_obj)
                except Exception:
                    workflow_obj = None
            if isinstance(workflow_obj, dict):
                wf_data = _extract_from_workflow_obj(workflow_obj)
                for k, v in wf_data.items():
                    if v not in (None, "", 0):
                        data[k] = v

            params_text = found.get("parameters")
            if isinstance(params_text, str) and params_text.strip():
                params_data = _parse_parameters_text(params_text)
                for k, v in params_data.items():
                    if v not in (None, "", 0):
                        data[k] = v

            if data:
                return data, resolved_paths
        except Exception:
            continue

    return {}, resolved_paths


def _debug_dump_png_meta(
    extra_pnginfo,
    prompt_from_png,
    png_meta_data,
    workflow_data,
    image_meta_data,
    image_meta_paths,
    final_data,
):
    try:
        dump_items = [
            ("extra_pnginfo", extra_pnginfo),
            ("prompt_from_png", prompt_from_png),
            ("workflow_data", workflow_data),
            ("png_meta_data", png_meta_data),
            ("source_image_paths", image_meta_paths),
            ("source_image_meta_data", image_meta_data),
            ("final_generation_data", final_data),
        ]
        print("[PromptVaultSaveNode] extracted metadata begin")
        for label, value in dump_items:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
            print(f"[PromptVaultSaveNode] {label}: {serialized}")
            logger.debug("%s: %s", label, serialized)
        print("[PromptVaultSaveNode] extracted metadata end")
    except Exception as exc:
        logger.debug("dump failed: %s", exc)


def _first_five_chars(text):
    return (text or "").strip()[:5].strip()


def _run_async_sync(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result = {"value": None, "error": None}

    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result["value"] = loop.run_until_complete(awaitable)
        except Exception as exc:
            result["error"] = exc
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    thread = threading.Thread(target=_worker, name="PromptVaultAsyncRunner", daemon=True)
    thread.start()
    thread.join()
    if result["error"] is not None:
        raise result["error"]
    return result["value"]


def _maybe_auto_fill_with_llm(title, tags, positive, negative, auto_generate, auto_generate_mode):
    final_title = (title or "").strip()
    final_tags = list(tags or [])

    if not auto_generate:
        return final_title, final_tags, False
    if not (positive or negative):
        return final_title, final_tags, False

    need_title = auto_generate_mode in {"title_only", "title_and_tags"} or (
        auto_generate_mode == "auto" and not final_title
    )
    need_tags = auto_generate_mode in {"tags_only", "title_and_tags"} or (
        auto_generate_mode == "auto" and not final_tags
    )
    if not need_title and not need_tags:
        return final_title, final_tags, False

    store = PromptVaultStore.get()
    config = normalize_config(store.get_llm_config())
    if not config.get("enabled"):
        logger.info("PromptVaultSaveNode auto_generate skipped: llm disabled")
        return final_title, final_tags, False

    client = LLMClient(config)
    changed = False
    try:
        if need_title and need_tags:
            result = _run_async_sync(
                client.auto_title_and_tags(
                    positive,
                    negative,
                    existing_title=final_title,
                    existing_tags=final_tags,
                )
            ) or {}
            new_title = str(result.get("title") or "").strip()
            new_tags = [str(tag).strip() for tag in (result.get("tags") or []) if str(tag).strip()]
            if new_title:
                final_title = new_title
                changed = True
            if new_tags:
                final_tags = list(dict.fromkeys(final_tags + new_tags))[:5]
                changed = True
        elif need_title:
            new_title = _run_async_sync(
                client.auto_title(
                    positive,
                    negative,
                    existing_title=final_title,
                    existing_tags=final_tags,
                )
            )
            new_title = str(new_title or "").strip()
            if new_title:
                final_title = new_title
                changed = True
        elif need_tags:
            new_tags = _run_async_sync(client.auto_tag(positive, negative, final_tags)) or []
            new_tags = [str(tag).strip() for tag in new_tags if str(tag).strip()]
            if new_tags:
                final_tags = list(dict.fromkeys(final_tags + new_tags))[:5]
                changed = True
    except Exception as exc:
        logger.warning("PromptVaultSaveNode auto_generate failed: %s", exc)

    return final_title, final_tags, changed


class PromptVaultQueryNode:
    SEARCH_LIMIT = 10

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "query": ("STRING", {"default": "", "multiline": False}),
                "title": ("STRING", {"default": "", "multiline": False}),
                "tags": ("STRING", {"default": "", "multiline": False}),
                "model": ("STRING", {"default": "", "multiline": False}),
                "mode": (["auto", "locked"], {"default": "auto"}),
                "entry_id": ("STRING", {"default": "", "multiline": False}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt")
    FUNCTION = "run"
    CATEGORY = "PromptVault"

    def run(self, mode, entry_id, query, title, tags, model):
        store = PromptVaultStore.get()
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        title_kw = (title or "").strip()
        query_kw = (query or "").strip()
        locked_entry_id = (entry_id or "").strip()

        if mode == "locked" and locked_entry_id:
            try:
                entry = store.get_entry(locked_entry_id)
            except Exception as exc:
                logger.error("get_entry failed in locked mode: %s", exc)
                return ("", "")
            logger.debug(
                "selected_entry_locked: id=%s title=%s version=%s",
                entry.get("id"),
                entry.get("title"),
                entry.get("version"),
            )
            try:
                assembled = assemble_entry(store=store, entry=entry)
                logger.debug(
                    "assembled_len_locked: positive=%d negative=%d",
                    len(str(assembled.get("positive", "") or "")),
                    len(str(assembled.get("negative", "") or "")),
                )
                return (
                    str(assembled.get("positive", "") or ""),
                    str(assembled.get("negative", "") or ""),
                )
            except Exception as exc:
                logger.warning("assemble failed in locked mode, fallback raw: %s", exc)
                raw = entry.get("raw", {}) if isinstance(entry, dict) else {}
                return (str(raw.get("positive", "") or ""), str(raw.get("negative", "") or ""))

        search_q = query_kw
        if title_kw:
            search_q = f"{title_kw} {query_kw}".strip()

        def _do_search(qv, tags_v, model_v, stage):
            try:
                rows = store.search_entries(
                    q=qv,
                    tags=tags_v,
                    model=model_v,
                    status="active",
                    limit=self.SEARCH_LIMIT,
                )
                logger.debug("stage=%s hits=%d q=%r tags=%s model=%r", stage, len(rows), qv, tags_v, model_v)
                return rows
            except Exception as exc:
                logger.error("stage=%s search failed: %s", stage, exc)
                return []

        # Progressive relaxation to avoid over-filtering by model/tags.
        hits = _do_search(search_q, tag_list, model or "", "strict")
        if not hits and (tag_list or (model or "").strip()):
            hits = _do_search(search_q, tag_list, "", "drop_model")
        if not hits and tag_list:
            hits = _do_search(search_q, [], model or "", "drop_tags")
        if not hits and (tag_list or (model or "").strip()):
            hits = _do_search(search_q, [], "", "q_only")
        if not hits and title_kw and query_kw:
            hits = _do_search(query_kw, [], "", "query_only")
        if not hits and title_kw:
            hits = _do_search(title_kw, [], "", "title_only")
        if not hits:
            hits = _do_search("", [], "", "latest_active")

        if title_kw and hits:
            lower_title = title_kw.lower()
            title_hits = [h for h in hits if lower_title in (h.get("title", "").lower())]
            if title_hits:
                hits = title_hits
                logger.debug("title_filtered_hits=%d", len(hits))

        if not hits:
            return ("", "")

        entry_id = hits[0].get("id")
        if not entry_id:
            logger.warning("first hit has no id")
            return ("", "")

        try:
            entry = store.get_entry(entry_id)
        except Exception as exc:
            logger.error("get_entry failed: %s", exc)
            return ("", "")
        logger.debug("selected_entry: id=%s title=%s version=%s",
                      entry.get("id"), entry.get("title"), entry.get("version"))

        try:
            assembled = assemble_entry(store=store, entry=entry)
            logger.debug("assembled_len: positive=%d negative=%d",
                         len(str(assembled.get("positive", "") or "")),
                         len(str(assembled.get("negative", "") or "")))
            return (
                str(assembled.get("positive", "") or ""),
                str(assembled.get("negative", "") or ""),
            )
        except Exception as exc:
            logger.warning("assemble failed, fallback raw: %s", exc)
            raw = entry.get("raw", {}) if isinstance(entry, dict) else {}
            return (str(raw.get("positive", "") or ""), str(raw.get("negative", "") or ""))

class PromptVaultSaveNode:
    @staticmethod
    def _default_llm_generate_enabled():
        try:
            store = PromptVaultStore.get()
            config = normalize_config(store.get_llm_config())
            return bool(config.get("enabled"))
        except Exception as exc:
            logger.debug("PromptVaultSaveNode default llm_generate fallback: %s", exc)
            return False

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "title": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "tags": ("STRING", {"default": "", "multiline": False}),
                "model": ("STRING", {"default": "", "multiline": False}),
                "positive_prompt": ("STRING", {"default": "", "multiline": True}),
                "negative_prompt": ("STRING", {"default": "", "multiline": True}),
                "llm_generate": ("BOOLEAN", {"default": cls._default_llm_generate_enabled()}),
                "llm_generate_mode": (["auto", "title_only", "tags_only", "title_and_tags"], {"default": "title_and_tags"}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("entry_id", "status")
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "PromptVault"

    def run(
        self,
        image,
        title,
        tags="",
        model="",
        positive_prompt="",
        negative_prompt="",
        llm_generate=False,
        llm_generate_mode="auto",
        auto_generate=None,
        auto_generate_mode=None,
        prompt=None,
        extra_pnginfo=None,
    ):
        try:
            thumb_png, thumb_w, thumb_h = _make_thumbnail_png(image, target_width=256)
        except Exception as exc:
            return ("", f"保存失败: 缩略图处理错误: {exc}")
       
        # Prefer PNG metadata, then fallback to current workflow prompt.
        prompt_from_png = _extract_prompt_from_pnginfo(extra_pnginfo)
        data = _extract_generation_data(prompt_from_png or prompt)
        workflow_data = _extract_from_workflow(extra_pnginfo)
        for key, value in workflow_data.items():
            if value not in (None, "", 0):
                data[key] = value
        png_meta_data = _extract_generation_data_from_pnginfo(extra_pnginfo)
        for key, value in png_meta_data.items():
            if value not in (None, "", 0):
                data[key] = value
        image_meta_data, image_meta_paths = _extract_from_source_image_metadata(prompt, extra_pnginfo)
        for key, value in image_meta_data.items():
            if value not in (None, "", 0):
                data[key] = value
    
        _debug_dump_png_meta(
            extra_pnginfo,
            prompt_from_png,
            png_meta_data,
            workflow_data,
            image_meta_data,
            image_meta_paths,
            data,
        )
        positive = str(positive_prompt or "").strip() or data.get("positive", "")
        negative = str(negative_prompt or "").strip() or data.get("negative", "")
        effective_llm_generate = bool(auto_generate) if auto_generate is not None else bool(llm_generate)
        effective_llm_generate_mode = (
            str(auto_generate_mode or "auto")
            if auto_generate_mode is not None
            else str(llm_generate_mode or "auto")
        )
        if not str(positive or "").strip():
            return ("", "保存失败: 未提取到正向提示词，请确认输入图像或工作流元数据")
        fallback5 = _first_five_chars(positive)

        final_title = (title or "").strip()
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]

        final_title, tag_list, llm_changed = _maybe_auto_fill_with_llm(
            final_title,
            tag_list,
            positive,
            negative,
            effective_llm_generate,
            effective_llm_generate_mode,
        )

        if not final_title:
            final_title = fallback5 or "未命名"
        if not tag_list and fallback5:
            tag_list = [fallback5]

        model_list = [m.strip() for m in (model or "").split(",") if m.strip()]
        auto_model = data.get("model_name", "").strip()
        if not model_list and auto_model:
            model_list = [auto_model]

        payload = {
            "title": final_title,
            "tags": tag_list,
            "model_scope": model_list,
            "raw": {
                "positive": positive,
                "negative": negative,
            },
            "params": {
                "steps": data.get("steps", 20),
                "cfg": data.get("cfg", 7.0),
                "sampler": data.get("sampler", "euler"),
                "scheduler": data.get("scheduler", "normal"),
                "seed": data.get("seed", 0),
            },
            "thumbnail_png": thumb_png,
            "thumbnail_width": thumb_w,
            "thumbnail_height": thumb_h,
        }

        try:
            store = PromptVaultStore.get()
            entry = store.create_entry(payload)
            status = "保存成功"
            if llm_changed:
                status += " (AI 已补全标题或标签)"
            return (entry.get("id", ""), status)
        except Exception as exc:
            return ("", f"保存失败: {exc}")


MODEL_RESOLUTIONS = {
    "Qwen-Image": [
        (1328, 1328),
        (1664, 928),
        (928, 1664),
        (1472, 1104),
        (1104, 1472),
        (1584, 1056),
        (1056, 1584),
    ],
    "FLUX": [
        (1024, 1024),
        (1920, 1088),
        (1088, 1920),
        (1408, 1056),
        (1056, 1408),
        (2560, 1440),
    ],
    "SDXL": [
        (1024, 1024),
        (1344, 768),
        (768, 1344),
        (1152, 896),
        (896, 1152),
    ],
    "Z-Image": [
        (1024, 1024),
        (1600, 900),
        (720, 1280),
        (1440, 1440),
        (1920, 1088),
    ],
}

_ALL_MODELS = sorted(MODEL_RESOLUTIONS.keys())
_SIZE_LOOKUP = {}
for _m, _sizes in MODEL_RESOLUTIONS.items():
    for _w, _h in _sizes:
        _SIZE_LOOKUP.setdefault(f"{_w}x{_h}", []).append(_m)
_ALL_SIZES = sorted(_SIZE_LOOKUP.keys(), key=lambda s: [int(x) for x in s.split("x")])


class ModelResolutionNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (_ALL_MODELS, {"default": _ALL_MODELS[0]}),
                "size": (_ALL_SIZES, {"default": "1024x1024"}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "STRING")
    RETURN_NAMES = ("width", "height", "info")
    FUNCTION = "run"
    CATEGORY = "PromptVault"

    def run(self, model, size):
        sizes = MODEL_RESOLUTIONS.get(model, [])
        size_map = {f"{w}x{h}": (w, h) for w, h in sizes}
        if size in size_map:
            w, h = size_map[size]
            return (w, h, f"{model}: {w}×{h}")
        available = ", ".join(f"{w}x{h}" for w, h in sizes)
        w, h = sizes[0] if sizes else (1024, 1024)
        return (w, h, f"{model} 不支持 {size}，已回退 {w}×{h} | 可选: {available}")


NODE_CLASS_MAPPINGS = {
    "PromptVaultQuery": PromptVaultQueryNode,
    "PromptVaultSave": PromptVaultSaveNode,
    "ModelResolution": ModelResolutionNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptVaultQuery": "提示词库检索",
    "PromptVaultSave": "提示词库保存",
    "ModelResolution": "模型出图尺寸",
}
