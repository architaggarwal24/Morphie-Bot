"""
Loader registry.

`get_loader_for(extension)` is the single place that maps a file
extension to its DocumentLoader. Adding a new supported format later
means writing one new loader module and adding one line here - nothing
else in the RAG pipeline needs to change.

`check_content_matches_extension` is the "don't trust the extension
alone" safeguard for binary formats with a clear signature (PDF, DOCX).
Text-based formats (txt/csv/json) are validated by their loader actually
parsing the content successfully instead - a mismatched file simply
fails to parse as that format.
"""

from __future__ import annotations

import io
import zipfile

from .base import DocumentLoadError, DocumentLoader, LoadedPage
from .csv_loader import CSVLoader
from .docx_loader import DOCXLoader
from .json_loader import JSONLoader
from .pdf_loader import PDFLoader
from .txt_loader import TXTLoader

_LOADERS: dict[str, DocumentLoader] = {
    "pdf": PDFLoader(),
    "txt": TXTLoader(),
    "docx": DOCXLoader(),
    "csv": CSVLoader(),
    "json": JSONLoader(),
}

SUPPORTED_EXTENSIONS = frozenset(_LOADERS.keys())

# A .docx is a zip, and a tiny zip can expand to gigabytes. These limits are
# checked from the archive's own directory *before* anything is unpacked.
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 5000


def _check_zip_is_reasonable(file_bytes: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile:
        raise DocumentLoadError("This file's content doesn't look like a real Word document.") from None
    if len(entries) > MAX_ZIP_ENTRIES or sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
        raise DocumentLoadError("This document is too large once unpacked, so it can't be processed.")


def get_loader_for(extension: str) -> DocumentLoader:
    loader = _LOADERS.get(extension.lower().lstrip("."))
    if loader is None:
        raise DocumentLoadError(
            f"Unsupported file type '.{extension}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    return loader


def check_content_matches_extension(extension: str, file_bytes: bytes) -> None:
    """Raises DocumentLoadError on an obvious mismatch between the
    claimed extension and the file's actual bytes - e.g. a renamed
    executable pretending to be a PDF."""
    head = file_bytes[:8]
    looks_like_pdf = head.startswith(b"%PDF-")
    looks_like_zip = head.startswith(b"PK\x03\x04")  # docx (and any zip-based format)

    extension = extension.lower().lstrip(".")
    if extension == "pdf" and not looks_like_pdf:
        raise DocumentLoadError("This file's content doesn't look like a real PDF.")
    if extension == "docx":
        if not looks_like_zip:
            raise DocumentLoadError("This file's content doesn't look like a real Word document.")
        _check_zip_is_reasonable(file_bytes)
    if extension in ("txt", "csv", "json") and (looks_like_pdf or looks_like_zip):
        raise DocumentLoadError(f"This file's content doesn't look like a real .{extension} file.")


__all__ = [
    "DocumentLoader",
    "DocumentLoadError",
    "LoadedPage",
    "SUPPORTED_EXTENSIONS",
    "get_loader_for",
    "check_content_matches_extension",
]
