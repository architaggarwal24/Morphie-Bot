-- Morphie-Bot schema for Cloudflare D1.
-- Apply with:  uv run pywrangler d1 migrations apply morphie-bot --remote   (--local for dev)
--
-- documents / chunks   the RAG index (same tables LocalVectorStore creates in its SQLite file)
-- conversation_messages short-term chat context per browser (kept in memory when running locally)
-- rate_buckets          fixed-window request counters shared by every isolate

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  content_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_id);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(workspace_id, content_hash);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  document_name TEXT NOT NULL,
  page_number INTEGER,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  embedding TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversation_messages(user_id, id);
CREATE INDEX IF NOT EXISTS idx_conv_created ON conversation_messages(created_at);

CREATE TABLE IF NOT EXISTS rate_buckets (
  bucket TEXT NOT NULL,
  window INTEGER NOT NULL,
  n INTEGER NOT NULL,
  PRIMARY KEY (bucket, window)
);
