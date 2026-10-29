-- Morphie-Bot v2.
-- Apply with:  uv run pywrangler d1 migrations apply morphie-bot --remote   (--local for dev)
--
-- conversation_messages.turn_id / meta   a question and its answer share a turn id (Stop, Regenerate, Edit);
--                                         meta holds what the page shows next to an answer (sources, tools)
-- cancelled_turns                         tombstones: a stopped turn that is still finishing is never saved
-- documents.semantic_model / chunks.semantic
--                                         optional meaning-based embeddings next to the keyword ones

ALTER TABLE conversation_messages ADD COLUMN turn_id TEXT;
ALTER TABLE conversation_messages ADD COLUMN meta TEXT;
CREATE INDEX IF NOT EXISTS idx_conv_turn ON conversation_messages(user_id, turn_id);

CREATE TABLE IF NOT EXISTS cancelled_turns (
  user_id TEXT NOT NULL,
  turn_id TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, turn_id)
);

ALTER TABLE documents ADD COLUMN semantic_model TEXT;
ALTER TABLE chunks ADD COLUMN semantic TEXT;
