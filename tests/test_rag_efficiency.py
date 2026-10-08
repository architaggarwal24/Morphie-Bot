"""RAG cost and abuse controls: batching, dedupe, caching, chunk caps, decompression bombs."""

import io
import sqlite3
import zipfile

import pytest

from morphie.providers.embeddings import EmbeddingProvider
from morphie.providers.embeddings_local import LocalEmbeddingProvider
from morphie.rag import loaders
from morphie.rag.loaders import DocumentLoadError, check_content_matches_extension
from morphie.rag.pipeline import RAGIngestionError, RAGPipeline
from morphie.rag.retriever import DocumentRetriever
from morphie.rag.vector_store import LocalVectorStore

from fixtures import make_docx_bytes, make_txt_bytes

WS = "ws-1"


class CountingEmbedder(EmbeddingProvider):
    """Wraps the local embedder and records how it was called."""

    name = "counting"

    def __init__(self):
        self.inner = LocalEmbeddingProvider(dim=64)
        self.embed_calls = 0
        self.batch_sizes = []

    def is_configured(self):
        return True

    def embed(self, text):
        self.embed_calls += 1
        return self.inner.embed(text)

    def embed_batch(self, texts):
        self.batch_sizes.append(len(texts))
        return [self.inner.embed(t) for t in texts]


def _pipeline(tmp_path, embedder=None, **kwargs):
    embedder = embedder or CountingEmbedder()
    options = dict(upload_dir=str(tmp_path / "docs"), max_upload_size_mb=5, chunk_size=200, chunk_overlap=20, min_score=0.05)
    options.update(kwargs)
    return RAGPipeline(embedder, LocalVectorStore(db_path=str(tmp_path / "rag.sqlite3")), **options), embedder


def _long_text(paragraphs=70):
    return make_txt_bytes("\n\n".join(f"Paragraph {i}: " + "lorem ipsum dolor sit amet " * 8 for i in range(paragraphs)))


# ---- batching ----

def test_the_default_embed_batch_preserves_order_and_uses_embed():
    class Plain(EmbeddingProvider):
        def is_configured(self): return True
        def embed(self, text): return [float(len(text))]

    assert Plain().embed_batch(["a", "bb", "ccc"]) == [[1.0], [2.0], [3.0]]
    assert Plain().embed_batch([]) == []


