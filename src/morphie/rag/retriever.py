"""
Document retriever.

Turns a question into the top-K relevant chunks - never the whole vector
store. A minimum similarity score filters out chunks that technically
rank highest among a workspace's documents but aren't actually relevant,
which matters most when a workspace only has documents unrelated to the
question (e.g. asking "what's 2+2" with only a resume uploaded).
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from ..providers.embeddings import EmbeddingProvider
from .vector_store import ScoredChunk, SemanticQuery, VectorStore


class DocumentRetriever:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        top_k: int = 5,
        min_score: float = 0.1,
        cache_size: int = 128,
    ):
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.top_k = top_k
        self.min_score = min_score
        # Query embeddings are cached (small LRU): the agent often searches the
        # same phrase more than once in a turn, and with an API embedder every
        # miss is a paid network call. Failures are never cached.
        self.cache_size = max(0, cache_size)
        self._cache: "OrderedDict[str, list[float]]" = OrderedDict()
        self._cache_lock = threading.Lock()

    def cache_len(self) -> int:
        with self._cache_lock:
            return len(self._cache)

    def _embed_query(self, query: str, embedder: EmbeddingProvider | None = None) -> list[float]:
        embedder = embedder or self.embedding_provider
        key = f"{getattr(embedder, 'model_id', embedder.name)}\x00{query}"
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
        vector = embedder.embed(query)
        if self.cache_size:
            with self._cache_lock:
                self._cache[key] = vector
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
        return vector

    def _semantic_query(self, workspace_id: str, query: str, semantic: EmbeddingProvider | None,
                        document_ids: list[str] | None) -> SemanticQuery | None:
        """Embed the query by meaning only if some searched document has vectors from the same model."""
        model_id = getattr(semantic, "model_id", None)
        if semantic is None or not model_id or model_id not in self.vector_store.semantic_models(workspace_id, document_ids):
            return None
        try:
            return SemanticQuery(model_id, self._embed_query(query, semantic), float(getattr(semantic, "min_score", 0.3)))
        except Exception:  # noqa: BLE001 - fall back to keyword search
            return None

    def retrieve(
        self, workspace_id: str, query: str, top_k: int | None = None,
        document_ids: list[str] | None = None, semantic: EmbeddingProvider | None = None,
    ) -> list[ScoredChunk]:
        """Hybrid when possible: chunks are ranked by meaning and shared words together (see hybrid_score), and
        kept if either signal says they're relevant - the keyword score clears `min_score`, or the meaning score
        clears the embedding model's own "unrelated" floor."""
        if not self.vector_store.has_documents(workspace_id):
            return []
        try:
            query_vector = self._embed_query(query)
        except Exception:
            return []
        meaning = self._semantic_query(workspace_id, query, semantic, document_ids)

        results = self.vector_store.search(
            workspace_id, query_vector, top_k=top_k or self.top_k, document_ids=document_ids, semantic=meaning,
        )
        return [
            r for r in results
            if r.lexical >= self.min_score or (r.semantic is not None and meaning is not None and r.semantic >= meaning.floor)
        ]
