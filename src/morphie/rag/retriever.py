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
from .vector_store import ScoredChunk, VectorStore


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

    def _embed_query(self, query: str) -> list[float]:
        with self._cache_lock:
            cached = self._cache.get(query)
            if cached is not None:
                self._cache.move_to_end(query)
                return cached
        vector = self.embedding_provider.embed(query)
        if self.cache_size:
            with self._cache_lock:
                self._cache[query] = vector
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
        return vector

    def retrieve(
        self, workspace_id: str, query: str, top_k: int | None = None,
        document_ids: list[str] | None = None,
    ) -> list[ScoredChunk]:
        if not self.vector_store.has_documents(workspace_id):
            return []
        try:
            query_vector = self._embed_query(query)
        except Exception:
            return []

        results = self.vector_store.search(
            workspace_id, query_vector, top_k=top_k or self.top_k, document_ids=document_ids
        )
        return [r for r in results if r.score >= self.min_score]
