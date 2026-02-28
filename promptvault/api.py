import base64
import json
from datetime import datetime

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


def _download_name(ext):
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"promptvault-export-{stamp}.{ext}"


def setup_routes():
    from server import PromptServer  # type: ignore

    routes = PromptServer.instance.routes

    def _sanitize_llm_config(config):
        safe = dict(config or {})
        key = safe.get("api_key", "")
        if key and len(key) > 4:
            safe["api_key"] = key[:2] + "*" * (len(key) - 4) + key[-2:]
        return safe

    def _validate_llm_payload(payload):
        positive = str((payload or {}).get("positive", "") or "")
        negative = str((payload or {}).get("negative", "") or "")
        existing_tags = (payload or {}).get("existing_tags", [])
        existing_title = str((payload or {}).get("existing_title", "") or "").strip()
        if not positive and not negative:
            return None, None, None, None, _bad_request("正向和负向提示词不能同时为空")
        if not isinstance(existing_tags, list):
            existing_tags = []
        existing_tags = [str(tag).strip() for tag in existing_tags if str(tag).strip()]
        return positive, negative, existing_tags, existing_title, None

    def _load_llm_config(require_enabled=True):
        from .llm import normalize_config

        store = PromptVaultStore.get()
        config = normalize_config(store.get_llm_config())
        if require_enabled and not config.get("enabled"):
            return None, _json_response(
                {"error": "LLM 功能未启用，请先在设置中开启并配置 LM Studio 地址。"},
                status=400,
            )
        return config, None

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
        sort = request.query.get("sort", "updated_desc")
        favorite_only = request.query.get("favorite_only", "").strip().lower() in {"1", "true", "yes", "on"}
        has_thumbnail = request.query.get("has_thumbnail", "").strip().lower() in {"1", "true", "yes", "on"}
        try:
            limit = max(1, min(200, int(request.query.get("limit", "20"))))
        except (TypeError, ValueError):
            limit = 20
        try:
            offset = max(0, int(request.query.get("offset", "0")))
        except (TypeError, ValueError):
            offset = 0

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        items = store.search_entries(
            q=q,
            tags=tag_list,
            model=model,
            status=status,
            limit=limit,
            offset=offset,
            sort=sort,
            favorite_only=favorite_only,
            has_thumbnail=has_thumbnail,
        )
        total = store.count_entries(
            q=q,
            tags=tag_list,
            model=model,
            status=status,
            favorite_only=favorite_only,
            has_thumbnail=has_thumbnail,
        )
        return _json_response(
            {
                "items": items,
                "limit": limit,
                "offset": offset,
                "total": total,
                "sort": sort,
                "filters": {
                    "favorite_only": favorite_only,
                    "has_thumbnail": has_thumbnail,
                },
            }
        )

    @routes.post("/promptvault/entries/purge_deleted")
    async def purge_deleted(_request):
        store = PromptVaultStore.get()
        count = store.purge_deleted_entries()
        return _json_response({"deleted": count})

    @routes.post("/promptvault/tags/tidy")
    async def tidy_tags(_request):
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

        assembled = assemble_entry(
            store=store,
            entry=entry,
            variables_override=variables_override,
            model_hint=model_hint,
        )
        return _json_response(assembled)

    @routes.get("/promptvault/export")
    async def export_promptvault(request):
        store = PromptVaultStore.get()
        fmt = str(request.query.get("format", "json") or "json").strip().lower()
        if fmt == "json":
            text = json.dumps(store.export_bundle(), ensure_ascii=False, indent=2)
            return web.Response(
                text=text,
                content_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{_download_name("json")}"'},
            )
        if fmt == "csv":
            text = store.export_bundle_csv()
            return web.Response(
                text=text,
                content_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{_download_name("csv")}"'},
            )
        return _bad_request("仅支持 json 或 csv 格式导出")

    @routes.post("/promptvault/import")
    async def import_promptvault(request):
        store = PromptVaultStore.get()
        content_type = (request.content_type or "").lower()
        conflict_strategy = "merge"

        if content_type.startswith("multipart/"):
            form = await request.post()
            upload = form.get("file")
            conflict_strategy = str(form.get("conflict_strategy", "merge") or "merge").strip().lower()
            fmt = str(form.get("format", "") or "").strip().lower()
            if not upload or not getattr(upload, "file", None):
                return _bad_request("缺少导入文件")
            raw_bytes = upload.file.read()
            if not fmt:
                filename = str(getattr(upload, "filename", "") or "").lower()
                if filename.endswith(".csv"):
                    fmt = "csv"
                else:
                    fmt = "json"
        else:
            try:
                payload = await request.json()
            except Exception:
                return _bad_request("无法解析导入请求")
            if not isinstance(payload, dict):
                return _bad_request("请求体必须是 JSON 对象")
            fmt = str(payload.get("format", "json") or "json").strip().lower()
            conflict_strategy = str(payload.get("conflict_strategy", "merge") or "merge").strip().lower()
            raw_text = str(payload.get("content", "") or "")
            raw_bytes = raw_text.encode("utf-8")

        if conflict_strategy != "merge":
            return _bad_request("当前仅支持 merge 冲突策略")
        try:
            text = raw_bytes.decode("utf-8-sig")
        except Exception:
            return _bad_request("导入文件必须为 UTF-8 编码")

        try:
            if fmt == "csv":
                result = store.import_csv_text(text, conflict_strategy=conflict_strategy)
            else:
                bundle = json.loads(text or "{}")
                result = store.import_bundle(bundle, conflict_strategy=conflict_strategy)
        except Exception as exc:
            return _json_response({"error": str(exc)}, status=400)
        return _json_response(result)

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

    @routes.get("/promptvault/llm/config")
    async def get_llm_config(_request):
        config, _error = _load_llm_config(require_enabled=False)
        return _json_response(_sanitize_llm_config(config))

    @routes.put("/promptvault/llm/config")
    async def put_llm_config(request):
        from .llm import normalize_config

        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        if not isinstance(payload, dict):
            return _bad_request("请求体必须是 JSON 对象")

        store = PromptVaultStore.get()
        current = store.get_llm_config()
        current.update(payload)
        current = normalize_config(current)
        store.set_llm_config(current)
        return _json_response(_sanitize_llm_config(current))

    @routes.post("/promptvault/llm/auto_tag")
    async def llm_auto_tag(request):
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        positive, negative, existing_tags, _existing_title, error = _validate_llm_payload(payload)
        if error:
            return error

        config, error = _load_llm_config()
        if error:
            return error

        from .llm import LLMClient

        client = LLMClient(config)
        try:
            tags = await client.auto_tag(positive, negative, existing_tags)
        except Exception as exc:
            return _json_response({"error": str(exc), "tags": []})
        return _json_response({"tags": tags})

    @routes.post("/promptvault/llm/auto_title")
    async def llm_auto_title(request):
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        positive, negative, existing_tags, existing_title, error = _validate_llm_payload(payload)
        if error:
            return error

        config, error = _load_llm_config()
        if error:
            return error

        from .llm import LLMClient

        client = LLMClient(config)
        try:
            title = await client.auto_title(positive, negative, existing_title, existing_tags)
        except Exception as exc:
            return _json_response({"error": str(exc), "title": ""})
        return _json_response({"title": title})

    @routes.post("/promptvault/llm/auto_title_tags")
    async def llm_auto_title_tags(request):
        try:
            payload = await request.json()
        except Exception:
            return _bad_request("JSON 解析失败")
        positive, negative, existing_tags, existing_title, error = _validate_llm_payload(payload)
        if error:
            return error

        config, error = _load_llm_config()
        if error:
            return error

        from .llm import LLMClient

        client = LLMClient(config)
        try:
            result = await client.auto_title_and_tags(positive, negative, existing_title, existing_tags)
        except Exception as exc:
            return _json_response({"error": str(exc), "title": "", "tags": []})
        return _json_response({"title": result.get("title", ""), "tags": result.get("tags", [])})

    @routes.post("/promptvault/llm/test")
    async def llm_test(request):
        import logging as _logging

        _log = _logging.getLogger("PromptVault")
        config, _error = _load_llm_config(require_enabled=False)
        _log.info("[llm/test] db config base_url=%s enabled=%s", config.get("base_url"), config.get("enabled"))

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        if isinstance(payload, dict) and payload:
            _log.info("[llm/test] payload keys=%s base_url=%s", list(payload.keys()), payload.get("base_url"))
            config.update(payload)

        _log.info(
            "[llm/test] final base_url=%s model=%s timeout=%s",
            config.get("base_url"),
            config.get("model"),
            config.get("timeout"),
        )

        from .llm import LLMClient

        client = LLMClient(config)
        _log.info("[llm/test] endpoint=%s", client._endpoint)
        try:
            result = await client.test_connection()
        except Exception as exc:
            _log.error("[llm/test] failed: %s", exc)
            return _json_response({"ok": False, "error": str(exc)})
        _log.info("[llm/test] success: %s", result)
        return _json_response(result)

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
        import io

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

        from .image_metadata import extract_exif_xmp, extract_from_info
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
            _extract_from_workflow_obj,
            _extract_generation_data,
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
            for key, value in wf_data.items():
                if value not in (None, "", 0):
                    data[key] = value

        params_text = found.get("parameters")
        if isinstance(params_text, str) and params_text.strip():
            params_data = _parse_parameters_text(params_text)
            for key, value in params_data.items():
                if value not in (None, "", 0):
                    data[key] = value

        return _json_response({"found": list(found.keys()), "data": data})

    @routes.get("/promptvault/model_resolutions")
    async def model_resolutions(_request):
        from ..nodes import MODEL_RESOLUTIONS

        data = {}
        for model, sizes in MODEL_RESOLUTIONS.items():
            data[model] = [f"{w}x{h}" for w, h in sizes]
        return _json_response(data)
