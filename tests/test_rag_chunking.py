from morphie.rag.chunking import chunk_text


def test_empty_text_yields_no_chunks():
    assert chunk_text("", 1000, 150) == []


def test_short_text_yields_one_chunk():
    chunks = chunk_text("Just a short sentence.", 1000, 150)
    assert chunks == ["Just a short sentence."]


def test_chunking_never_splits_a_word():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)

    all_words = set(text.split())
    for chunk in chunks:
        for w in chunk.split():
            assert w in all_words  # every "word" in a chunk is an intact original word


def test_chunk_sizes_stay_close_to_configured_limit():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 110 for c in chunks)  # small slack for the last word that tips it over


def test_consecutive_chunks_overlap():
    text = " ".join(f"w{i}" for i in range(60))
    chunks = chunk_text(text, chunk_size=50, chunk_overlap=15)

    first_words = chunks[0].split()
    second_words = chunks[1].split()
    overlap = set(first_words) & set(second_words)
    assert len(overlap) > 0  # some tail words repeat at the start of the next chunk


def test_oversized_single_word_does_not_hang_and_gets_its_own_chunk():
    huge_word = "x" * 5000
    chunks = chunk_text(f"short {huge_word} short", chunk_size=100, chunk_overlap=20)
    assert chunks == ["short", huge_word, "short"]


def test_many_oversized_words_in_a_row_do_not_hang():
    text = " ".join("y" * 200 for _ in range(6))
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
    assert len(chunks) == 6


def test_chunk_overlap_is_clamped_below_chunk_size():
    # chunk_overlap >= chunk_size would be a pathological config; make sure
    # it can't cause a hang or a nonsensical result.
    text = " ".join(f"word{i}" for i in range(200))
    chunks = chunk_text(text, chunk_size=50, chunk_overlap=500)
    assert len(chunks) > 1
