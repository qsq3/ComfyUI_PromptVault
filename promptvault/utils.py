import hashlib
import json
import re
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_ws_re = re.compile(r"\s+")


def normalize_text(s):
    if s is None:
        return ""
    s = str(s).strip()
    s = _ws_re.sub(" ", s)
    return s


def normalize_tags(tags):
    out = []
    seen = set()
    for t in tags or []:
        t = normalize_text(t)
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def json_dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def stable_hash(payload_obj):
    # Stable content hash for de-dup / cache.
    raw = json_dumps(payload_obj).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

