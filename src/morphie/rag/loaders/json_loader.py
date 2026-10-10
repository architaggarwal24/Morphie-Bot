"""JSON loader. Pretty-prints the parsed structure back into readable
text; no real pages, so citations show the document name."""

from __future__ import annotations

import json

from .base import DocumentLoadError, DocumentLoader, LoadedPage


class JSONLoader(DocumentLoader):
    def load(self, file_bytes: bytes) -> list[LoadedPage]:
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentLoadError("Could not decode this JSON file as UTF-8.") from exc

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DocumentLoadError(f"This file is not valid JSON: {exc}") from exc

        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        if not pretty.strip():
            raise DocumentLoadError("This JSON file has no content.")
        return [LoadedPage(page_number=None, text=pretty)]
