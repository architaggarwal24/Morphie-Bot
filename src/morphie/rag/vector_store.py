"""
Vector store layer.

VectorStore is the interface the rest of RAG depends on - nothing
outside this file talks to SQLite (or a real vector database) directly.

  VectorStore
  `-- LocalVectorStore   default. SQLite-backed, brute-force cosine
                         similarity in Python. For the corpus sizes a
                         single-user/small-team app like this handles
                         (tens to low thousands of chunks), that's
                         genuinely fast enough, and it keeps the
                         dependency footprint at zero - no FAISS/Chroma
                         binary wheels to install, no separate service to
                         run. A hosted store (Qdrant, Pinecone, Weaviate)
                         or FAISS/Chroma slots in later as another
                         VectorStore implementation without the
                         retriever, pipeline, or routes changing at all.

A single, persistent SQLite connection is kept open per store (guarded by
a lock), both for normal long-running-process correctness and so
":memory:" databases work in tests.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def hybrid_score(lexical: float, semantic: float | None, semantic_floor: float) -> float:
    """One ranking score from the keyword similarity and (when the document has them) meaning-based embeddings.
    Semantic cosines live on a model-specific scale, so they are rescaled from "unrelated" (the model's floor) to
    1 first; meaning then counts for 70%, shared words for 30%."""
    if semantic is None:
        return lexical
    rescaled = max(0.0, min(1.0, (semantic - semantic_floor) / max(1e-6, 1.0 - semantic_floor)))
    return 0.7 * rescaled + 0.3 * lexical


@dataclass
class SemanticQuery:
    """A query embedded with one model; only chunks embedded with the same model are compared with it."""
    model_id: str
    vector: list[float]
    floor: float


@dataclass
class DocumentRecord:
    id: str
    workspace_id: str
    filename: str            # safe, generated on-disk filename
    original_filename: str   # user-supplied display name (sanitized, but human-readable)
    content_type: str        # extension: pdf / txt / docx / csv / json
    size_bytes: int
    chunk_count: int
    created_at: str
    semantic_model: str | None = None  # "<provider>:<model>" when meaning-based search is available

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.original_filename,
            "type": self.content_type,
            "size_bytes": self.size_bytes,
            "chunk_count": self.chunk_count,
            "created_at": self.created_at,
            "search": "semantic" if self.semantic_model else "keyword",
        }


@dataclass
class ChunkInput:
    document_id: str
    document_name: str
    page_number: int | None
    chunk_index: int
    text: str
    embedding: list[float]
    semantic: list[float] | None = None


@dataclass
class ScoredChunk:
    document_id: str
    document_name: str
    page_number: int | None
    chunk_index: int
    text: str
    score: float
    lexical: float = 0.0
    semantic: float | None = None


class VectorStore(ABC):
    @abstractmethod
    def add_document(
        self, workspace_id: str, document_id: str, filename: str,
        original_filename: str, content_type: str, size_bytes: int,
        content_hash: str | None = None, semantic_model: str | None = None,
    ) -> DocumentRecord: ...

    def set_semantic_model(self, workspace_id: str, document_id: str, model_id: str) -> None:
        """Record that a document's chunks carry meaning-based vectors from `model_id`."""

    def semantic_models(self, workspace_id: str, document_ids: list[str] | None = None) -> set[str]:
        """The embedding models this workspace's (selected) documents have meaning-based vectors for."""
        return {d.semantic_model for d in self.list_documents(workspace_id)
                if d.semantic_model and (not document_ids or d.id in document_ids)}

    def find_document_by_hash(self, workspace_id: str, content_hash: str) -> DocumentRecord | None:
        """An already-indexed document with identical content in this
        workspace (used to skip re-indexing duplicates). Stores that can't
        do this simply never report a duplicate."""
        return None

    @abstractmethod
    def add_chunks(self, workspace_id: str, chunks: list[ChunkInput]) -> None: ...

    @abstractmethod
    def list_documents(self, workspace_id: str) -> list[DocumentRecord]: ...

    @abstractmethod
    def get_document(self, workspace_id: str, document_id: str) -> DocumentRecord | None: ...

    @abstractmethod
    def delete_document(self, workspace_id: str, document_id: str) -> bool: ...

    @abstractmethod
    def has_documents(self, workspace_id: str) -> bool: ...

    @abstractmethod
    def search(
        self, workspace_id: str, query_vector: list[float], top_k: int = 5,
        document_ids: list[str] | None = None, semantic: SemanticQuery | None = None,
    ) -> list[ScoredChunk]: ...


def score_rows(rows, query_vector: list[float], semantic: SemanticQuery | None) -> list[ScoredChunk]:
    """Scores chunk rows (dict-like: document_id, document_name, page_number, chunk_index, text, embedding,
    semantic, semantic_model) for both stores."""
    scored: list[ScoredChunk] = []
    for row in rows:
        try:
            vector = json.loads(row["embedding"])
        except (ValueError, TypeError):
            continue
        lexical = cosine_similarity(query_vector, vector)
        meaning = None
        if semantic is not None and row["semantic_model"] == semantic.model_id and row["semantic"]:
            try:
                meaning = cosine_similarity(semantic.vector, json.loads(row["semantic"]))
            except (ValueError, TypeError):
                meaning = None
        scored.append(ScoredChunk(
            document_id=row["document_id"], document_name=row["document_name"],
            page_number=row["page_number"], chunk_index=int(row["chunk_index"]), text=row["text"],
            score=hybrid_score(lexical, meaning, semantic.floor if semantic else 0.0),
            lexical=lexical, semantic=meaning,
        ))
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored


class LocalVectorStore(VectorStore):
    def __init__(self, db_path: str = "data/vector_store/rag.sqlite3"):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    content_hash TEXT
                )
                """
            )
            # Databases created before duplicate detection lack the column.
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(documents)")}
            if "content_hash" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")
            if "semantic_model" not in columns:
                self._conn.execute("ALTER TABLE documents ADD COLUMN semantic_model TEXT")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_id)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(workspace_id, content_hash)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    document_name TEXT NOT NULL,
                    page_number INTEGER,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL
                )
                """
            )
            chunk_columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(chunks)")}
            if "semantic" not in chunk_columns:
                self._conn.execute("ALTER TABLE chunks ADD COLUMN semantic TEXT")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks(workspace_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id)")

    def _chunk_count(self, document_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE document_id = ?", (document_id,)
        ).fetchone()
        return row["n"] if row else 0

    def _row_to_document(self, row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"], workspace_id=row["workspace_id"], filename=row["filename"],
            original_filename=row["original_filename"], content_type=row["content_type"],
            size_bytes=row["size_bytes"], chunk_count=self._chunk_count(row["id"]),
            created_at=row["created_at"], semantic_model=row["semantic_model"],
        )

    def add_document(
        self, workspace_id: str, document_id: str, filename: str,
        original_filename: str, content_type: str, size_bytes: int,
        content_hash: str | None = None, semantic_model: str | None = None,
    ) -> DocumentRecord:
        ts = _now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO documents (id, workspace_id, filename, original_filename, content_type, "
                "size_bytes, created_at, content_hash, semantic_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (document_id, workspace_id, filename, original_filename, content_type, size_bytes, ts, content_hash, semantic_model),
            )
        return DocumentRecord(
            id=document_id, workspace_id=workspace_id, filename=filename,
            original_filename=original_filename, content_type=content_type,
            size_bytes=size_bytes, chunk_count=0, created_at=ts, semantic_model=semantic_model,
        )

    def set_semantic_model(self, workspace_id: str, document_id: str, model_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE documents SET semantic_model = ? WHERE workspace_id = ? AND id = ?", (model_id, workspace_id, document_id)
            )

    def find_document_by_hash(self, workspace_id: str, content_hash: str) -> DocumentRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE workspace_id = ? AND content_hash = ? LIMIT 1",
                (workspace_id, content_hash),
            ).fetchone()
            return self._row_to_document(row) if row else None

    def add_chunks(self, workspace_id: str, chunks: list[ChunkInput]) -> None:
        if not chunks:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO chunks (workspace_id, document_id, document_name, page_number, "
                "chunk_index, text, embedding, semantic) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        workspace_id, c.document_id, c.document_name, c.page_number,
                        c.chunk_index, c.text, json.dumps(c.embedding),
                        json.dumps(c.semantic) if c.semantic is not None else None,
                    )
                    for c in chunks
                ],
            )

    def list_documents(self, workspace_id: str) -> list[DocumentRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM documents WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,)
            ).fetchall()
        return [self._row_to_document(r) for r in rows]

    def get_document(self, workspace_id: str, document_id: str) -> DocumentRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE workspace_id = ? AND id = ?", (workspace_id, document_id)
            ).fetchone()
        return self._row_to_document(row) if row else None

    def delete_document(self, workspace_id: str, document_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM documents WHERE workspace_id = ? AND id = ?", (workspace_id, document_id)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                self._conn.execute(
                    "DELETE FROM chunks WHERE workspace_id = ? AND document_id = ?", (workspace_id, document_id)
                )
        return deleted

    def has_documents(self, workspace_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM documents WHERE workspace_id = ? LIMIT 1", (workspace_id,)
            ).fetchone()
        return row is not None

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
        with self._lock:
            if document_ids:
                placeholders = ",".join("?" * len(document_ids))
                rows = self._conn.execute(
                    select + f" AND c.document_id IN ({placeholders})", [workspace_id, *document_ids]
                ).fetchall()
            else:
                rows = self._conn.execute(select, (workspace_id,)).fetchall()
        return score_rows(rows, query_vector, semantic)[:top_k]
