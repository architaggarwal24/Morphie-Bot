"""The Cloudflare D1 layer, run against a sqlite3-backed fake of the D1 binding and the real migration."""

import pytest

from fake_d1 import FakeD1Binding, make_d1
from helpers import ScriptedProvider  # noqa: F401  (keeps sys.path identical to the other suites)
from morphie.d1 import D1ConversationHistory, D1RateLimiter
from morphie.providers.embeddings_local import LocalEmbeddingProvider
from morphie.rag.d1_store import D1VectorStore
from morphie.rag.pipeline import RAGIngestionError, RAGPipeline
from morphie.rag.vector_store import ChunkInput

from fixtures import make_txt_bytes


@pytest.fixture
def db():
    return make_d1()


# ---- the D1 wrapper ----

def test_query_execute_and_batch_round_trip(db):
    assert db.execute("INSERT INTO rate_buckets (bucket, window, n) VALUES (?, ?, ?)", ("a", 1, 5)) == 1
    assert db.query("SELECT bucket, n FROM rate_buckets") == [{"bucket": "a", "n": 5}]
    db.batch([
        ("INSERT INTO rate_buckets (bucket, window, n) VALUES (?, ?, ?)", ("b", 1, 1)),
        ("UPDATE rate_buckets SET n = n + 1 WHERE bucket = ?", ("a",)),
    ])
    assert {r["bucket"]: r["n"] for r in db.query("SELECT * FROM rate_buckets")} == {"a": 6, "b": 1}


def test_a_failing_batch_applies_nothing(db):
    with pytest.raises(Exception):
        db.batch([
            ("INSERT INTO rate_buckets (bucket, window, n) VALUES (?, ?, ?)", ("a", 1, 1)),
            ("INSERT INTO no_such_table VALUES (1)", ()),
        ])
    assert db.query("SELECT * FROM rate_buckets") == []


def test_an_empty_batch_is_a_noop(db):
    db.batch([])


# ---- conversation history ----

def test_history_is_per_user_ordered_and_bounded(db):
    history = D1ConversationHistory(db, max_messages=3, sweep_probability=0)
    for i in range(5):
        history.append("alice", "user" if i % 2 == 0 else "assistant", f"m{i}")
    history.append("bob", "user", "hello")
    assert [m["content"] for m in history.get("alice")] == ["m2", "m3", "m4"]
    assert history.get("bob") == [{"role": "user", "content": "hello"}]
    assert history.get("nobody") == []


def test_history_reset_clears_only_that_user(db):
    history = D1ConversationHistory(db, max_messages=5, sweep_probability=0)
    history.append("alice", "user", "a")
    history.append("bob", "user", "b")
    history.reset("alice")
    assert history.get("alice") == [] and len(history.get("bob")) == 1


def test_history_sweeps_rows_older_than_the_ttl(db):
    history = D1ConversationHistory(db, max_messages=5, ttl_days=1, sweep_probability=1.0)
    db.execute("INSERT INTO conversation_messages (user_id, role, content, created_at) VALUES ('old', 'user', 'x', 1)")
    history.append("alice", "user", "fresh")
    assert history.get("old") == [] and len(history.get("alice")) == 1


# ---- rate limiting ----

def test_rate_limiter_allows_up_to_the_limit_then_reports_retry_after(db):
    now = [1000.0]
    limiter = D1RateLimiter(db, "chat:user", 3, 60, clock=lambda: now[0], sweep_probability=0)
    assert [limiter.check("u")[0] for _ in range(3)] == [True, True, True]
    allowed, retry = limiter.check("u")
    assert allowed is False and 1 <= retry <= 60
    assert limiter.check("someone-else")[0] is True  # keys are independent
    now[0] += 61  # next window
    assert limiter.check("u") == (True, 0)


def test_rate_limiter_scopes_do_not_share_counters(db):
    a = D1RateLimiter(db, "chat:user", 1, 60, sweep_probability=0)
    b = D1RateLimiter(db, "upload:user", 1, 60, sweep_probability=0)
    assert a.check("u")[0] and b.check("u")[0]


