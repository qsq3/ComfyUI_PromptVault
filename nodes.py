from .promptvault.assemble import assemble_entry
from .promptvault.db import PromptVaultStore


class PromptVaultQueryNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "query": ("STRING", {"default": "", "multiline": False}),
                "title": ("STRING", {"default": "", "multiline": False}),
                "tags": ("STRING", {"default": "", "multiline": False}),
                "model": ("STRING", {"default": "", "multiline": False}),
                "top_k": ("INT", {"default": 1, "min": 1, "max": 50, "step": 1}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt")
    FUNCTION = "run"
    CATEGORY = "提示词库"

    def run(self, query, title, tags, model, top_k):
        store = PromptVaultStore.get()
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        title_kw = (title or "").strip()
        query_kw = (query or "").strip()

        # If title is provided, include it in the FTS query to improve hit quality.
        search_q = query_kw
        if title_kw:
            search_q = f"{title_kw} {query_kw}".strip()

        hits = store.search_entries(
            q=search_q,
            tags=tag_list,
            model=model or "",
            status="active",
            limit=max(1, int(top_k)),
        )

        if title_kw and hits:
            lower_title = title_kw.lower()
            title_hits = [h for h in hits if lower_title in (h.get("title", "").lower())]
            if title_hits:
                hits = title_hits

        if not hits:
            return ("", "")

        entry = store.get_entry(hits[0]["id"])
        assembled = assemble_entry(store=store, entry=entry, variables_override={})
        return (
            assembled.get("positive", ""),
            assembled.get("negative", ""),
        )


NODE_CLASS_MAPPINGS = {
    "PromptVaultQuery": PromptVaultQueryNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptVaultQuery": "提示词库检索",
}
