"""PDF loader. Text extraction only - scanned/image-only PDFs with no
embedded text layer will yield empty pages (no OCR is performed)."""

from __future__ import annotations

import io
import logging

from .base import DocumentLoadError, DocumentLoader, LoadedPage


logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 1000  # text extraction is synchronous; bound the work a single upload can cause


class PDFLoader(DocumentLoader):
    def load(self, file_bytes: bytes) -> list[LoadedPage]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise DocumentLoadError("PDF support is not installed (pypdf).") from exc

        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            if reader.is_encrypted:
                raise DocumentLoadError("This PDF is password-protected and can't be read.")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise DocumentLoadError(f"This PDF is too large: it has more than {MAX_PDF_PAGES} pages.")
            pages = []
            for i, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if text:
                    pages.append(LoadedPage(page_number=i, text=text))
            return pages
        except DocumentLoadError:
            raise
        except Exception as exc:  # noqa: BLE001 - PdfReadError and anything else the parser throws
            logger.warning("PDF could not be parsed (%s).", type(exc).__name__)
            raise DocumentLoadError("Could not read this PDF. It may be damaged or password-protected.") from exc
