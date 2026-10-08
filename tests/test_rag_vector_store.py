import pytest

from morphie.rag.vector_store import ChunkInput, LocalVectorStore, cosine_similarity


@pytest.fixture()
def store(tmp_path):
    return LocalVectorStore(db_path=str(tmp_path / "rag.sqlite3"))


def test_cosine_similarity_basic():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([], [1]) == 0.0


def test_add_and_list_documents(store):
    store.add_document("ws1", "doc1", "doc1.pdf", "policy.pdf", "pdf", 1000)
    store.add_document("ws1", "doc2", "doc2.txt", "notes.txt", "txt", 200)

    docs = store.list_documents("ws1")
    assert len(docs) == 2
    assert {d.original_filename for d in docs} == {"policy.pdf", "notes.txt"}


def test_documents_are_scoped_per_workspace(store):
    store.add_document("ws1", "doc1", "doc1.pdf", "policy.pdf", "pdf", 1000)
    store.add_document("ws2", "doc2", "doc2.pdf", "other.pdf", "pdf", 1000)

    assert [d.original_filename for d in store.list_documents("ws1")] == ["policy.pdf"]
    assert [d.original_filename for d in store.list_documents("ws2")] == ["other.pdf"]


def test_chunk_count_reflects_added_chunks(store):
    store.add_document("ws1", "doc1", "doc1.pdf", "policy.pdf", "pdf", 1000)
    store.add_chunks("ws1", [
        ChunkInput(document_id="doc1", document_name="policy.pdf", page_number=1, chunk_index=0,
                   text="chunk one", embedding=[1.0, 0.0]),
        ChunkInput(document_id="doc1", document_name="policy.pdf", page_number=1, chunk_index=1,
                   text="chunk two", embedding=[0.0, 1.0]),
    ])
    doc = store.get_document("ws1", "doc1")
    assert doc.chunk_count == 2


def test_delete_document_cascades_to_chunks(store):
    store.add_document("ws1", "doc1", "doc1.pdf", "policy.pdf", "pdf", 1000)
    store.add_chunks("ws1", [
        ChunkInput(document_id="doc1", document_name="policy.pdf", page_number=1, chunk_index=0,
                   text="chunk one", embedding=[1.0, 0.0]),
    ])

    assert store.delete_document("ws1", "doc1") is True
    assert store.get_document("ws1", "doc1") is None
    assert store.search("ws1", [1.0, 0.0], top_k=5) == []


def test_delete_does_not_cross_workspaces(store):
    store.add_document("ws1", "doc1", "doc1.pdf", "policy.pdf", "pdf", 1000)
    assert store.delete_document("ws2", "doc1") is False
    assert store.get_document("ws1", "doc1") is not None


def test_has_documents(store):
    assert store.has_documents("ws1") is False
    store.add_document("ws1", "doc1", "doc1.pdf", "policy.pdf", "pdf", 1000)
    assert store.has_documents("ws1") is True


def test_search_ranks_by_similarity_and_respects_top_k(store):
    store.add_document("ws1", "doc1", "doc1.pdf", "policy.pdf", "pdf", 1000)
    store.add_chunks("ws1", [
        ChunkInput(document_id="doc1", document_name="policy.pdf", page_number=1, chunk_index=0,
                   text="exact match", embedding=[1.0, 0.0, 0.0]),
        ChunkInput(document_id="doc1", document_name="policy.pdf", page_number=2, chunk_index=1,
                   text="partial match", embedding=[0.7, 0.7, 0.0]),
        ChunkInput(document_id="doc1", document_name="policy.pdf", page_number=3, chunk_index=2,
                   text="unrelated", embedding=[0.0, 0.0, 1.0]),
    ])

    results = store.search("ws1", [1.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    assert results[0].text == "exact match"
    assert results[0].score == pytest.approx(1.0)


def test_search_is_scoped_per_workspace(store):
    store.add_document("ws1", "doc1", "doc1.pdf", "a.pdf", "pdf", 1000)
    store.add_chunks("ws1", [
        ChunkInput(document_id="doc1", document_name="a.pdf", page_number=1, chunk_index=0,
                   text="ws1 content", embedding=[1.0, 0.0]),
    ])
    store.add_document("ws2", "doc2", "doc2.pdf", "b.pdf", "pdf", 1000)
    store.add_chunks("ws2", [
        ChunkInput(document_id="doc2", document_name="b.pdf", page_number=1, chunk_index=0,
                   text="ws2 content", embedding=[1.0, 0.0]),
    ])

    ws1_results = store.search("ws1", [1.0, 0.0], top_k=5)
    assert len(ws1_results) == 1
    assert ws1_results[0].text == "ws1 content"


def test_search_can_be_scoped_to_selected_documents(store):
    store.add_document("ws1", "doc1", "doc1.pdf", "a.pdf", "pdf", 1000)
    store.add_document("ws1", "doc2", "doc2.pdf", "b.pdf", "pdf", 1000)
    store.add_chunks("ws1", [
        ChunkInput(document_id="doc1", document_name="a.pdf", page_number=1, chunk_index=0,
                   text="from doc1", embedding=[1.0, 0.0]),
        ChunkInput(document_id="doc2", document_name="b.pdf", page_number=1, chunk_index=0,
                   text="from doc2", embedding=[1.0, 0.0]),
    ])

    results = store.search("ws1", [1.0, 0.0], top_k=5, document_ids=["doc1"])
    assert len(results) == 1
    assert results[0].text == "from doc1"