def test_rate_limiter_with_zero_limit_is_disabled(db):
    limiter = D1RateLimiter(db, "x", 0, 60)
    assert all(limiter.check("u") == (True, 0) for _ in range(50))


# ---- the vector store ----

def _chunk(doc, i, text, vec):
    return ChunkInput(document_id=doc, document_name="n.txt", page_number=None, chunk_index=i, text=text, embedding=vec)


def test_d1_vector_store_documents_chunks_and_isolation(db):
    store = D1VectorStore(db)
    record = store.add_document("ws1", "d1", "d1.txt", "notes.txt", "txt", 10, content_hash="h1")
    assert record.chunk_count == 0
    store.add_chunks("ws1", [_chunk("d1", 0, "alpha", [1.0, 0.0]), _chunk("d1", 1, "beta", [0.0, 1.0])])
    assert store.get_document("ws1", "d1").chunk_count == 2
    assert [d.id for d in store.list_documents("ws1")] == ["d1"]
    assert store.find_document_by_hash("ws1", "h1").id == "d1"
    assert store.find_document_by_hash("ws2", "h1") is None
    assert store.has_documents("ws1") and not store.has_documents("ws2")
    assert store.get_document("ws2", "d1") is None and store.search("ws2", [1.0, 0.0]) == []
    top = store.search("ws1", [1.0, 0.0], top_k=1)
    assert [c.text for c in top] == ["alpha"] and top[0].score == pytest.approx(1.0)
    assert store.delete_document("ws2", "d1") is False
    assert store.delete_document("ws1", "d1") is True
    assert not store.has_documents("ws1") and store.search("ws1", [1.0, 0.0]) == []


def test_d1_vector_store_restricts_search_to_chosen_documents(db):
    store = D1VectorStore(db)
    for doc in ("a", "b"):
        store.add_document("ws", doc, f"{doc}.txt", f"{doc}.txt", "txt", 1)
        store.add_chunks("ws", [_chunk(doc, 0, f"text of {doc}", [1.0, 0.0])])
    assert {c.document_id for c in store.search("ws", [1.0, 0.0])} == {"a", "b"}
    assert [c.document_id for c in store.search("ws", [1.0, 0.0], document_ids=["b"])] == ["b"]


def test_chunks_are_inserted_in_statements_under_the_d1_parameter_limit():
    binding = FakeD1Binding()
    store = D1VectorStore(make_d1(binding))
    store.add_document("ws", "d", "d.txt", "d.txt", "txt", 1)
    seen = []
    original = binding.batch
    binding.batch = lambda statements: (seen.extend(len(s._params) for s in statements), original(statements))[1]
    store.add_chunks("ws", [_chunk("d", i, f"t{i}", [0.1, 0.2]) for i in range(100)])
    assert seen and max(seen) <= 100
    assert store.get_document("ws", "d").chunk_count == 100


def test_the_rag_pipeline_runs_end_to_end_on_d1_without_keeping_files(db):
    pipeline = RAGPipeline(LocalEmbeddingProvider(dim=256), D1VectorStore(db), upload_dir=None,
                           max_upload_size_mb=1, chunk_size=300, chunk_overlap=50, min_score=0.1)
    doc, created = pipeline.ingest_with_status("ws", "recipes.txt", make_txt_bytes("Sourdough needs flour, water, salt and a starter. " * 30))
    assert created and doc.chunk_count > 1
    again, created_again = pipeline.ingest_with_status("ws", "copy.txt", make_txt_bytes("Sourdough needs flour, water, salt and a starter. " * 30))
    assert not created_again and again.id == doc.id  # duplicate detection works through D1
    hits = pipeline.search("ws", "what does sourdough need")
    assert hits and hits[0].document_name == "recipes.txt"
    assert pipeline.delete_document("ws", doc.id) is True
    assert pipeline.list_documents("ws") == []
    with pytest.raises(RAGIngestionError):
        pipeline.ingest_with_status("ws", "bad.exe", b"MZ")
