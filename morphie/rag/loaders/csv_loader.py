"""CSV loader. Rows are converted into readable 'column: value' lines so
they chunk and embed sensibly as text; no real pages, so citations show
the document name."""

from __future__ import annotations

import csv
import io

from .base import DocumentLoadError, DocumentLoader, LoadedPage


class CSVLoader(DocumentLoader):
    def load(self, file_bytes: bytes) -> list[LoadedPage]:
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                text = file_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise DocumentLoadError("Could not decode this CSV file as text.")

        try:
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        except csv.Error as exc:
            raise DocumentLoadError(f"Could not parse this CSV file: {exc}") from exc

        if not rows:
            raise DocumentLoadError("This CSV file has no data rows.")

        lines = []
        for i, row in enumerate(rows, start=1):
            fields = "; ".join(f"{k}: {v}" for k, v in row.items() if k)
            lines.append(f"Row {i}: {fields}")

        return [LoadedPage(page_number=None, text="\n".join(lines))]
