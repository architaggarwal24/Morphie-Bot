"""
Document loader interface.

Every supported file type implements DocumentLoader: given validated
bytes, return the extracted text as a list of pages. Non-paginated
formats (txt, csv, json, docx) return a single LoadedPage with
page_number=None - callers show the document name instead of a page
number for citations, per the RAG spec.

Adding a new format later means writing one new loader module here and
registering it in loaders/__init__.py - nothing else in the RAG pipeline
needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LoadedPage:
    page_number: int | None  # 1-indexed; None when the format has no real pages
    text: str


class DocumentLoadError(Exception):
    """Raised when a file's content doesn't actually match its claimed
    type, or can't be parsed - never lets a bad file crash ingestion."""


class DocumentLoader(ABC):
    @abstractmethod
    def load(self, file_bytes: bytes) -> list[LoadedPage]:
        """Extract text from raw file bytes. Raises DocumentLoadError on
        anything that isn't valid content for this loader."""
