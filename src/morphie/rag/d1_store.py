"""D1-backed VectorStore: the same tables and behaviour as LocalVectorStore, in Cloudflare D1.

Used when running on Workers (no local disk). Search is the same brute-force cosine over the workspace's chunks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..d1 import D1
from .vector_store import ChunkInput, DocumentRecord, ScoredChunk, SemanticQuery, VectorStore, score_rows

# D1 allows at most 100 bound parameters per statement; a chunk row binds 8.
_ROWS_PER_INSERT = 12
# ...and rows carrying meaning-based vectors are large, so those go in smaller statements.
_ROWS_PER_INSERT_SEMANTIC = 4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class D1VectorStore(VectorStore):
    def __init__(self, db: D1):
        self.db = db

    @staticmethod
    def _record(row: dict) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"], workspace_id=row["workspace_id"], filename=row["filename"],
            original_filename=row["original_filename"], content_type=row["content_type"],
            size_bytes=int(row["size_bytes"]), chunk_count=int(row.get("n") or 0), created_at=row["created_at"],
            semantic_model=row.get("semantic_model"),
        )

    _SELECT = (
        "SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS n FROM documents d "
    )

    def add_document(
        self, workspace_id: str, document_id: str, filename: str,
        original_filename: str, content_type: str, size_bytes: int,
        content_hash: str | None = None, semantic_model: str | None = None,
    ) -> DocumentRecord:
        ts = _now_iso()
        self.db.execute(
            "INSERT INTO documents (id, workspace_id, filename, original_filename, content_type, "
            "size_bytes, created_at, content_hash, semantic_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (document_id, workspace_id, filename, original_filename, content_type, size_bytes, ts, content_hash, semantic_model),
        )
        return DocumentRecord(
            id=document_id, workspace_id=workspace_id, filename=filename, original_filename=original_filename,
            content_type=content_type, size_bytes=size_bytes, chunk_count=0, created_at=ts, semantic_model=semantic_model,
        )

    def set_semantic_model(self, workspace_id: str, document_id: str, model_id: str) -> None:
        self.db.execute(
            "UPDATE documents SET semantic_model = ? WHERE workspace_id = ? AND id = ?", (model_id, workspace_id, document_id)
        )

    def find_document_by_hash(self, workspace_id: str, content_hash: str) -> DocumentRecord | None:
        rows = self.db.query(
            self._SELECT + "WHERE d.workspace_id = ? AND d.content_hash = ? LIMIT 1", (workspace_id, content_hash)
        )
        return self._record(rows[0]) if rows else None

    def add_chunks(self, workspace_id: str, chunks: list[ChunkInput]) -> None:
        statements = []
        per_insert = _ROWS_PER_INSERT_SEMANTIC if any(c.semantic is not None for c in chunks) else _ROWS_PER_INSERT
        for start in range(0, len(chunks), per_insert):
            batch = chunks[start:start + per_insert]
            params: list = []
            for c in batch:
                params += [
                    workspace_id, c.document_id, c.document_name, c.page_number, c.chunk_index, c.text,
                    json.dumps(c.embedding), json.dumps(c.semantic) if c.semantic is not None else None,
                ]
            statements.append((
                "INSERT INTO chunks (workspace_id, document_id, document_name, page_number, chunk_index, text, embedding, semantic) VALUES "
                + ", ".join(["(?, ?, ?, ?, ?, ?, ?, ?)"] * len(batch)),
                params,
            ))
        self.db.batch(statements)

    def list_documents(self, workspace_id: str) -> list[DocumentRecord]:
        rows = self.db.query(self._SELECT + "WHERE d.workspace_id = ? ORDER BY d.created_at DESC", (workspace_id,))
        return [self._record(r) for r in rows]

    def get_document(self, workspace_id: str, document_id: str) -> DocumentRecord | None:
        rows = self.db.query(self._SELECT + "WHERE d.workspace_id = ? AND d.id = ?", (workspace_id, document_id))
        return self._record(rows[0]) if rows else None

    def delete_document(self, workspace_id: str, document_id: str) -> bool:
        exists = self.get_document(workspace_id, document_id) is not None
        if not exists:
            return False
        self.db.batch([
            ("DELETE FROM chunks WHERE workspace_id = ? AND document_id = ?", (workspace_id, document_id)),
            ("DELETE FROM documents WHERE workspace_id = ? AND id = ?", (workspace_id, document_id)),
        ])
        return True

    def has_documents(self, workspace_id: str) -> bool:
        return bool(self.db.query("SELECT 1 AS x FROM documents WHERE workspace_id = ? LIMIT 1", (workspace_id,)))

    def search(
        self, workspace_id: str, query_vector: list[float], top_k: int = 5,
        document_ids: list[str] | None = None, semantic: SemanticQuery | None = None,
    ) -> list[ScoredChunk]:
        # The meaning-based vectors are large: only read them when this search can use them.
        semantic_col = "c.semantic" if semantic is not None else "NULL AS semantic"
        select = (
            f"SELECT c.document_id, c.document_name, c.page_number, c.chunk_index, c.text, c.embedding, {semantic_col}, "
            "d.semantic_model FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.workspace_id = ?"
        )
        if document_ids:
            placeholders = ",".join("?" * len(document_ids))
            rows = self.db.query(select + f" AND c.document_id IN ({placeholders})", [workspace_id, *document_ids])
        else:
            rows = self.db.query(select, (workspace_id,))
        return score_rows(rows, query_vector, semantic)[:top_k]
