import json
import re
from pathlib import Path

from PIL import Image


JSON_LIKE_KEYS = {
    "workflow",
    "prompt",
    "comfyui",
    "ComfyUI",
    "parameters",
    "metadata",
    "prompt_json",
    "workflow_json",
}


def _extract_first_json_object(text):
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def try_parse_json(value):
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        return value

    if isinstance(value, bytes):
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                value = value.decode(enc)
                break
            except Exception:
                pass
        if isinstance(value, bytes):
            return None

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            pass

        candidate = _extract_first_json_object(s)
        if candidate:
            try:
                return json.loads(candidate)
            except Exception:
                return None

    return None


def extract_from_info(info):
    found = {}
    keyset = {k.lower() for k in JSON_LIKE_KEYS}

    for k, v in (info or {}).items():
        lk = str(k).strip()
        if lk.lower() in keyset:
            parsed = try_parse_json(v)
            found[lk] = parsed if parsed is not None else v

    for k, v in (info or {}).items():
        lk = str(k).strip()
        if lk in found:
            continue
        parsed = try_parse_json(v)
        if parsed is not None:
            if isinstance(parsed, dict):
                if "nodes" in parsed or "workflow" in lk.lower() or "prompt" in lk.lower():
                    found[lk] = parsed
            elif isinstance(parsed, list) and parsed:
                found[lk] = parsed

    return found


def extract_exif_xmp(img):
    found = {}
    try:
        exif = img.getexif()
        if exif:
            for tag_id, v in exif.items():
                parsed = try_parse_json(v)
                if parsed is not None:
                    found[f"EXIF:{tag_id}"] = parsed
    except Exception:
        pass

    try:
        for k, v in (getattr(img, "info", {}) or {}).items():
            key = str(k)
            if "xmp" in key.lower() or "xml" in key.lower():
                parsed = try_parse_json(v)
                found[f"INFO:{k}"] = parsed if parsed is not None else v
    except Exception:
        pass

    return found


def extract_comfyui_metadata(image_path):
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(image_path)

    with Image.open(image_path) as img:
        info = dict(getattr(img, "info", {}) or {})
        result = {
            "file": str(image_path),
            "format": img.format,
            "size": img.size,
            "found": {},
        }

        if (img.format or "").upper() == "PNG":
            result["found"].update(extract_from_info(info))
        else:
            result["found"].update(extract_from_info(info))
            result["found"].update(extract_exif_xmp(img))

        return result


def export_metadata_to_file(image_path, out_path, pretty=False):
    data = extract_comfyui_metadata(image_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2 if pretty else None)
    return data
