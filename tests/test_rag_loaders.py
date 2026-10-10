import pytest

from morphie.rag.loaders import (
    SUPPORTED_EXTENSIONS,
    DocumentLoadError,
    check_content_matches_extension,
    get_loader_for,
)
from morphie.rag.loaders.csv_loader import CSVLoader
from morphie.rag.loaders.docx_loader import DOCXLoader
from morphie.rag.loaders.json_loader import JSONLoader
from morphie.rag.loaders.pdf_loader import PDFLoader
from morphie.rag.loaders.txt_loader import TXTLoader

from fixtures import make_csv_bytes, make_docx_bytes, make_json_bytes, make_pdf_bytes, make_txt_bytes


def test_supported_extensions():
    assert SUPPORTED_EXTENSIONS == frozenset({"pdf", "txt", "docx", "csv", "json"})


def test_get_loader_for_unsupported_extension_raises():
    with pytest.raises(DocumentLoadError):
        get_loader_for("exe")


# ---- PDF ----

def test_pdf_loader_extracts_text_with_page_numbers():
    pdf_bytes = make_pdf_bytes(["First page about refunds.", "Second page about shipping."])
    pages = PDFLoader().load(pdf_bytes)

    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert "refunds" in pages[0].text
    assert pages[1].page_number == 2
    assert "shipping" in pages[1].text


def test_pdf_loader_rejects_garbage_bytes():
    with pytest.raises(DocumentLoadError):
        PDFLoader().load(b"not a real pdf at all")


# ---- TXT ----

def test_txt_loader_returns_single_page_with_no_page_number():
    pages = TXTLoader().load(make_txt_bytes("Meeting notes about FastAPI."))
    assert len(pages) == 1
    assert pages[0].page_number is None
    assert "FastAPI" in pages[0].text


def test_txt_loader_rejects_empty_file():
    with pytest.raises(DocumentLoadError):
        TXTLoader().load(b"")


def test_txt_loader_handles_latin1_fallback():
    text_bytes = "café".encode("latin-1")
    pages = TXTLoader().load(text_bytes)
    assert "caf" in pages[0].text


# ---- DOCX ----

def test_docx_loader_extracts_paragraphs():
    docx_bytes = make_docx_bytes(["Resume of Jane Doe", "Skills: Python, LangChain, distributed systems."])
    pages = DOCXLoader().load(docx_bytes)
    assert len(pages) == 1
    assert pages[0].page_number is None
    assert "LangChain" in pages[0].text


def test_docx_loader_rejects_non_docx_bytes():
    with pytest.raises(DocumentLoadError):
        DOCXLoader().load(b"not a real docx")


# ---- CSV ----

def test_csv_loader_converts_rows_to_readable_text():
    csv_bytes = make_csv_bytes([{"name": "Alice", "role": "Engineer"}, {"name": "Bob", "role": "Designer"}])
    pages = CSVLoader().load(csv_bytes)
    assert len(pages) == 1
    assert pages[0].page_number is None
    assert "Alice" in pages[0].text and "Engineer" in pages[0].text
    assert "Bob" in pages[0].text and "Designer" in pages[0].text


def test_csv_loader_rejects_empty_csv():
    with pytest.raises(DocumentLoadError):
        CSVLoader().load(b"")


# ---- JSON ----

def test_json_loader_pretty_prints_content():
    pages = JSONLoader().load(make_json_bytes({"project": "Morphie", "status": "in progress"}))
    assert len(pages) == 1
    assert pages[0].page_number is None
    assert "Morphie" in pages[0].text


def test_json_loader_rejects_invalid_json():
    with pytest.raises(DocumentLoadError):
        JSONLoader().load(b"{not valid json")


# ---- content-vs-extension validation (the "don't trust the extension" safeguard) ----

def test_content_check_accepts_real_pdf():
    check_content_matches_extension("pdf", make_pdf_bytes(["hello"]))  # must not raise


def test_content_check_rejects_fake_pdf():
    with pytest.raises(DocumentLoadError):
        check_content_matches_extension("pdf", b"MZ\x90\x00 this is an exe, not a pdf")


def test_content_check_accepts_real_docx():
    check_content_matches_extension("docx", make_docx_bytes(["hello"]))  # must not raise


def test_content_check_rejects_fake_docx():
    with pytest.raises(DocumentLoadError):
        check_content_matches_extension("docx", b"just some plain text, not a zip")


def test_content_check_rejects_binary_pretending_to_be_text():
    pdf_bytes = make_pdf_bytes(["hello"])
    for ext in ("txt", "csv", "json"):
        with pytest.raises(DocumentLoadError):
            check_content_matches_extension(ext, pdf_bytes)