def test_ingestion_embeds_in_batches_not_one_call_per_chunk(tmp_path):
    pipeline, embedder = _pipeline(tmp_path)
    doc = pipeline.ingest(WS, "big.txt", _long_text(70))
    assert doc.chunk_count > 60
    assert embedder.embed_calls == 0                          # no per-chunk calls
    assert sum(embedder.batch_sizes) == doc.chunk_count
    assert max(embedder.batch_sizes) <= 32 and len(embedder.batch_sizes) <= -(-doc.chunk_count // 32) + 1


# ---- chunk cap ----

def test_a_document_needing_too_many_chunks_is_rejected_before_any_embedding(tmp_path):
    pipeline, embedder = _pipeline(tmp_path, max_chunks_per_document=10)
    with pytest.raises(RAGIngestionError) as exc:
        pipeline.ingest(WS, "huge.txt", _long_text(70))
    assert "too large" in str(exc.value).lower()
    assert embedder.batch_sizes == [] and embedder.embed_calls == 0
    assert pipeline.list_documents(WS) == []
    assert not list((tmp_path / "docs").rglob("*.txt"))          # nothing left on disk


# ---- dedupe ----

def test_uploading_identical_content_again_returns_the_existing_document_without_reindexing(tmp_path):
    pipeline, embedder = _pipeline(tmp_path)
    content = _long_text(5)
    first, created_first = pipeline.ingest_with_status(WS, "notes.txt", content)
    embedded = sum(embedder.batch_sizes)
    second, created_second = pipeline.ingest_with_status(WS, "notes-copy.txt", content)
    assert created_first is True and created_second is False
    assert second.id == first.id and second.original_filename == "notes.txt"
    assert sum(embedder.batch_sizes) == embedded               # not embedded a second time
    assert len(pipeline.list_documents(WS)) == 1


def test_plain_ingest_still_returns_a_record_for_duplicates(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    a = pipeline.ingest(WS, "a.txt", _long_text(3))
    b = pipeline.ingest(WS, "a.txt", _long_text(3))
    assert a.id == b.id


def test_dedupe_is_per_workspace_and_per_content(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    content = _long_text(3)
    mine = pipeline.ingest("alice", "a.txt", content)
    theirs = pipeline.ingest("bob", "a.txt", content)              # same bytes, different user: separate document
    other = pipeline.ingest("alice", "b.txt", _long_text(4))
    assert len({mine.id, theirs.id, other.id}) == 3
    assert len(pipeline.list_documents("alice")) == 2 and len(pipeline.list_documents("bob")) == 1


def test_deleting_a_document_allows_uploading_it_again(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    content = _long_text(3)
    first, _ = pipeline.ingest_with_status(WS, "a.txt", content)
    assert pipeline.delete_document(WS, first.id)
    again, created = pipeline.ingest_with_status(WS, "a.txt", content)
    assert created is True and again.id != first.id


def test_a_pre_existing_database_without_the_hash_column_is_migrated(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, filename TEXT NOT NULL, "
                 "original_filename TEXT NOT NULL, content_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO documents VALUES ('old1', 'ws', 'old1.txt', 'old.txt', 'txt', 10, '2024-01-01T00:00:00')")
    conn.commit(); conn.close()

    store = LocalVectorStore(db_path=path)                          # opening must migrate, not crash
    assert [d.original_filename for d in store.list_documents("ws")] == ["old.txt"]
    pipeline = RAGPipeline(CountingEmbedder(), store, upload_dir=str(tmp_path / "docs"), chunk_size=200, chunk_overlap=20)
    doc = pipeline.ingest("ws", "new.txt", _long_text(2))
    assert pipeline.ingest("ws", "new.txt", _long_text(2)).id == doc.id
    assert len(store.list_documents("ws")) == 2


# ---- query embedding cache ----

def test_repeated_identical_queries_reuse_the_embedding(tmp_path):
    pipeline, embedder = _pipeline(tmp_path)
    pipeline.ingest(WS, "a.txt", _long_text(3))
    embedder.embed_calls = 0
    for _ in range(3):
        pipeline.search(WS, "lorem ipsum")
    assert embedder.embed_calls == 1
    pipeline.search(WS, "something different")
    assert embedder.embed_calls == 2


def test_the_query_cache_is_bounded(tmp_path):
    store = LocalVectorStore(db_path=str(tmp_path / "r.sqlite3"))
    embedder = CountingEmbedder()
    retriever = DocumentRetriever(embedder, store, cache_size=8)
    pipeline = RAGPipeline(embedder, store, upload_dir=str(tmp_path / "d"), chunk_size=200, chunk_overlap=20)
    pipeline.ingest(WS, "a.txt", _long_text(2))
    for i in range(100):
        retriever.retrieve(WS, f"query {i}")
    assert retriever.cache_len() <= 8


def test_a_failed_query_embedding_is_not_cached(tmp_path):
    store = LocalVectorStore(db_path=str(tmp_path / "r.sqlite3"))

    class Flaky(CountingEmbedder):
        fail = True

        def embed(self, text):
            if self.fail:
                raise RuntimeError("down")
            return super().embed(text)

    embedder = Flaky()
    RAGPipeline(embedder, store, upload_dir=str(tmp_path / "d"), chunk_size=200, chunk_overlap=20).ingest(WS, "a.txt", _long_text(2))
    retriever = DocumentRetriever(embedder, store)
    assert retriever.retrieve(WS, "lorem") == []
    embedder.fail = False
    assert retriever.retrieve(WS, "lorem") != []


# ---- decompression bombs ----

def _zip_with(size, name="word/document.xml"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, b"\0" * size)
    return buffer.getvalue()


def test_a_zip_that_expands_enormously_is_rejected_without_unpacking_it(monkeypatch):
    monkeypatch.setattr(loaders, "MAX_UNCOMPRESSED_BYTES", 1024 * 1024)
    bomb = _zip_with(20 * 1024 * 1024)
    assert len(bomb) < 100 * 1024                                     # tiny on the wire
    with pytest.raises(DocumentLoadError) as exc:
        check_content_matches_extension("docx", bomb)
    assert "too large" in str(exc.value).lower()


def test_a_zip_with_an_absurd_number_of_entries_is_rejected(monkeypatch):
    monkeypatch.setattr(loaders, "MAX_ZIP_ENTRIES", 20)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for i in range(50):
            z.writestr(f"f{i}.xml", b"x")
    with pytest.raises(DocumentLoadError):
        check_content_matches_extension("docx", buffer.getvalue())


def test_a_truncated_zip_is_reported_as_not_a_real_word_document():
    with pytest.raises(DocumentLoadError):
        check_content_matches_extension("docx", b"PK\x03\x04" + b"garbage" * 10)


def test_a_normal_word_document_still_passes_the_guard_and_ingests(tmp_path):
    docx = make_docx_bytes(["Vacation policy: employees get 25 days of paid leave per year."])
    check_content_matches_extension("docx", docx)
    pipeline, _ = _pipeline(tmp_path)
    assert pipeline.ingest(WS, "policy.docx", docx).chunk_count >= 1


def test_library_error_details_are_not_shown_to_the_user_for_binary_formats(tmp_path):
    pipeline, _ = _pipeline(tmp_path)
    # Looks like a docx (PK header + valid zip) but has no Word structure inside.
    bogus = _zip_with(100, name="not-word.txt")
    with pytest.raises(RAGIngestionError) as exc:
        pipeline.ingest(WS, "fake.docx", bogus)
    message = str(exc.value)
    assert "Traceback" not in message and "KeyError" not in message and "word/document.xml" not in message
    assert "Word document" in message
