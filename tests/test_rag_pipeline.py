import os

import pytest

from morphie.providers.embeddings_local import LocalEmbeddingProvider
from morphie.rag.pipeline import RAGIngestionError, RAGPipeline
from morphie.rag.vector_store import LocalVectorStore

from fixtures import make_csv_bytes, make_docx_bytes, make_json_bytes, make_pdf_bytes, make_txt_bytes

WS = "test-workspace"


@pytest.fixture()
def pipeline(tmp_path):
    store = LocalVectorStore(db_path=str(tmp_path / "rag.sqlite3"))
    embeddings = LocalEmbeddingProvider(dim=256)
    return RAGPipeline(
        embedding_provider=embeddings,
        vector_store=store,
        upload_dir=str(tmp_path / "documents"),
        max_upload_size_mb=1,
        chunk_size=300,
        chunk_overlap=50,
        min_score=0.1,
    )


# ---- 1: PDF upload ----

def test_pdf_upload_and_ingestion(pipeline):
    pdf_bytes = make_pdf_bytes(["The refund period for all purchases is 30 days from the date of delivery."])
    doc = pipeline.ingest(WS, "company_policy.pdf", pdf_bytes)

    assert doc.original_filename == "company_policy.pdf"
    assert doc.content_type == "pdf"
    assert doc.chunk_count >= 1
    # The raw file is stored on disk, separately from application code.
    stored_path = pipeline._workspace_dir(WS) / doc.filename
    assert stored_path.exists()
    assert stored_path.read_bytes() == pdf_bytes


# ---- 2: TXT upload ----

def test_txt_upload_and_ingestion(pipeline):
    doc = pipeline.ingest(WS, "notes.txt", make_txt_bytes("Meeting notes: use FastAPI for the microservice."))
    assert doc.content_type == "txt"
    assert doc.chunk_count == 1


def test_docx_and_csv_and_json_upload(pipeline):
    doc1 = pipeline.ingest(WS, "resume.docx", make_docx_bytes(["Skills: Python, LangChain."]))
    doc2 = pipeline.ingest(WS, "team.csv", make_csv_bytes([{"name": "Alice", "role": "Engineer"}]))
    doc3 = pipeline.ingest(WS, "project.json", make_json_bytes({"project": "Morphie"}))

    assert {doc1.content_type, doc2.content_type, doc3.content_type} == {"docx", "csv", "json"}


# ---- 3: invalid file ----

def test_invalid_extension_is_rejected(pipeline):
    with pytest.raises(RAGIngestionError, match="Unsupported file type"):
        pipeline.ingest(WS, "malware.exe", b"MZ\x90\x00 not supported at all")


def test_content_not_matching_claimed_extension_is_rejected(pipeline):
    with pytest.raises(RAGIngestionError):
        pipeline.ingest(WS, "fake.pdf", b"MZ\x90\x00 this is not a pdf")


def test_empty_file_is_rejected(pipeline):
    with pytest.raises(RAGIngestionError, match="empty"):
        pipeline.ingest(WS, "empty.txt", b"")


def test_filename_without_extension_is_rejected(pipeline):
    with pytest.raises(RAGIngestionError):
        pipeline.ingest(WS, "no_extension", b"some text")


def test_path_traversal_filename_is_neutralized(pipeline):
    # secure_filename() strips path components; ingestion should succeed
    # using a sanitized name rather than writing outside the upload dir.
    doc = pipeline.ingest(WS, "../../etc/passwd.txt", make_txt_bytes("hello"))
    stored_path = pipeline._workspace_dir(WS) / doc.filename
    assert stored_path.exists()
    assert str(pipeline.upload_dir.resolve()) in str(stored_path.resolve())


# ---- 4: oversized file ----

def test_oversized_file_is_rejected(pipeline):
    too_big = b"x" * (pipeline.max_upload_bytes + 1)
    with pytest.raises(RAGIngestionError, match="too large"):
        pipeline.ingest(WS, "big.txt", too_big)


def test_file_at_exact_limit_is_accepted(pipeline):
    exactly_ok = b"x" * pipeline.max_upload_bytes
    doc = pipeline.ingest(WS, "exact.txt", exactly_ok)
    assert doc.size_bytes == pipeline.max_upload_bytes


