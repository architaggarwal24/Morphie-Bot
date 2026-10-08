"""Plain text loader. No real pages - the whole file is one LoadedPage."""

from __future__ import annotations

from .base import DocumentLoadError, DocumentLoader, LoadedPage


class TXTLoader(DocumentLoader):
    def load(self, file_bytes: bytes) -> list[LoadedPage]:
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                text = file_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise DocumentLoadError("Could not decode this file as text.")

        text = text.strip()
        if not text:
            raise DocumentLoadError("This text file is empty.")
        return [LoadedPage(page_number=None, text=text)]
