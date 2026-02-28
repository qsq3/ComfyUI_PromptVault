SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  ir_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fragments (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  model_scope_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entries (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  version INTEGER NOT NULL,
  lang TEXT NOT NULL,
  template_id TEXT,
  tags_json TEXT NOT NULL,
  model_scope_json TEXT NOT NULL,
  variables_json TEXT NOT NULL,
  fragments_json TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  negative_json TEXT NOT NULL,
  params_json TEXT NOT NULL DEFAULT '{}',
  thumbnail_png BLOB,
  thumbnail_width INTEGER,
  thumbnail_height INTEGER,
  favorite INTEGER NOT NULL DEFAULT 0,
  score REAL NOT NULL DEFAULT 0.0,
  hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (template_id) REFERENCES templates(id)
);

CREATE TABLE IF NOT EXISTS entry_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (entry_id) REFERENCES entries(id)
);

-- Lightweight tag table (optional; tags are also stored in entries.tags_json)
CREATE TABLE IF NOT EXISTS tags (
  name TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);

-- FTS for fast keyword search; keep it simple for V1.
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
  entry_id UNINDEXED,
  title,
  content,
  tags,
  tokenize = 'unicode61'
);

CREATE INDEX IF NOT EXISTS idx_entries_status_updated ON entries(status, updated_at);
"""
