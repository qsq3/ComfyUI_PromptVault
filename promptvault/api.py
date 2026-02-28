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


def _decode_thumbnail_b64(payload):
    """If payload contains thumbnail_b64, decode it into thumbnail_png bytes."""
    b64 = (payload or {}).get("thumbnail_b64")
    if not b64 or not isinstance(b64, str):
        return
    raw = b64.split(",", 1)[-1]
    try:
        png_bytes = base64.b64decode(raw)
    except Exception:
        return
    if len(png_bytes) < 8:
        return
    payload["thumbnail_png"] = png_bytes
    payload.pop("thumbnail_b64", None)
    w = payload.get("thumbnail_width")
    h = payload.get("thumbnail_height")
    if isinstance(w, (int, float)) and isinstance(h, (int, float)):
        payload["thumbnail_width"] = int(w)
        payload["thumbnail_height"] = int(h)


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
        try:
            limit = max(1, min(200, int(request.query.get("limit", "20"))))
        except (TypeError, ValueError):
            limit = 20
        try:
            offset = max(0, int(request.query.get("offset", "0")))
        except (TypeError, ValueError):
            offset = 0

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
        _decode_thumbnail_b64(payload)
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
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @routes.put("/promptvault/entries/{entry_id}")
    async def update_entry(request):
        store = PromptVaultStore.get()
        entry_id = request.match_info["entry_id"]
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        _decode_thumbnail_b64(payload)
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
        try:
            limit = max(1, min(1000, int(request.query.get("limit", "200"))))
        except (TypeError, ValueError):
            limit = 200
        items = store.list_tags(limit=limit)
        return _json_response({"items": items, "limit": limit})

    @routes.post("/promptvault/extract_image_metadata")
    async def extract_image_metadata(request):
        """Accept a base64-encoded image, write to temp file, extract metadata."""
        import io
        import tempfile
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        b64 = (payload or {}).get("image_b64", "")
        if not b64:
            return _bad_request("缺少 image_b64")
        raw = b64.split(",", 1)[-1]
        try:
            img_bytes = base64.b64decode(raw)
        except Exception:
            return _bad_request("base64 解码失败")

        from .image_metadata import extract_from_info, extract_exif_xmp
        from PIL import Image as PILImage

        try:
            img = PILImage.open(io.BytesIO(img_bytes))
            info = dict(getattr(img, "info", {}) or {})
            found = {}
            found.update(extract_from_info(info))
            if (img.format or "").upper() != "PNG":
                found.update(extract_exif_xmp(img))
            img.close()
        except Exception as exc:
            return _json_response({"found": {}, "error": f"图片解析失败: {exc}"})

        if not found:
            return _json_response({"found": {}, "data": {}})

        from ..nodes import (
            _extract_generation_data,
            _extract_from_workflow_obj,
            _parse_parameters_text,
        )

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

        return _json_response({"found": list(found.keys()), "data": data})

    @routes.get("/promptvault/model_resolutions")
    async def model_resolutions(_request):
        from ..nodes import MODEL_RESOLUTIONS
        data = {}
        for model, sizes in MODEL_RESOLUTIONS.items():
            data[model] = [f"{w}x{h}" for w, h in sizes]
        return _json_response(data)
