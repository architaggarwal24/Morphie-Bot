"""
Embedding provider interface.

Parallel to LLMProvider: an abstraction so document search doesn't depend
on any one vendor's embeddings API. Today there is one implementation
(LocalEmbeddingProvider, offline); a hosted one can be added by
subclassing this.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return an embedding vector for `text`. Raises on transport/API
        errors."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts, in order. The default just loops over embed();
        providers whose API accepts several inputs per request override this
        so indexing a document costs a few calls instead of one per chunk."""
        return [self.embed(text) for text in texts]
