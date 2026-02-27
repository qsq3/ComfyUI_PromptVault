import json
import os
import sqlite3
import threading
import uuid

from .paths import get_db_path
from .schema import SCHEMA_SQL
from .utils import json_dumps, normalize_tags, normalize_text, now_iso, stable_hash


class PromptVaultStore:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.db_path = get_db_path()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version', ?)",
                ("1",),
            )
            conn.commit()
        finally:
            conn.close()

    def _fts_upsert(self, conn, entry):
        tags = " ".join(entry.get("tags", []))
        content = " ".join(
            [
                entry.get("raw", {}).get("positive", ""),
                entry.get("raw", {}).get("negative", ""),
                json.dumps(entry.get("variables", {}), ensure_ascii=False),
            ]
        )
        conn.execute("DELETE FROM entries_fts WHERE entry_id = ?", (entry["id"],))
        conn.execute(
            "INSERT INTO entries_fts(entry_id,title,content,tags) VALUES(?,?,?,?)",
            (entry["id"], entry.get("title", ""), content, tags),
        )

    def create_entry(self, payload):
        title = normalize_text(payload.get("title", "")) or "未命名"
        tags = normalize_tags(payload.get("tags", []))
        model_scope = normalize_tags(payload.get("model_scope", []))

        raw = payload.get("raw", {}) or {}
        raw_pos = normalize_text(raw.get("positive", ""))
        raw_neg = normalize_text(raw.get("negative", ""))

        entry_id = payload.get("id") or f"entry_{uuid.uuid4().hex}"
        now = now_iso()

        entry_obj = {
            "id": entry_id,
            "title": title,
            "status": "active",
            "version": 1,
            "lang": payload.get("lang") or "zh-CN",
            "template_id": payload.get("template_id"),
            "tags": tags,
            "model_scope": model_scope,
            "variables": payload.get("variables") or {},
            "fragments": payload.get("fragments") or [],
            "raw": {"positive": raw_pos, "negative": raw_neg},
            "negative": payload.get("negative") or {"fragments": [], "raw": raw_neg},
        }
        entry_obj["hash"] = stable_hash(entry_obj)
        entry_obj["created_at"] = now
        entry_obj["updated_at"] = now

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO entries(
                  id,title,status,version,lang,template_id,tags_json,model_scope_json,
                  variables_json,fragments_json,raw_json,negative_json,hash,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    entry_obj["id"],
                    entry_obj["title"],
                    entry_obj["status"],
                    entry_obj["version"],
                    entry_obj["lang"],
                    entry_obj["template_id"],
                    json_dumps(entry_obj["tags"]),
                    json_dumps(entry_obj["model_scope"]),
                    json_dumps(entry_obj["variables"]),
                    json_dumps(entry_obj["fragments"]),
                    json_dumps(entry_obj["raw"]),
                    json_dumps(entry_obj["negative"]),
                    entry_obj["hash"],
                    entry_obj["created_at"],
                    entry_obj["updated_at"],
                ),
            )
            conn.execute(
                "INSERT INTO entry_versions(entry_id,version,snapshot_json,created_at) VALUES(?,?,?,?)",
                (entry_obj["id"], 1, json_dumps(entry_obj), now),
            )
            for t in tags:
                conn.execute("INSERT OR IGNORE INTO tags(name,created_at) VALUES(?,?)", (t, now))
            self._fts_upsert(conn, entry_obj)
            conn.commit()
            return entry_obj
        finally:
            conn.close()

    def upsert_fragment(self, payload):
        frag_id = payload.get("id") or f"frag_{uuid.uuid4().hex}"
        title = normalize_text(payload.get("title", "")) or "未命名片段"
        text = normalize_text(payload.get("text", ""))
        tags = normalize_tags(payload.get("tags", []))
        model_scope = normalize_tags(payload.get("model_scope", []))
        now = now_iso()

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO fragments(id,title,text,tags_json,model_scope_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  text=excluded.text,
                  tags_json=excluded.tags_json,
                  model_scope_json=excluded.model_scope_json,
                  updated_at=excluded.updated_at
                """,
                (frag_id, title, text, json_dumps(tags), json_dumps(model_scope), now, now),
            )
            conn.commit()
            return {
                "id": frag_id,
                "title": title,
                "text": text,
                "tags": tags,
                "model_scope": model_scope,
                "created_at": now,
                "updated_at": now,
            }
        finally:
            conn.close()

    def get_fragment(self, frag_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM fragments WHERE id = ?", (frag_id,)).fetchone()
            if not row:
                raise KeyError("fragment not found")
            return {
                "id": row["id"],
                "title": row["title"],
                "text": row["text"],
                "tags": json.loads(row["tags_json"] or "[]"),
                "model_scope": json.loads(row["model_scope_json"] or "[]"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    def upsert_template(self, payload):
        tpl_id = payload.get("id") or f"tpl_{uuid.uuid4().hex}"
        title = normalize_text(payload.get("title", "")) or "未命名模板"
        ir = payload.get("ir") or payload.get("ir_json") or {}
        if isinstance(ir, str):
            try:
                ir = json.loads(ir)
            except Exception:
                ir = {}
        if not isinstance(ir, dict):
            ir = {}
        now = now_iso()

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO templates(id,title,ir_json,created_at,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  ir_json=excluded.ir_json,
                  updated_at=excluded.updated_at
                """,
                (tpl_id, title, json_dumps(ir), now, now),
            )
            conn.commit()
            return {"id": tpl_id, "title": title, "ir": ir, "created_at": now, "updated_at": now}
        finally:
            conn.close()

    def get_template(self, tpl_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM templates WHERE id = ?", (tpl_id,)).fetchone()
            if not row:
                raise KeyError("template not found")
            return {
                "id": row["id"],
                "title": row["title"],
                "ir": json.loads(row["ir_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    def list_tags(self, limit=200):
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT name, created_at FROM tags ORDER BY name ASC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [{"name": r["name"], "created_at": r["created_at"]} for r in rows]
        finally:
            conn.close()

    def get_entry(self, entry_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
            if not row:
                raise KeyError("entry not found")
            return self._row_to_entry(row)
        finally:
            conn.close()

    def update_entry(self, entry_id, payload):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
            if not row:
                raise KeyError("entry not found")
            entry = self._row_to_entry(row)

            # Only update a conservative subset for V1 UI.
            if "title" in payload:
                entry["title"] = normalize_text(payload.get("title", "")) or entry["title"]
            if "tags" in payload:
                entry["tags"] = normalize_tags(payload.get("tags") or [])
            if "model_scope" in payload:
                entry["model_scope"] = normalize_tags(payload.get("model_scope") or [])
            if "raw" in payload:
                raw = payload.get("raw") or {}
                entry["raw"]["positive"] = normalize_text(raw.get("positive", entry["raw"].get("positive", "")))
                entry["raw"]["negative"] = normalize_text(raw.get("negative", entry["raw"].get("negative", "")))
                entry["negative"]["raw"] = entry["raw"]["negative"]
            if "variables" in payload:
                variables = payload.get("variables") or {}
                if isinstance(variables, dict):
                    entry["variables"] = variables

            entry["version"] = int(entry.get("version", 1)) + 1
            entry["updated_at"] = now_iso()
            entry["hash"] = stable_hash(entry)

            conn.execute(
                """
                UPDATE entries SET
                  title=?,
                  version=?,
                  tags_json=?,
                  model_scope_json=?,
                  variables_json=?,
                  raw_json=?,
                  negative_json=?,
                  hash=?,
                  updated_at=?
                WHERE id=?
                """,
                (
                    entry["title"],
                    entry["version"],
                    json_dumps(entry["tags"]),
                    json_dumps(entry["model_scope"]),
                    json_dumps(entry["variables"]),
                    json_dumps(entry["raw"]),
                    json_dumps(entry["negative"]),
                    entry["hash"],
                    entry["updated_at"],
                    entry["id"],
                ),
            )
            conn.execute(
                "INSERT INTO entry_versions(entry_id,version,snapshot_json,created_at) VALUES(?,?,?,?)",
                (entry["id"], entry["version"], json_dumps(entry), entry["updated_at"]),
            )
            for t in entry["tags"]:
                conn.execute("INSERT OR IGNORE INTO tags(name,created_at) VALUES(?,?)", (t, entry["updated_at"]))
            self._fts_upsert(conn, entry)
            conn.commit()
            return entry
        finally:
            conn.close()

    def delete_entry(self, entry_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
            if not row:
                raise KeyError("entry not found")
            entry = self._row_to_entry(row)
            entry["status"] = "deleted"
            entry["version"] = int(entry.get("version", 1)) + 1
            entry["updated_at"] = now_iso()
            entry["hash"] = stable_hash(entry)

            conn.execute(
                "UPDATE entries SET status=?, version=?, hash=?, updated_at=? WHERE id=?",
                (entry["status"], entry["version"], entry["hash"], entry["updated_at"], entry_id),
            )
            conn.execute(
                "INSERT INTO entry_versions(entry_id,version,snapshot_json,created_at) VALUES(?,?,?,?)",
                (entry["id"], entry["version"], json_dumps(entry), entry["updated_at"]),
            )
            self._fts_upsert(conn, entry)
            conn.commit()
            return entry
        finally:
            conn.close()

    def search_entries(self, q="", tags=None, model="", status="active", limit=20, offset=0):
        tags = normalize_tags(tags or [])
        q = normalize_text(q)
        model = normalize_text(model)

        conn = self._connect()
        try:
            where = ["e.status = ?"]
            params = [status]

            if model:
                # model_scope_json is JSON array; V1 uses LIKE as a pragmatic filter.
                where.append("e.model_scope_json LIKE ?")
                params.append(f"%{model}%")

            for t in tags:
                where.append("e.tags_json LIKE ?")
                params.append(f"%{t}%")

            if q:
                sql = f"""
                SELECT e.id, e.title, e.tags_json, e.model_scope_json, e.updated_at
                FROM entries_fts f
                JOIN entries e ON e.id = f.entry_id
                WHERE ({' AND '.join(where)}) AND entries_fts MATCH ?
                ORDER BY bm25(entries_fts) ASC, e.updated_at DESC
                LIMIT ? OFFSET ?
                """
                params2 = params + [q, int(limit), int(offset)]
                rows = conn.execute(sql, params2).fetchall()
            else:
                sql = f"""
                SELECT e.id, e.title, e.tags_json, e.model_scope_json, e.updated_at
                FROM entries e
                WHERE {' AND '.join(where)}
                ORDER BY e.updated_at DESC
                LIMIT ? OFFSET ?
                """
                rows = conn.execute(sql, params + [int(limit), int(offset)]).fetchall()

            items = []
            for r in rows:
                items.append(
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "tags": json.loads(r["tags_json"] or "[]"),
                        "model_scope": json.loads(r["model_scope_json"] or "[]"),
                        "updated_at": r["updated_at"],
                    }
                )
            return items
        finally:
            conn.close()

    def list_entry_versions(self, entry_id, limit=50):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT version, created_at
                FROM entry_versions
                WHERE entry_id = ?
                ORDER BY version DESC
                LIMIT ?
                """,
                (entry_id, int(limit)),
            ).fetchall()
            return [{"version": r["version"], "created_at": r["created_at"]} for r in rows]
        finally:
            conn.close()

    def _row_to_entry(self, row):
        return {
            "id": row["id"],
            "title": row["title"],
            "status": row["status"],
            "version": int(row["version"]),
            "lang": row["lang"],
            "template_id": row["template_id"],
            "tags": json.loads(row["tags_json"] or "[]"),
            "model_scope": json.loads(row["model_scope_json"] or "[]"),
            "variables": json.loads(row["variables_json"] or "{}"),
            "fragments": json.loads(row["fragments_json"] or "[]"),
            "raw": json.loads(row["raw_json"] or "{}"),
            "negative": json.loads(row["negative_json"] or "{}"),
            "hash": row["hash"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
