"""
Meaning-based (neural) embeddings from the visitor's own provider.

The offline hashing embedding (embeddings_local.py) matches shared words; these match meaning, so "how many
years of Python" can find "five years writing Python services". They run on the same bring-your-own key as chat
and are optional: when no key is available, or the call fails, documents are simply searched by keywords.

  OpenAICompatibleEmbeddings   POST {base_url}/embeddings  (OpenAI, Mistral)
  OllamaEmbeddings             POST {base_url}/api/embed   (local models, e.g. nomic-embed-text)

Vectors are rounded before storage: six significant decimals change no ranking and roughly halve the JSON.
"""

from __future__ import annotations

from .. import net as requests  # `requests` locally; fetch() on Cloudflare Workers
from .embeddings import EmbeddingProvider

TIMEOUT_SECONDS = 30


class EmbeddingError(Exception):
    """A remote embedding call failed. The message is safe to show (never contains the key)."""


def _round(vector) -> list[float]:
    return [round(float(x), 6) for x in vector]


class _RemoteEmbeddings(EmbeddingProvider):
    """`model_id` ("<provider>:<model>") is stored with each document, so a query is only ever compared with
    vectors from the same model. `min_score` is that model's "probably unrelated below this" cosine."""

    def __init__(self, provider_id: str, model: str, min_score: float):
        self.provider_id = provider_id
        self.model = model
        self.model_id = f"{provider_id}:{model}"
        self.min_score = min_score
        self.name = self.model_id

    def is_configured(self) -> bool:
        return True

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)
        except requests.RequestException:
            raise EmbeddingError(f"Could not reach {self.provider_id} for embeddings.") from None
        if response.status_code >= 400:
            raise EmbeddingError(f"{self.provider_id} refused the embedding request (HTTP {response.status_code}).")
        try:
            return response.json()
        except ValueError:
            raise EmbeddingError(f"{self.provider_id} returned unreadable embeddings.") from None


class OpenAICompatibleEmbeddings(_RemoteEmbeddings):
    def __init__(self, provider_id: str, base_url: str, api_key: str, model: str, min_score: float, dimensions: int | None = None):
        super().__init__(provider_id, model, min_score)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.dimensions = dimensions

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict = {"model": self.model, "input": texts}
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        data = self._post(
            f"{self.base_url}/embeddings", payload,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            rows = sorted(data["data"], key=lambda r: r.get("index", 0))
            vectors = [_round(r["embedding"]) for r in rows]
        except (KeyError, TypeError, ValueError):
            raise EmbeddingError(f"{self.provider_id} returned unreadable embeddings.") from None
        if len(vectors) != len(texts):
            raise EmbeddingError(f"{self.provider_id} returned the wrong number of embeddings.")
        return vectors


class OllamaEmbeddings(_RemoteEmbeddings):
    def __init__(self, base_url: str, model: str, min_score: float, api_key: str | None = None):
        super().__init__("ollama", model, min_score)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = self._post(f"{self.base_url}/api/embed", {"model": self.model, "input": texts}, headers)
        try:
            vectors = [_round(v) for v in data["embeddings"]]
        except (KeyError, TypeError, ValueError):
            raise EmbeddingError("Ollama returned unreadable embeddings.") from None
        if len(vectors) != len(texts):
            raise EmbeddingError("Ollama returned the wrong number of embeddings.")
        return vectors
