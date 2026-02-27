import json
import base64

from aiohttp import web

from .assemble import assemble_entry
from .db import PromptVaultStore


def _json_response(obj, status=200):
    return web.Response(
        status=status,
        text=json.dumps(obj, ensure_ascii=False),
        content_type="application/json",
    )


def _bad_request(msg):
    return _json_response({"error": msg}, status=400)


def setup_routes():
    from server import PromptServer  # type: ignore

    routes = PromptServer.instance.routes

    @routes.get("/promptvault/health")
    async def health(_request):
        store = PromptVaultStore.get()
        return _json_response({"ok": True, "db_path": store.db_path})

    @routes.get("/promptvault/entries")
    async def list_entries(request):
        store = PromptVaultStore.get()
        q = request.query.get("q", "")
        tags = request.query.get("tags", "")
        model = request.query.get("model", "")
        status = request.query.get("status", "active")
        limit = int(request.query.get("limit", "20"))
        offset = int(request.query.get("offset", "0"))

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        items = store.search_entries(q=q, tags=tag_list, model=model, status=status, limit=limit, offset=offset)
        return _json_response({"items": items, "limit": limit, "offset": offset})

    @routes.post("/promptvault/entries/purge_deleted")
    async def purge_deleted(_request):
        """清空回收站：硬删除所有 status=deleted 的记录。"""
        store = PromptVaultStore.get()
        count = store.purge_deleted_entries()
        return _json_response({"deleted": count})

    @routes.post("/promptvault/tags/tidy")
    async def tidy_tags(_request):
        """整理标签：删除无记录引用的标签，补充缺失标签。"""
        store = PromptVaultStore.get()
        result = store.tidy_tags()
        return _json_response(result)

    @routes.post("/promptvault/entries")
    async def create_entry(request):
        store = PromptVaultStore.get()
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        entry = store.create_entry(payload or {})
        return _json_response(entry, status=201)

    @routes.get("/promptvault/entries/{entry_id}")
    async def get_entry(request):
        store = PromptVaultStore.get()
        entry_id = request.match_info["entry_id"]
        try:
            entry = store.get_entry(entry_id)
        except KeyError:
            return _json_response({"error": "未找到记录"}, status=404)
        try:
            thumb = store.get_entry_thumbnail(entry_id)
            if thumb and thumb.get("png"):
                b64 = base64.b64encode(thumb["png"]).decode("ascii")
                entry["thumbnail_data_url"] = f"data:image/png;base64,{b64}"
        except Exception:
            entry["thumbnail_data_url"] = ""
        return _json_response(entry)

    @routes.get("/promptvault/entries/{entry_id}/thumbnail")
    async def get_entry_thumbnail(request):
        store = PromptVaultStore.get()
        entry_id = request.match_info["entry_id"]
        try:
            thumb = store.get_entry_thumbnail(entry_id)
        except KeyError:
            return _json_response({"error": "未找到记录"}, status=404)
        if not thumb:
            return _json_response({"error": "未找到缩略图"}, status=404)
        return web.Response(
            body=thumb["png"],
            content_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @routes.put("/promptvault/entries/{entry_id}")
    async def update_entry(request):
        store = PromptVaultStore.get()
        entry_id = request.match_info["entry_id"]
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        try:
            entry = store.update_entry(entry_id, payload or {})
        except KeyError:
            return _json_response({"error": "未找到记录"}, status=404)
        return _json_response(entry)

    @routes.delete("/promptvault/entries/{entry_id}")
    async def delete_entry(request):
        store = PromptVaultStore.get()
        entry_id = request.match_info["entry_id"]
        try:
            entry = store.delete_entry(entry_id)
        except KeyError:
            return _json_response({"error": "未找到记录"}, status=404)
        return _json_response(entry)

    @routes.get("/promptvault/entries/{entry_id}/versions")
    async def list_versions(request):
        store = PromptVaultStore.get()
        entry_id = request.match_info["entry_id"]
        try:
            store.get_entry(entry_id)
        except KeyError:
            return _json_response({"error": "未找到记录"}, status=404)
        items = store.list_entry_versions(entry_id)
        return _json_response({"items": items})

    @routes.post("/promptvault/assemble")
    async def assemble(request):
        store = PromptVaultStore.get()
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")

        entry_id = (payload or {}).get("entry_id")
        if not entry_id:
            return _bad_request("缺少 entry_id")

        variables_override = (payload or {}).get("variables_override") or {}
        if not isinstance(variables_override, dict):
            return _bad_request("variables_override 必须是对象")

        model_hint = (payload or {}).get("model_hint") or ""

        try:
            entry = store.get_entry(entry_id)
        except KeyError:
            return _json_response({"error": "未找到记录"}, status=404)

        assembled = assemble_entry(store=store, entry=entry, variables_override=variables_override, model_hint=model_hint)
        return _json_response(assembled)

    @routes.post("/promptvault/fragments")
    async def upsert_fragment(request):
        store = PromptVaultStore.get()
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        frag = store.upsert_fragment(payload or {})
        return _json_response(frag, status=201)

    @routes.get("/promptvault/fragments/{frag_id}")
    async def get_fragment(request):
        store = PromptVaultStore.get()
        frag_id = request.match_info["frag_id"]
        try:
            frag = store.get_fragment(frag_id)
        except KeyError:
            return _json_response({"error": "未找到片段"}, status=404)
        return _json_response(frag)

    @routes.post("/promptvault/templates")
    async def upsert_template(request):
        store = PromptVaultStore.get()
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        tpl = store.upsert_template(payload or {})
        return _json_response(tpl, status=201)

    @routes.get("/promptvault/templates/{tpl_id}")
    async def get_template(request):
        store = PromptVaultStore.get()
        tpl_id = request.match_info["tpl_id"]
        try:
            tpl = store.get_template(tpl_id)
        except KeyError:
            return _json_response({"error": "未找到模板"}, status=404)
        return _json_response(tpl)

    @routes.get("/promptvault/tags")
    async def list_tags(request):
        store = PromptVaultStore.get()
        limit = int(request.query.get("limit", "200"))
        items = store.list_tags(limit=limit)
        return _json_response({"items": items, "limit": limit})
