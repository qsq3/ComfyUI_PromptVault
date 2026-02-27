import json

from .promptvault.db import PromptVaultStore
from .promptvault.assemble import assemble_entry


class PromptVaultQueryNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "query": ("STRING", {"default": "", "multiline": False}),
                "tags": ("STRING", {"default": "", "multiline": False}),
                "model": ("STRING", {"default": "", "multiline": False}),
                "top_k": ("INT", {"default": 1, "min": 1, "max": 50, "step": 1}),
                "variables_json": ("STRING", {"default": "{}", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "entry_id", "meta_json")
    FUNCTION = "run"
    CATEGORY = "提示词库"

    def run(self, query, tags, model, top_k, variables_json):
        try:
            variables = json.loads(variables_json) if variables_json.strip() else {}
            if not isinstance(variables, dict):
                raise ValueError("variables_json must be a JSON object")
        except Exception as e:
            meta = {"error": f"variables_json 解析失败: {e}"}
            return ("", "", "", json.dumps(meta, ensure_ascii=False))

        store = PromptVaultStore.get()
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]

        hits = store.search_entries(
            q=query or "",
            tags=tag_list,
            model=model or "",
            status="active",
            limit=max(1, int(top_k)),
        )

        if not hits:
            meta = {"warning": "未找到匹配提示词", "query": query, "tags": tag_list, "model": model}
            return ("", "", "", json.dumps(meta, ensure_ascii=False))

        entry = store.get_entry(hits[0]["id"])
        assembled = assemble_entry(store=store, entry=entry, variables_override=variables)

        meta = {
            "id": entry["id"],
            "title": entry.get("title", ""),
            "tags": entry.get("tags", []),
            "version": entry.get("version", 1),
            "trace": assembled.get("trace", []),
        }
        return (
            assembled.get("positive", ""),
            assembled.get("negative", ""),
            entry["id"],
            json.dumps(meta, ensure_ascii=False),
        )


NODE_CLASS_MAPPINGS = {
    "PromptVaultQuery": PromptVaultQueryNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptVaultQuery": "提示词库检索",
}

