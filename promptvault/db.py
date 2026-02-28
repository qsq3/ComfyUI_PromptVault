import base64
import csv
import io
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

    def search_entries(
        self,
        q="",
        tags=None,
        model="",
        status="active",
        limit=20,
        offset=0,
        sort="updated_desc",
        favorite_only=False,
        has_thumbnail=False,
    ):
        tags = normalize_tags(tags or [])
        q = normalize_text(q)
        model = normalize_text(model)
        sort = normalize_text(sort or "updated_desc") or "updated_desc"
        logger.debug(
            "search_entries input: q=%r tags=%s model=%r status=%r limit=%d offset=%d sort=%r favorite_only=%r has_thumbnail=%r",
            q,
            tags,
            model,
            status,
            int(limit),
            int(offset),
            sort,
            bool(favorite_only),
            bool(has_thumbnail),
        )

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

            if favorite_only:
                where.append("e.favorite = 1")

            if has_thumbnail:
                where.append("e.thumbnail_png IS NOT NULL")

            select_fields = (
                "e.id, e.title, e.tags_json, e.model_scope_json, e.updated_at, "
                "e.raw_json, e.favorite, e.score, e.thumbnail_png IS NOT NULL AS has_thumbnail"
            )
            order_by = self._search_order_by(sort=sort, with_fts=bool(q))

            if q:
                rows = self._search_rows_with_keyword(
                    conn=conn,
                    q=q,
                    where=where,
                    params=params,
                    select_fields=select_fields,
                    sort=sort,
                    limit=limit,
                    offset=offset,
                )
            else:
                sql = f"""
                SELECT {select_fields}
                FROM entries e
                WHERE {' AND '.join(where)}
                ORDER BY {self._search_order_by(sort=sort, with_fts=False)}
                LIMIT ? OFFSET ?
                """
                rows = conn.execute(sql, params + [int(limit), int(offset)]).fetchall()
                logger.debug("no-q rows=%d", len(rows))

            items = []
            for r in rows:
                tags_list = json.loads(r["tags_json"] or "[]")
                model_scope_list = json.loads(r["model_scope_json"] or "[]")
                positive_preview = self._positive_preview_from_raw_json(r["raw_json"])
                items.append(
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "tags": tags_list,
                        "model_scope": model_scope_list,
                        "favorite": int(r["favorite"] or 0),
                        "score": float(r["score"] or 0.0),
                        "has_thumbnail": bool(r["has_thumbnail"]),
                        "positive_preview": positive_preview,
                        "match_reasons": self._build_match_reasons(
                            q=q,
                            tags=tags_list,
                            title=r["title"],
                            positive_preview=positive_preview,
                        ),
                        "updated_at": r["updated_at"],
                    }
                )
            logger.debug("return_items=%d", len(items))
            return items
        finally:
            conn.close()

    def count_entries(self, q="", tags=None, model="", status="active", favorite_only=False, has_thumbnail=False):
        tags = normalize_tags(tags or [])
        q = normalize_text(q)
        model = normalize_text(model)

        conn = self._connect()
        try:
            where = ["e.status = ?"]
            params = [status]

            if model:
                where.append("e.model_scope_json LIKE ?")
                params.append(f"%{model}%")

            for tag in tags:
                where.append("e.tags_json LIKE ?")
                params.append(f"%{tag}%")

            if favorite_only:
                where.append("e.favorite = 1")

            if has_thumbnail:
                where.append("e.thumbnail_png IS NOT NULL")

            if q:
                return self._count_rows_with_keyword(conn=conn, q=q, where=where, params=params)

            sql = f"""
            SELECT COUNT(*) AS total
            FROM entries e
            WHERE {' AND '.join(where)}
            """
            row = conn.execute(sql, params).fetchone()
            return int((row or {})["total"] if row else 0)
        finally:
            conn.close()

    @staticmethod
    def _search_order_by(sort="updated_desc", with_fts=False):
        if sort == "score_desc":
            return "e.score DESC, e.updated_at DESC"
        if sort == "favorite_desc":
            return "e.favorite DESC, e.score DESC, e.updated_at DESC"
        if with_fts:
            return "bm25(entries_fts) ASC, e.updated_at DESC"
        return "e.updated_at DESC"

    @staticmethod
    def _positive_preview_from_raw_json(raw_json, limit=96):
        try:
            raw = json.loads(raw_json or "{}")
        except Exception:
            raw = {}
        positive = normalize_text((raw or {}).get("positive", ""))
        if len(positive) <= limit:
            return positive
        return positive[: limit - 1].rstrip() + "…"

    @staticmethod
    def _build_match_reasons(q="", tags=None, title="", positive_preview=""):
        reasons = []
        query = normalize_text(q).lower()
        title_l = normalize_text(title).lower()
        preview_l = normalize_text(positive_preview).lower()
        tags_l = [normalize_text(tag).lower() for tag in (tags or []) if normalize_text(tag)]
        if query:
            if query in title_l:
                reasons.append("命中标题")
            if any(query in tag for tag in tags_l):
                reasons.append("命中标签")
            if query in preview_l:
                reasons.append("命中内容")
        if not reasons and tags_l:
            reasons.append("提示词")
        return reasons

    @staticmethod
    def _should_prefer_like(q):
        compact = "".join((q or "").split())
        if not compact:
            return False
        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in compact)
        return has_cjk and len(compact) <= 2

    def _search_rows_with_keyword(self, conn, q, where, params, select_fields, sort, limit, offset):
        if self._should_prefer_like(q):
            rows = self._search_rows_like(conn, q, where, params, select_fields, sort, limit, offset)
            logger.debug("LIKE rows=%d (preferred)", len(rows))
            return rows

        fts_q = self._escape_fts_query(q)
        sql = f"""
        SELECT {select_fields}
        FROM entries_fts f
        JOIN entries e ON e.id = f.entry_id
        WHERE ({' AND '.join(where)}) AND entries_fts MATCH ?
        ORDER BY {self._search_order_by(sort=sort, with_fts=True)}
        LIMIT ? OFFSET ?
        """
        try:
            rows = conn.execute(sql, params + [fts_q, int(limit), int(offset)]).fetchall()
            logger.debug("FTS rows=%d", len(rows))
        except sqlite3.OperationalError:
            logger.warning("FTS failed, fallback to LIKE")
            rows = self._search_rows_like(conn, q, where, params, select_fields, sort, limit, offset)
            logger.debug("LIKE rows=%d (fts failed)", len(rows))
            return rows

        if not rows:
            rows = self._search_rows_like(conn, q, where, params, select_fields, sort, limit, offset)
            logger.debug("LIKE rows=%d (fts empty)", len(rows))
        return rows

    def _search_rows_like(self, conn, q, where, params, select_fields, sort, limit, offset):
        like_where = list(where)
        like_where.append("(e.title LIKE ? OR e.raw_json LIKE ? OR e.negative_json LIKE ?)")
        like_q = f"%{q}%"
        sql_like = f"""
        SELECT {select_fields}
        FROM entries e
        WHERE {' AND '.join(like_where)}
        ORDER BY {self._search_order_by(sort=sort, with_fts=False)}
        LIMIT ? OFFSET ?
        """
        return conn.execute(
            sql_like,
            params + [like_q, like_q, like_q, int(limit), int(offset)],
        ).fetchall()

    def _count_rows_with_keyword(self, conn, q, where, params):
        if self._should_prefer_like(q):
            return self._count_rows_like(conn, q, where, params)

        fts_q = self._escape_fts_query(q)
        sql = f"""
        SELECT COUNT(*) AS total
        FROM entries_fts f
        JOIN entries e ON e.id = f.entry_id
        WHERE ({' AND '.join(where)}) AND entries_fts MATCH ?
        """
        try:
            row = conn.execute(sql, params + [fts_q]).fetchone()
            total = int((row or {})["total"] if row else 0)
        except sqlite3.OperationalError:
            return self._count_rows_like(conn, q, where, params)

        if total == 0:
            return self._count_rows_like(conn, q, where, params)
        return total

    @staticmethod
    def _count_rows_like(conn, q, where, params):
        like_where = list(where)
        like_where.append("(e.title LIKE ? OR e.raw_json LIKE ? OR e.negative_json LIKE ?)")
        like_q = f"%{q}%"
        sql_like = f"""
        SELECT COUNT(*) AS total
        FROM entries e
        WHERE {' AND '.join(like_where)}
        """
        row = conn.execute(sql_like, params + [like_q, like_q, like_q]).fetchone()
        return int((row or {})["total"] if row else 0)

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

    def export_bundle(self):
        conn = self._connect()
        try:
            template_rows = conn.execute("SELECT * FROM templates ORDER BY updated_at DESC, id ASC").fetchall()
            fragment_rows = conn.execute("SELECT * FROM fragments ORDER BY updated_at DESC, id ASC").fetchall()
            entry_rows = conn.execute("SELECT * FROM entries ORDER BY updated_at DESC, id ASC").fetchall()
            return {
                "version": "1.0",
                "exported_at": now_iso(),
                "templates": [self._row_to_template(row) for row in template_rows],
                "fragments": [self._row_to_fragment(row) for row in fragment_rows],
                "entries": [self._row_to_entry(row, include_thumbnail=True) for row in entry_rows],
            }
        finally:
            conn.close()

    def export_bundle_csv(self):
        bundle = self.export_bundle()
        fields = [
            "record_type",
            "id",
            "title",
            "text",
            "ir_json",
            "status",
            "version",
            "lang",
            "template_id",
            "tags_json",
            "model_scope_json",
            "variables_json",
            "fragments_json",
            "raw_json",
            "negative_json",
            "params_json",
            "favorite",
            "score",
            "hash",
            "thumbnail_b64",
            "thumbnail_width",
            "thumbnail_height",
            "created_at",
            "updated_at",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for template in bundle["templates"]:
            writer.writerow(
                {
                    "record_type": "template",
                    "id": template["id"],
                    "title": template["title"],
                    "ir_json": json_dumps(template.get("ir") or {}),
                    "created_at": template.get("created_at", ""),
                    "updated_at": template.get("updated_at", ""),
                }
            )
        for fragment in bundle["fragments"]:
            writer.writerow(
                {
                    "record_type": "fragment",
                    "id": fragment["id"],
                    "title": fragment["title"],
                    "text": fragment.get("text", ""),
                    "tags_json": json_dumps(fragment.get("tags") or []),
                    "model_scope_json": json_dumps(fragment.get("model_scope") or []),
                    "created_at": fragment.get("created_at", ""),
                    "updated_at": fragment.get("updated_at", ""),
                }
            )
        for entry in bundle["entries"]:
            writer.writerow(
                {
                    "record_type": "entry",
                    "id": entry["id"],
                    "title": entry["title"],
                    "status": entry.get("status", "active"),
                    "version": entry.get("version", 1),
                    "lang": entry.get("lang", "zh-CN"),
                    "template_id": entry.get("template_id") or "",
                    "tags_json": json_dumps(entry.get("tags") or []),
                    "model_scope_json": json_dumps(entry.get("model_scope") or []),
                    "variables_json": json_dumps(entry.get("variables") or {}),
                    "fragments_json": json_dumps(entry.get("fragments") or []),
                    "raw_json": json_dumps(entry.get("raw") or {}),
                    "negative_json": json_dumps(entry.get("negative") or {}),
                    "params_json": json_dumps(entry.get("params") or {}),
                    "favorite": entry.get("favorite", 0),
                    "score": entry.get("score", 0.0),
                    "hash": entry.get("hash", ""),
                    "thumbnail_b64": entry.get("thumbnail_b64", ""),
                    "thumbnail_width": entry.get("thumbnail_width") or "",
                    "thumbnail_height": entry.get("thumbnail_height") or "",
                    "created_at": entry.get("created_at", ""),
                    "updated_at": entry.get("updated_at", ""),
                }
            )
        return buf.getvalue()

    def import_bundle(self, bundle, conflict_strategy="merge"):
        if conflict_strategy != "merge":
            raise ValueError("Only merge conflict strategy is supported")
        if not isinstance(bundle, dict):
            raise ValueError("Import bundle must be a JSON object")

        templates = bundle.get("templates") or []
        fragments = bundle.get("fragments") or []
        entries = bundle.get("entries") or []

        result = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "details": [],
        }

        conn = self._connect()
        try:
            for record_type, records in (("template", templates), ("fragment", fragments), ("entry", entries)):
                for payload in records:
                    try:
                        action = self._import_record(conn, record_type, payload or {})
                        result[action] += 1
                        result["details"].append(
                            {
                                "record_type": record_type,
                                "id": str((payload or {}).get("id") or ""),
                                "action": action,
                            }
                        )
                    except Exception as exc:
                        record_id = str((payload or {}).get("id") or "")
                        result["errors"].append(
                            {
                                "record_type": record_type,
                                "id": record_id,
                                "error": str(exc),
                            }
                        )
            conn.commit()
            return result
        finally:
            conn.close()

    def import_csv_text(self, csv_text, conflict_strategy="merge"):
        reader = csv.DictReader(io.StringIO(csv_text or ""))
        bundle = {"templates": [], "fragments": [], "entries": []}
        for row in reader:
            record_type = (row.get("record_type") or "").strip().lower()
            if record_type == "template":
                bundle["templates"].append(self._csv_row_to_template(row))
            elif record_type == "fragment":
                bundle["fragments"].append(self._csv_row_to_fragment(row))
            elif record_type == "entry":
                bundle["entries"].append(self._csv_row_to_entry(row))
        return self.import_bundle(bundle, conflict_strategy=conflict_strategy)

    # ── LLM config helpers ──

    def get_llm_config(self) -> dict:
        from .llm import DEFAULT_LLM_CONFIG

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'llm_config'"
            ).fetchone()
            if row:
                try:
                    stored = json.loads(row["value"])
                    return {**DEFAULT_LLM_CONFIG, **stored}
                except (json.JSONDecodeError, TypeError):
                    pass
            return dict(DEFAULT_LLM_CONFIG)
        finally:
            conn.close()

    def set_llm_config(self, config: dict):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('llm_config', ?)",
                (json.dumps(config, ensure_ascii=False),),
            )
            conn.commit()
        finally:
            conn.close()

    def _row_to_entry(self, row, include_thumbnail=False):
        thumbnail_b64 = ""
        if include_thumbnail and row["thumbnail_png"] is not None:
            thumbnail_b64 = base64.b64encode(bytes(row["thumbnail_png"])).decode("ascii")
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
            "thumbnail_b64": thumbnail_b64,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_fragment(self, row):
        return {
            "id": row["id"],
            "title": row["title"],
            "text": row["text"],
            "tags": json.loads(row["tags_json"] or "[]"),
            "model_scope": json.loads(row["model_scope_json"] or "[]"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_template(self, row):
        return {
            "id": row["id"],
            "title": row["title"],
            "ir": json.loads(row["ir_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _import_record(self, conn, record_type, payload):
        if record_type == "template":
            return self._merge_template(conn, payload)
        if record_type == "fragment":
            return self._merge_fragment(conn, payload)
        if record_type == "entry":
            return self._merge_entry(conn, payload)
        raise ValueError(f"Unsupported record type: {record_type}")

    def _merge_template(self, conn, payload):
        tpl_id = normalize_text(payload.get("id", ""))
        if not tpl_id:
            raise ValueError("template id is required")
        title = normalize_text(payload.get("title", "")) or "未命名模板"
        ir = payload.get("ir") or payload.get("ir_json") or {}
        if isinstance(ir, str):
            ir = self._loads_json_object(ir, default={})
        created_at = normalize_text(payload.get("created_at", "")) or now_iso()
        updated_at = normalize_text(payload.get("updated_at", "")) or now_iso()
        row = conn.execute("SELECT created_at FROM templates WHERE id = ?", (tpl_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE templates SET title=?, ir_json=?, updated_at=? WHERE id=?",
                (title, json_dumps(ir), updated_at, tpl_id),
            )
            return "updated"
        conn.execute(
            "INSERT INTO templates(id,title,ir_json,created_at,updated_at) VALUES(?,?,?,?,?)",
            (tpl_id, title, json_dumps(ir), created_at, updated_at),
        )
        return "created"

    def _merge_fragment(self, conn, payload):
        frag_id = normalize_text(payload.get("id", ""))
        if not frag_id:
            raise ValueError("fragment id is required")
        title = normalize_text(payload.get("title", "")) or "未命名片段"
        text = normalize_text(payload.get("text", ""))
        tags = normalize_tags(payload.get("tags") or self._loads_json_list(payload.get("tags_json"), default=[]))
        model_scope = normalize_tags(
            payload.get("model_scope") or self._loads_json_list(payload.get("model_scope_json"), default=[])
        )
        created_at = normalize_text(payload.get("created_at", "")) or now_iso()
        updated_at = normalize_text(payload.get("updated_at", "")) or now_iso()
        row = conn.execute("SELECT created_at FROM fragments WHERE id = ?", (frag_id,)).fetchone()
        if row:
            conn.execute(
                """
                UPDATE fragments
                SET title=?, text=?, tags_json=?, model_scope_json=?, updated_at=?
                WHERE id=?
                """,
                (title, text, json_dumps(tags), json_dumps(model_scope), updated_at, frag_id),
            )
            return "updated"
        conn.execute(
            """
            INSERT INTO fragments(id,title,text,tags_json,model_scope_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (frag_id, title, text, json_dumps(tags), json_dumps(model_scope), created_at, updated_at),
        )
        return "created"

    def _merge_entry(self, conn, payload):
        entry_id = normalize_text(payload.get("id", ""))
        if not entry_id:
            raise ValueError("entry id is required")
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row:
            return self._merge_existing_entry(conn, self._row_to_entry(row), payload, row["thumbnail_png"])
        return self._create_imported_entry(conn, payload)

    def _create_imported_entry(self, conn, payload):
        entry = self._normalized_import_entry(payload, existing_created_at=None, base_version=0)
        thumbnail_blob = self._thumbnail_blob_from_payload(entry)
        conn.execute(
            """
            INSERT INTO entries(
              id,title,status,version,lang,template_id,tags_json,model_scope_json,
              variables_json,fragments_json,raw_json,negative_json,params_json,
              thumbnail_png,thumbnail_width,thumbnail_height,favorite,score,hash,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry["id"],
                entry["title"],
                entry["status"],
                entry["version"],
                entry["lang"],
                entry["template_id"],
                json_dumps(entry["tags"]),
                json_dumps(entry["model_scope"]),
                json_dumps(entry["variables"]),
                json_dumps(entry["fragments"]),
                json_dumps(entry["raw"]),
                json_dumps(entry["negative"]),
                json_dumps(entry["params"]),
                thumbnail_blob,
                entry["thumbnail_width"],
                entry["thumbnail_height"],
                entry["favorite"],
                entry["score"],
                entry["hash"],
                entry["created_at"],
                entry["updated_at"],
            ),
        )
        conn.execute(
            "INSERT INTO entry_versions(entry_id,version,snapshot_json,created_at) VALUES(?,?,?,?)",
            (entry["id"], entry["version"], json_dumps(entry), entry["updated_at"]),
        )
        for tag in entry["tags"]:
            conn.execute("INSERT OR IGNORE INTO tags(name,created_at) VALUES(?,?)", (tag, entry["updated_at"]))
        self._fts_upsert(conn, entry)
        return "created"

    def _merge_existing_entry(self, conn, existing_entry, payload, existing_thumbnail_blob):
        entry = self._normalized_import_entry(
            payload,
            existing_created_at=existing_entry.get("created_at"),
            base_version=int(existing_entry.get("version", 1)),
        )
        thumbnail_blob = self._thumbnail_blob_from_payload(entry, existing_thumbnail_blob)
        conn.execute(
            """
            UPDATE entries SET
              title=?, status=?, version=?, lang=?, template_id=?, tags_json=?, model_scope_json=?,
              variables_json=?, fragments_json=?, raw_json=?, negative_json=?, params_json=?,
              thumbnail_png=?, thumbnail_width=?, thumbnail_height=?, favorite=?, score=?, hash=?, updated_at=?
            WHERE id=?
            """,
            (
                entry["title"],
                entry["status"],
                entry["version"],
                entry["lang"],
                entry["template_id"],
                json_dumps(entry["tags"]),
                json_dumps(entry["model_scope"]),
                json_dumps(entry["variables"]),
                json_dumps(entry["fragments"]),
                json_dumps(entry["raw"]),
                json_dumps(entry["negative"]),
                json_dumps(entry["params"]),
                thumbnail_blob,
                entry["thumbnail_width"],
                entry["thumbnail_height"],
                entry["favorite"],
                entry["score"],
                entry["hash"],
                entry["updated_at"],
                entry["id"],
            ),
        )
        conn.execute(
            "INSERT INTO entry_versions(entry_id,version,snapshot_json,created_at) VALUES(?,?,?,?)",
            (entry["id"], entry["version"], json_dumps(entry), entry["updated_at"]),
        )
        for tag in entry["tags"]:
            conn.execute("INSERT OR IGNORE INTO tags(name,created_at) VALUES(?,?)", (tag, entry["updated_at"]))
        self._fts_upsert(conn, entry)
        return "updated"

    def _normalized_import_entry(self, payload, existing_created_at=None, base_version=0):
        raw = payload.get("raw") or self._loads_json_object(payload.get("raw_json"), default={})
        variables = payload.get("variables") or self._loads_json_object(payload.get("variables_json"), default={})
        fragments = payload.get("fragments") or self._loads_json_list(payload.get("fragments_json"), default=[])
        negative = payload.get("negative") or self._loads_json_object(payload.get("negative_json"), default={})
        params = payload.get("params") or self._loads_json_object(payload.get("params_json"), default={})
        tags = normalize_tags(payload.get("tags") or self._loads_json_list(payload.get("tags_json"), default=[]))
        model_scope = normalize_tags(
            payload.get("model_scope") or self._loads_json_list(payload.get("model_scope_json"), default=[])
        )
        positive = normalize_text((raw or {}).get("positive", ""))
        negative_raw = normalize_text((raw or {}).get("negative", ""))
        negative_obj = negative if isinstance(negative, dict) else {}
        negative_obj["raw"] = normalize_text(negative_obj.get("raw", negative_raw) or negative_raw)
        version = int(base_version or 0) + 1
        created_at = existing_created_at or normalize_text(payload.get("created_at", "")) or now_iso()
        updated_at = normalize_text(payload.get("updated_at", "")) or now_iso()
        entry = {
            "id": normalize_text(payload.get("id", "")),
            "title": normalize_text(payload.get("title", "")) or "未命名",
            "status": normalize_text(payload.get("status", "")) or "active",
            "version": version,
            "lang": normalize_text(payload.get("lang", "")) or "zh-CN",
            "template_id": normalize_text(payload.get("template_id", "")) or None,
            "tags": tags,
            "model_scope": model_scope,
            "variables": variables if isinstance(variables, dict) else {},
            "fragments": fragments if isinstance(fragments, list) else [],
            "raw": {"positive": positive, "negative": negative_raw},
            "negative": negative_obj,
            "params": params if isinstance(params, dict) else {},
            "favorite": self._to_int(payload.get("favorite"), default=0),
            "score": self._to_float(payload.get("score"), default=0.0),
            "thumbnail_b64": normalize_text(payload.get("thumbnail_b64", "")),
            "thumbnail_width": self._to_optional_int(payload.get("thumbnail_width")),
            "thumbnail_height": self._to_optional_int(payload.get("thumbnail_height")),
            "created_at": created_at,
            "updated_at": updated_at,
        }
        entry["has_thumbnail"] = bool(entry["thumbnail_b64"])
        entry["hash"] = stable_hash({k: v for k, v in entry.items() if k != "thumbnail_b64"})
        return entry

    def _thumbnail_blob_from_payload(self, entry, existing_blob=None):
        thumb_b64 = entry.get("thumbnail_b64", "")
        if not thumb_b64:
            return existing_blob
        try:
            return sqlite3.Binary(base64.b64decode(thumb_b64))
        except Exception as exc:
            raise ValueError(f"invalid thumbnail_b64: {exc}") from exc

    @staticmethod
    def _loads_json_object(raw, default=None):
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {} if default is None else default
        try:
            data = json.loads(raw)
        except Exception:
            return {} if default is None else default
        return data if isinstance(data, dict) else ({} if default is None else default)

    @staticmethod
    def _loads_json_list(raw, default=None):
        if isinstance(raw, list):
            return raw
        if not raw:
            return [] if default is None else default
        try:
            data = json.loads(raw)
        except Exception:
            return [] if default is None else default
        return data if isinstance(data, list) else ([] if default is None else default)

    @staticmethod
    def _to_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _to_optional_int(cls, value):
        if value in (None, ""):
            return None
        return cls._to_int(value, default=None)

    def _csv_row_to_template(self, row):
        return {
            "id": row.get("id", ""),
            "title": row.get("title", ""),
            "ir_json": row.get("ir_json", ""),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
        }

    def _csv_row_to_fragment(self, row):
        return {
            "id": row.get("id", ""),
            "title": row.get("title", ""),
            "text": row.get("text", ""),
            "tags_json": row.get("tags_json", ""),
            "model_scope_json": row.get("model_scope_json", ""),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
        }

    def _csv_row_to_entry(self, row):
        return {
            "id": row.get("id", ""),
            "title": row.get("title", ""),
            "status": row.get("status", ""),
            "lang": row.get("lang", ""),
            "template_id": row.get("template_id", ""),
            "tags_json": row.get("tags_json", ""),
            "model_scope_json": row.get("model_scope_json", ""),
            "variables_json": row.get("variables_json", ""),
            "fragments_json": row.get("fragments_json", ""),
            "raw_json": row.get("raw_json", ""),
            "negative_json": row.get("negative_json", ""),
            "params_json": row.get("params_json", ""),
            "favorite": row.get("favorite", ""),
            "score": row.get("score", ""),
            "thumbnail_b64": row.get("thumbnail_b64", ""),
            "thumbnail_width": row.get("thumbnail_width", ""),
            "thumbnail_height": row.get("thumbnail_height", ""),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
        }
