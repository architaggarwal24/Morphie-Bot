"""Generates real file bytes for RAG tests - a real PDF (via fpdf2, a
dev-only dependency) and a real DOCX (via python-docx, already a runtime
dependency), plus plain bytes for the text-based formats."""

import io
import json


def make_pdf_bytes(page_texts: list[str]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in page_texts:
        pdf.add_page()
        pdf.multi_cell(0, 10, text)
    return bytes(pdf.output())


def make_docx_bytes(paragraphs: list[str]) -> bytes:
    import docx

    document = docx.Document()
    for p in paragraphs:
        document.add_paragraph(p)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def make_txt_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def make_csv_bytes(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    header = ",".join(rows[0].keys())
    lines = [header] + [",".join(str(v) for v in row.values()) for row in rows]
    return ("\n".join(lines)).encode("utf-8")


def make_json_bytes(data) -> bytes:
    return json.dumps(data).encode("utf-8")
