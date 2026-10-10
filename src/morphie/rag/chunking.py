"""
Text chunking.

Word-boundary-respecting: chunks are built by packing whitespace-split
words up to `chunk_size` characters, and a chunk never splits a word in
half except in the unavoidable edge case where a single "word" (e.g. a
long URL) is itself longer than chunk_size.
"""

from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 150) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunk_size = max(50, chunk_size)
    chunk_overlap = max(0, min(chunk_overlap, chunk_size // 2))

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    i = 0

    while i < len(words):
        word = words[i]
        added_len = len(word) + (1 if current else 0)  # +1 for the joining space

        if current and current_len + added_len > chunk_size:
            chunks.append(" ".join(current))

            # Carry the trailing ~chunk_overlap characters of words into
            # the next chunk, so retrieval doesn't lose context right at
            # a chunk boundary.
            overlap_words: list[str] = []
            overlap_len = 0
            for w in reversed(current):
                extra = len(w) + (1 if overlap_words else 0)
                if overlap_len + extra > chunk_overlap:
                    break
                overlap_words.insert(0, w)
                overlap_len += extra

            # Guarantee progress: if nothing was trimmed from the carry-over
            # (the whole previous chunk fit inside the overlap budget), or
            # the word still won't fit even against the trimmed carry-over,
            # drop the carry-over entirely rather than retrying forever on
            # an unproductive loop. The next attempt then starts from an
            # empty chunk, where an oversized single word is simply
            # accepted as its own chunk (see module docstring).
            if len(overlap_words) == len(current) or overlap_len + added_len > chunk_size:
                current = []
                current_len = 0
            else:
                current = overlap_words
                current_len = overlap_len
            continue  # retry the same word against the (now smaller) current chunk

        current.append(word)
        current_len += added_len
        i += 1

    if current:
        chunks.append(" ".join(current))

    return chunks
