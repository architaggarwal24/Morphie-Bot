"""
RAG pipeline.

Ties the whole flow together:

  file bytes -> validate -> load (extract text) -> chunk -> embed -> store

and the inverse for answering questions:

  query -> embed -> vector search -> top-K relevant chunks

`RAGIngestionError` is the single, user-facing exception type for
anything wrong with an upload (bad type, too large, unreadable content) -
callers (the Flask route) can catch one exception type and show its
message directly, since these messages are always written to be safe to
show.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename

from ..providers.embeddings import EmbeddingProvider
from .chunking import chunk_text
from .loaders import (
    SUPPORTED_EXTENSIONS,
    DocumentLoadError,
    check_content_matches_extension,
    get_loader_for,
)
from .retriever import DocumentRetriever
from .vector_store import ChunkInput, DocumentRecord, ScoredChunk, VectorStore


class RAGIngestionError(Exception):
    """A validation or processing error safe to show to the user as-is."""


class RAGPipeline:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        upload_dir: "str | None" = "data/documents",
        max_upload_size_mb: int = 20,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        top_k: int = 5,
        min_score: float = 0.1,
        max_chunks_per_document: int = 2000,
    ):
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        # None = don't keep the original files (Cloudflare Workers has no disk to keep them on; only the
        # extracted text chunks are stored, which is all search ever reads).
        self.upload_dir = Path(upload_dir) if upload_dir else None
        self.max_upload_bytes = max(1, max_upload_size_mb) * 1024 * 1024
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_chunks_per_document = max(1, max_chunks_per_document)
        self.retriever = DocumentRetriever(embedding_provider, vector_store, top_k=top_k, min_score=min_score)

    # ---- ingestion ----

    EMBED_BATCH_SIZE = 32

    def ingest(self, workspace_id: str, original_filename: str, file_bytes: bytes) -> DocumentRecord:
        return self.ingest_with_status(workspace_id, original_filename, file_bytes)[0]

    def ingest_with_status(
        self, workspace_id: str, original_filename: str, file_bytes: bytes
    ) -> tuple[DocumentRecord, bool]:
        """Ingest a file. Returns (document, created). Uploading content this
        workspace already has returns the existing document with created=False
        and does no parsing, embedding, or storage - re-indexing identical
        bytes would cost embedding calls and only produce duplicate search hits."""
        safe_name = self._sanitize_filename(original_filename)
        extension = self._extract_extension(safe_name)
        if extension not in SUPPORTED_EXTENSIONS:
            raise RAGIngestionError(
                f"Unsupported file type '.{extension}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
            )

        if len(file_bytes) == 0:
            raise RAGIngestionError("The uploaded file is empty.")
        if len(file_bytes) > self.max_upload_bytes:
            max_mb = self.max_upload_bytes // (1024 * 1024)
            raise RAGIngestionError(f"File is too large - the limit is {max_mb} MB.")

        try:
            check_content_matches_extension(extension, file_bytes)
        except DocumentLoadError as exc:
            raise RAGIngestionError(str(exc)) from exc

        content_hash = hashlib.sha256(file_bytes).hexdigest()
        existing = self.vector_store.find_document_by_hash(workspace_id, content_hash)
        if existing is not None:
            return existing, False

        try:
            loader = get_loader_for(extension)
            pages = loader.load(file_bytes)
        except DocumentLoadError as exc:
            raise RAGIngestionError(str(exc)) from exc

        if not pages:
            raise RAGIngestionError("No readable text could be extracted from this file.")

        # Chunk everything first: an over-large document is rejected before a
        # single embedding call is made or a byte is written.
        pieces: list[tuple[int | None, str]] = [
            (page.page_number, piece)
            for page in pages
            for piece in chunk_text(page.text, self.chunk_size, self.chunk_overlap)
        ]
        if not pieces:
            raise RAGIngestionError("No text could be extracted from this file.")
        if len(pieces) > self.max_chunks_per_document:
            raise RAGIngestionError(
                f"This document is too large to index (more than {self.max_chunks_per_document} sections). "
                "Try splitting it into smaller files."
            )

        document_id = uuid.uuid4().hex
        on_disk_name = f"{document_id}.{extension}"
        file_path: "Path | None" = None
        if self.upload_dir is not None:
            workspace_dir = self._workspace_dir(workspace_id)
            workspace_dir.mkdir(parents=True, exist_ok=True)
            # Path is built entirely from a server-generated id + validated
            # extension - the user-supplied filename never touches the
            # filesystem path, which is what actually prevents path traversal.
            file_path = workspace_dir / on_disk_name

        try:
            if file_path is not None:
                file_path.write_bytes(file_bytes)
            self.vector_store.add_document(
                workspace_id=workspace_id, document_id=document_id, filename=on_disk_name,
                original_filename=safe_name, content_type=extension, size_bytes=len(file_bytes),
                content_hash=content_hash,
            )

            chunk_inputs: list[ChunkInput] = []
            for start in range(0, len(pieces), self.EMBED_BATCH_SIZE):
                batch = pieces[start:start + self.EMBED_BATCH_SIZE]
                embeddings = self.embedding_provider.embed_batch([text for _, text in batch])
                for offset, ((page_number, text), embedding) in enumerate(zip(batch, embeddings)):
                    chunk_inputs.append(
                        ChunkInput(
                            document_id=document_id, document_name=safe_name, page_number=page_number,
                            chunk_index=start + offset, text=text, embedding=embedding,
                        )
                    )

            self.vector_store.add_chunks(workspace_id, chunk_inputs)
        except Exception:
            # Roll back a partial ingest rather than leaving an orphaned
            # document with no (or partial) chunks.
            if file_path is not None:
                file_path.unlink(missing_ok=True)
            self.vector_store.delete_document(workspace_id, document_id)
            raise

        return self.vector_store.get_document(workspace_id, document_id), True

    # ---- management ----

    def list_documents(self, workspace_id: str) -> list[DocumentRecord]:
        return self.vector_store.list_documents(workspace_id)

    def delete_document(self, workspace_id: str, document_id: str) -> bool:
        document = self.vector_store.get_document(workspace_id, document_id)
        deleted = self.vector_store.delete_document(workspace_id, document_id)
        if deleted and document and self.upload_dir is not None:
            (self._workspace_dir(workspace_id) / document.filename).unlink(missing_ok=True)
        return deleted

    def has_documents(self, workspace_id: str) -> bool:
        return self.vector_store.has_documents(workspace_id)

    # ---- retrieval ----

    def search(
        self, workspace_id: str, query: str, top_k: int | None = None,
        document_ids: list[str] | None = None,
    ) -> list[ScoredChunk]:
        return self.retriever.retrieve(workspace_id, query, top_k=top_k, document_ids=document_ids)

    # ---- internals ----

    def _workspace_dir(self, workspace_id: str) -> Path:
        # Defense in depth: workspace_id is a server-generated uuid hex
        # already, but never trust it to be filesystem-safe unchecked.
        safe_workspace = re.sub(r"[^a-zA-Z0-9_-]", "_", workspace_id) or "default"
        return self.upload_dir / safe_workspace

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        safe = secure_filename(filename or "")
        if not safe:
            raise RAGIngestionError("Invalid or missing filename.")
        return safe

    @staticmethod
    def _extract_extension(filename: str) -> str:
        if "." not in filename:
            raise RAGIngestionError("File must have an extension (e.g. .pdf, .txt, .docx, .csv, .json).")
        return filename.rsplit(".", 1)[-1].lower()
