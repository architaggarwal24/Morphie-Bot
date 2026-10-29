"""Hybrid document search: meaning-based embeddings next to the keyword ones, with a keyword-only fallback."""

import pytest

from fake_d1 import make_d1
from fixtures import make_txt_bytes
from morphie.providers.embeddings import EmbeddingProvider
from morphie.providers.embeddings_local import LocalEmbeddingProvider
from morphie.rag.d1_store import D1VectorStore
from morphie.rag.pipeline import RAGPipeline
from morphie.rag.vector_store import LocalVectorStore, hybrid_score

# A toy "meaning" space: texts about programming point one way, cooking the other.
TOPICS = {"code": ("python", "programming", "software", "developer", "engineer", "coding"),
          "food": ("recipe", "cooking", "pasta", "kitchen", "chef")}


class ToyMeaning(EmbeddingProvider):
    model_id = "toy:meaning-1"
    name = "toy"
    min_score = 0.5

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def is_configured(self):
        return True

    def embed(self, text):
        self.calls += 1
        if self.fail:
            raise RuntimeError("embedding service down")
        words = text.lower()
        code = sum(w in words for w in TOPICS["code"])
        food = sum(w in words for w in TOPICS["food"])
        return [float(code) + 0.01, float(food) + 0.01]


@pytest.fixture(params=["local", "d1"])
def pipeline(request, tmp_path):
    store = LocalVectorStore(":memory:") if request.param == "local" else D1VectorStore(make_d1())
    return RAGPipeline(LocalEmbeddingProvider(dim=256), store, upload_dir=None, min_score=0.15)


def test_a_paraphrase_finds_the_passage_by_meaning(pipeline):
    meaning = ToyMeaning()
    doc, _ = pipeline.ingest_with_status("ws", "cv.txt", make_txt_bytes("Five years as a software engineer writing Python."), semantic=meaning)
    pipeline.ingest_with_status("ws", "food.txt", make_txt_bytes("My favourite pasta recipe from the kitchen."), semantic=meaning)
    assert doc.semantic_model == "toy:meaning-1" and doc.to_dict()["search"] == "semantic"

    keyword_only = pipeline.search("ws", "coding experience?")
    hybrid = pipeline.search("ws", "coding experience?", semantic=meaning)
    assert keyword_only == []                                    # no shared words...
    assert [c.document_name for c in hybrid] == ["cv.txt"]       # ...but the same meaning


def test_a_failed_embedding_still_indexes_the_document_for_keywords(pipeline):
    doc, created = pipeline.ingest_with_status("ws", "cv.txt", make_txt_bytes("Python developer."), semantic=ToyMeaning(fail=True))
    assert created and doc.semantic_model is None and doc.to_dict()["search"] == "keyword"
    assert pipeline.last_semantic_error
    assert [c.document_name for c in pipeline.search("ws", "Python developer")] == ["cv.txt"]


def test_a_different_embedding_model_is_never_compared(pipeline):
    pipeline.ingest_with_status("ws", "cv.txt", make_txt_bytes("Software engineer."), semantic=ToyMeaning())
    other = ToyMeaning()
    other.model_id = "toy:another-model"
    assert pipeline.search("ws", "coding experience?", semantic=other) == []
    assert other.calls == 0  # the query wasn't even embedded


def test_hybrid_score_rescales_meaning_from_the_models_floor():
    assert hybrid_score(0.4, None, 0.5) == 0.4
    assert hybrid_score(0.0, 0.5, 0.5) == 0.0
    assert hybrid_score(1.0, 1.0, 0.5) == pytest.approx(1.0)
