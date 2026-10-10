"""
Local implementation of EmbeddingProvider - no API calls, no model
download, works fully offline.

This is a deterministic "hashing trick" bag-of-words embedding: each
token (and word bigram, for a little more context) is hashed into a
fixed-size vector with sklearn-style signed hashing, then L2-normalized.
It is not a neural/semantic embedding - two sentences about the same
topic in very different words will not necessarily land close together -
but it captures shared-vocabulary similarity well, needs zero setup, and
costs nothing per call, which is why it powers RAG here. A neural
embedding model (hosted, or sentence-transformers) would slot in behind
the exact same EmbeddingProvider interface if you want better semantic
recall.
"""

from __future__ import annotations

import hashlib
import re

from .embeddings import EmbeddingProvider

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")

# Without filtering these out, two unrelated texts still share a lot of
# "stopword mass" (the, is, for, of...) which inflates cosine similarity
# and makes irrelevant documents look deceptively relevant.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their",
    "to", "of", "in", "on", "for", "with", "at", "by", "from", "as", "and", "or", "but",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "do", "does", "did", "have", "has", "had", "will", "would", "should", "could",
    "can", "may", "might", "must", "not", "no", "so", "if", "then", "all",
}


def _hash_index(token: str, dim: int) -> tuple[int, int]:
    """Deterministic (unlike Python's salted str hash) index + sign for
    the hashing trick, using MD5 so it's stable across processes/runs."""
    digest = hashlib.md5(token.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % dim
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    return index, sign


class LocalEmbeddingProvider(EmbeddingProvider):
    name = "local"

    def __init__(self, dim: int = 384):
        self.dim = max(16, dim)

    def is_configured(self) -> bool:
        return True  # always available - no credentials needed

    def embed(self, text: str) -> list[float]:
        words = [w.lower() for w in _WORD_RE.findall(text or "") if w.lower() not in _STOPWORDS and len(w) > 1]
        vector = [0.0] * self.dim

        tokens = list(words)
        # Word bigrams add a little local context beyond pure bag-of-words.
        tokens.extend(f"{a}_{b}" for a, b in zip(words, words[1:]))

        for token in tokens:
            index, sign = _hash_index(token, self.dim)
            vector[index] += sign

        norm = sum(v * v for v in vector) ** 0.5
        if norm == 0:
            return vector
        return [v / norm for v in vector]
