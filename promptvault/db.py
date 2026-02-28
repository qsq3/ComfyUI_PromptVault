import json
import logging
import os
import sqlite3
import threading
import uuid

logger = logging.getLogger("PromptVault")

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
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            conn.executescript(SCHEMA_SQL)
            self._migrate_db(conn)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version', ?)",
                ("2",),
            )
            conn.commit()
        finally:
            conn.close()

    def _migrate_db(self, conn):
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
        if "params_json" not in cols:
            conn.execute("ALTER TABLE entries ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}'")
        if "thumbnail_png" not in cols:
            conn.execute("ALTER TABLE entries ADD COLUMN thumbnail_png BLOB")
        if "thumbnail_width" not in cols:
            conn.execute("ALTER TABLE entries ADD COLUMN thumbnail_width INTEGER")
        if "thumbnail_height" not in cols:
            conn.execute("ALTER TABLE entries ADD COLUMN thumbnail_height INTEGER")
        if "favorite" not in cols:
            conn.execute("ALTER TABLE entries ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        if "score" not in cols:
            conn.execute("ALTER TABLE entries ADD COLUMN score REAL NOT NULL DEFAULT 0.0")

    def _fts_upsert(self, conn, entry):
        tags = " ".join(entry.get("tags", []))
        content = " ".join(
            [
                entry.get("raw", {}).get("positive", ""),
                entry.get("raw", {}).get("negative", ""),
                json.dumps(entry.get("variables", {}), ensure_ascii=False),
                json.dumps(entry.get("params", {}), ensure_ascii=False),
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

        params = payload.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        thumbnail_png = payload.get("thumbnail_png")
        has_thumbnail = isinstance(thumbnail_png, (bytes, bytearray)) and len(thumbnail_png) > 0
        thumb_w = int(payload.get("thumbnail_width") or 0) or None
        thumb_h = int(payload.get("thumbnail_height") or 0) or None

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
            "params": params,
            "has_thumbnail": has_thumbnail,
            "thumbnail_width": thumb_w,
            "thumbnail_height": thumb_h,
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
                  variables_json,fragments_json,raw_json,negative_json,params_json,
                  thumbnail_png,thumbnail_width,thumbnail_height,hash,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    json_dumps(entry_obj["params"]),
                    sqlite3.Binary(bytes(thumbnail_png)) if has_thumbnail else None,
                    entry_obj["thumbnail_width"],
                    entry_obj["thumbnail_height"],
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

    def get_entry_thumbnail(self, entry_id):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT thumbnail_png, thumbnail_width, thumbnail_height FROM entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
            if not row:
                raise KeyError("entry not found")
            blob = row["thumbnail_png"]
            if blob is None:
                return None
            return {
                "png": bytes(blob),
                "width": row["thumbnail_width"],
                "height": row["thumbnail_height"],
            }
        finally:
            conn.close()

    def update_entry(self, entry_id, payload):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
            if not row:
                raise KeyError("entry not found")
            entry = self._row_to_entry(row)

            current_thumb_blob = row["thumbnail_png"]
            thumb_blob = current_thumb_blob
            thumb_w = row["thumbnail_width"]
            thumb_h = row["thumbnail_height"]

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
            if "params" in payload:
                params = payload.get("params") or {}
                if isinstance(params, dict):
                    entry["params"] = params
            if "status" in payload:
                status = str(payload.get("status") or "").strip() or entry.get("status", "active")
                entry["status"] = status
            if "favorite" in payload:
                entry["favorite"] = 1 if payload.get("favorite") else 0
            if "score" in payload:
                try:
                    entry["score"] = float(payload.get("score", 0.0))
                except (TypeError, ValueError):
                    entry["score"] = 0.0
            if "thumbnail_png" in payload:
                new_thumb = payload.get("thumbnail_png")
                if isinstance(new_thumb, (bytes, bytearray)) and len(new_thumb) > 0:
                    thumb_blob = sqlite3.Binary(bytes(new_thumb))
                    thumb_w = int(payload.get("thumbnail_width") or 0) or None
                    thumb_h = int(payload.get("thumbnail_height") or 0) or None
                else:
                    thumb_blob = None
                    thumb_w = None
                    thumb_h = None

            entry["has_thumbnail"] = thumb_blob is not None
            entry["thumbnail_width"] = thumb_w
            entry["thumbnail_height"] = thumb_h
            entry["version"] = int(entry.get("version", 1)) + 1
            entry["updated_at"] = now_iso()
            entry["hash"] = stable_hash(entry)

            conn.execute(
                """
                UPDATE entries SET
                  title=?,
                  status=?,
                  version=?,
                  tags_json=?,
                  model_scope_json=?,
                  variables_json=?,
                  raw_json=?,
                  negative_json=?,
                  params_json=?,
                  thumbnail_png=?,
                  thumbnail_width=?,
                  thumbnail_height=?,
                  favorite=?,
                  score=?,
                  hash=?,
                  updated_at=?
                WHERE id=?
                """,
                (
                    entry["title"],
                    entry.get("status", "active"),
                    entry["version"],
                    json_dumps(entry["tags"]),
                    json_dumps(entry["model_scope"]),
                    json_dumps(entry["variables"]),
                    json_dumps(entry["raw"]),
                    json_dumps(entry["negative"]),
                    json_dumps(entry.get("params", {})),
                    thumb_blob,
                    thumb_w,
                    thumb_h,
                    entry.get("favorite", 0),
                    entry.get("score", 0.0),
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

    def purge_deleted_entries(self):
        """硬删除所有已软删除的记录及其相关索引/版本。"""
        conn = self._connect()
        try:
            # 先收集所有待删除的 entry_id，便于清理关联表
            rows = conn.execute("SELECT id FROM entries WHERE status = 'deleted'").fetchall()
            ids = [r["id"] for r in rows]
            if not ids:
                return 0

            # 使用参数化的 IN 子句删除 entry_versions 和 entries_fts 中的对应记录
            placeholders = ",".join(["?"] * len(ids))
            conn.execute(f"DELETE FROM entry_versions WHERE entry_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM entries_fts WHERE entry_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM entries WHERE id IN ({placeholders})", ids)
            conn.commit()
            return len(ids)
        finally:
            conn.close()

    def tidy_tags(self):
        """整理标签：
        1）删除在 entries 中已不存在的标签；
        2）补充 entries 中出现但 tags 表中缺失的标签。
        返回 {removed, added} 统计。
        """
        conn = self._connect()
        try:
            entry_rows = conn.execute(
                "SELECT tags_json FROM entries WHERE status != 'deleted'"
            ).fetchall()
            used_tags = set()
            for er in entry_rows:
                try:
                    tlist = json.loads(er["tags_json"] or "[]")
                except Exception:
                    tlist = []
                for t in tlist or []:
                    if t:
                        used_tags.add(str(t))

            rows = conn.execute("SELECT name FROM tags").fetchall()
            all_tag_names = [r["name"] for r in rows]
            removed = 0
            for name in all_tag_names:
                if name not in used_tags:
                    conn.execute("DELETE FROM tags WHERE name = ?", (name,))
                    removed += 1

            existing_rows = conn.execute("SELECT name FROM tags").fetchall()
            existing = {r["name"] for r in existing_rows}
            missing = sorted(used_tags - existing)
            now = now_iso()
            added = 0
            for name in missing:
                conn.execute(
                    "INSERT OR IGNORE INTO tags(name,created_at) VALUES(?,?)",
                    (name, now),
                )
                added += 1

            conn.commit()
            return {"removed": removed, "added": added}
        finally:
            conn.close()

    @staticmethod
    def _escape_fts_query(raw):
        """Wrap each token in double-quotes so FTS5 treats special chars as literals."""
        tokens = raw.split()
        escaped = []
        for t in tokens:
            t = t.replace('"', '""')
            escaped.append(f'"{t}"')
        return " ".join(escaped) if escaped else ""

    def search_entries(self, q="", tags=None, model="", status="active", limit=20, offset=0):
        tags = normalize_tags(tags or [])
        q = normalize_text(q)
        model = normalize_text(model)
        logger.debug("search_entries input: q=%r tags=%s model=%r status=%r limit=%d offset=%d",
                     q, tags, model, status, int(limit), int(offset))

        conn = self._connect()
        try:
            where = ["e.status = ?"]
            params = [status]

            if model:
                where.append("e.model_scope_json LIKE ?")
                params.append(f"%{model}%")

            for t in tags:
                where.append("e.tags_json LIKE ?")
                params.append(f"%{t}%")

            if q:
                fts_q = self._escape_fts_query(q)
                sql = f"""
                SELECT e.id, e.title, e.tags_json, e.model_scope_json, e.updated_at
                FROM entries_fts f
                JOIN entries e ON e.id = f.entry_id
                WHERE ({' AND '.join(where)}) AND entries_fts MATCH ?
                ORDER BY bm25(entries_fts) ASC, e.updated_at DESC
                LIMIT ? OFFSET ?
                """
                try:
                    rows = conn.execute(sql, params + [fts_q, int(limit), int(offset)]).fetchall()
                    logger.debug("FTS rows=%d", len(rows))
                except sqlite3.OperationalError:
                    # FTS query syntax can fail on unescaped special chars.
                    logger.warning("FTS failed, fallback to LIKE")
                    like_where = list(where)
                    like_where.append("(e.title LIKE ? OR e.raw_json LIKE ? OR e.negative_json LIKE ?)")
                    like_q = f"%{q}%"
                    sql_like = f"""
                    SELECT e.id, e.title, e.tags_json, e.model_scope_json, e.updated_at
                    FROM entries e
                    WHERE {' AND '.join(like_where)}
                    ORDER BY e.updated_at DESC
                    LIMIT ? OFFSET ?
                    """
                    rows = conn.execute(
                        sql_like,
                        params + [like_q, like_q, like_q, int(limit), int(offset)],
                    ).fetchall()
                    logger.debug("LIKE rows=%d", len(rows))
            else:
                sql = f"""
                SELECT e.id, e.title, e.tags_json, e.model_scope_json, e.updated_at
                FROM entries e
                WHERE {' AND '.join(where)}
                ORDER BY e.updated_at DESC
                LIMIT ? OFFSET ?
                """
                rows = conn.execute(sql, params + [int(limit), int(offset)]).fetchall()
                logger.debug("no-q rows=%d", len(rows))

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
            logger.debug("return_items=%d", len(items))
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
            "params": json.loads(row["params_json"] or "{}"),
            "has_thumbnail": row["thumbnail_png"] is not None,
            "thumbnail_width": row["thumbnail_width"],
            "thumbnail_height": row["thumbnail_height"],
            "favorite": int(row["favorite"] or 0),
            "score": float(row["score"] or 0.0),
            "hash": row["hash"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