# ---- 5: document retrieval ----

def test_document_retrieval_finds_relevant_chunk(pipeline):
    pipeline.ingest(WS, "policy.txt", make_txt_bytes(
        "Company Refund Policy. The refund period for all purchases is 30 days."
    ))
    results = pipeline.search(WS, "What is the refund period?")
    assert len(results) >= 1
    assert "refund" in results[0].text.lower()


# ---- 6: irrelevant question ----

def test_irrelevant_question_returns_no_results(pipeline):
    pipeline.ingest(WS, "policy.txt", make_txt_bytes(
        "Company Refund Policy. The refund period for all purchases is 30 days."
    ))
    results = pipeline.search(WS, "What is the airspeed velocity of an unladen swallow?")
    assert results == []


def test_search_with_no_documents_returns_empty(pipeline):
    assert pipeline.search(WS, "anything at all") == []


# ---- 7: citations ----

def test_citation_includes_page_number_for_pdf(pipeline):
    pdf_bytes = make_pdf_bytes(["Irrelevant filler page.", "The refund period is 30 days."])
    pipeline.ingest(WS, "policy.pdf", pdf_bytes)

    results = pipeline.search(WS, "What is the refund period?")
    assert len(results) >= 1
    assert results[0].document_name == "policy.pdf"
    assert results[0].page_number == 2


def test_citation_shows_document_name_only_when_no_page_info(pipeline):
    pipeline.ingest(WS, "notes.txt", make_txt_bytes("The refund period is 30 days per our notes."))
    results = pipeline.search(WS, "What is the refund period?")
    assert results[0].document_name == "notes.txt"
    assert results[0].page_number is None


# ---- 8: multiple documents ----

def test_multiple_documents_are_all_searchable_and_isolated_by_relevance(pipeline):
    pipeline.ingest(WS, "policy.txt", make_txt_bytes("The refund period is 30 days."))
    pipeline.ingest(WS, "resume.txt", make_txt_bytes("Skills include Python and LangChain integration work."))
    pipeline.ingest(WS, "notes.txt", make_txt_bytes("Meeting notes about the FastAPI microservice."))

    assert len(pipeline.list_documents(WS)) == 3

    refund_results = pipeline.search(WS, "refund period")
    assert refund_results[0].document_name == "policy.txt"

    langchain_results = pipeline.search(WS, "LangChain experience")
    assert langchain_results[0].document_name == "resume.txt"


def test_search_can_be_scoped_to_a_subset_of_documents(pipeline):
    doc1 = pipeline.ingest(WS, "policy.txt", make_txt_bytes("The refund period is 30 days."))
    pipeline.ingest(WS, "policy2.txt", make_txt_bytes("A different refund period of 90 days for premium members."))

    results = pipeline.search(WS, "refund period", document_ids=[doc1.id])
    assert all(r.document_id == doc1.id for r in results)


# ---- 9: document deletion ----

def test_document_deletion_removes_file_and_chunks(pipeline):
    doc = pipeline.ingest(WS, "policy.txt", make_txt_bytes("The refund period is 30 days."))
    stored_path = pipeline._workspace_dir(WS) / doc.filename

    assert pipeline.delete_document(WS, doc.id) is True
    assert pipeline.list_documents(WS) == []
    assert not stored_path.exists()
    assert pipeline.search(WS, "refund period") == []


def test_deleting_unknown_document_returns_false(pipeline):
    assert pipeline.delete_document(WS, "does-not-exist") is False


# ---- rollback on partial failure ----

def test_failed_ingestion_does_not_leave_orphaned_file(pipeline, monkeypatch):
    def boom(text):
        raise RuntimeError("simulated embedding failure")

    monkeypatch.setattr(pipeline.embedding_provider, "embed", boom)

    with pytest.raises(RuntimeError):
        pipeline.ingest(WS, "notes.txt", make_txt_bytes("some content that will fail to embed"))

    assert pipeline.list_documents(WS) == []
    workspace_dir = pipeline._workspace_dir(WS)
    assert not any(workspace_dir.iterdir()) if workspace_dir.exists() else True
