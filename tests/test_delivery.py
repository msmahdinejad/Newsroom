"""Test delivery — message chunking (4096 limit, semantic unit preservation),
chat ID hashing. Uses render module functions.
"""

import hashlib

from newsroom.delivery.render import DEFAULT_CHUNK_SIZE, render_chunks
from newsroom.delivery.telegram import TelegramDelivery

# ── Chat ID hashing ─────────────────────────────────────────────

def test_hash_chat_is_sha256_prefix():
    chat_id = "123456789"
    expected = hashlib.sha256(chat_id.encode()).hexdigest()[:16]
    td = TelegramDelivery.__new__(TelegramDelivery)
    assert td._hash_chat(chat_id) == expected


def test_hash_chat_deterministic():
    td = TelegramDelivery.__new__(TelegramDelivery)
    h1 = td._hash_chat("123")
    h2 = td._hash_chat("123")
    assert h1 == h2


def test_hash_chat_different_ids_different_hash():
    td = TelegramDelivery.__new__(TelegramDelivery)
    assert td._hash_chat("123") != td._hash_chat("456")


def test_hash_chat_length():
    td = TelegramDelivery.__new__(TelegramDelivery)
    assert len(td._hash_chat("test")) == 16


# ── Message chunking (delegates to render module) ────────────────────────────

def test_split_short_message_single_chunk():
    text = "short message"
    chunks = render_chunks(text)
    assert chunks == [text]


def test_split_preserves_line_boundaries():
    line = "a" * 100
    text = "\n".join([line] * 50)
    chunks = render_chunks(text, max_size=500)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 500


def test_split_no_chunk_exceeds_limit():
    text = "\n".join(["line " + str(i) for i in range(1000)])
    chunks = render_chunks(text)
    assert all(len(c) <= DEFAULT_CHUNK_SIZE for c in chunks)


def test_split_exact_limit_single_chunk():
    text = "a" * DEFAULT_CHUNK_SIZE
    chunks = render_chunks(text)
    assert chunks == [text]


def test_split_just_over_limit_two_chunks():
    text = "a" * 3000 + "\n" + "b" * 1000
    chunks = render_chunks(text)
    assert len(chunks) >= 2
    assert all(len(c) <= DEFAULT_CHUNK_SIZE for c in chunks)


def test_split_long_line_word_boundaries():
    word = "hello"
    text = " ".join([word] * 200)
    chunks = render_chunks(text, max_size=500)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 500


def test_split_preserves_paragraph_semantic_units():
    para1 = "paragraph one " + "x " * 2000
    para2 = "paragraph two " + "y " * 2000
    text = para1 + "\n\n" + para2
    chunks = render_chunks(text, max_size=3800)
    assert len(chunks) >= 2
    assert "paragraph one" in chunks[0]


def test_split_empty_text():
    assert render_chunks("") == [""]


def test_split_preserves_content():
    words = [f"word{i}" for i in range(500)]
    text = "\n".join(words)
    chunks = render_chunks(text)
    all_text = "\n".join(chunks)
    for w in words:
        assert w in all_text


def test_default_chunk_size_constant():
    assert DEFAULT_CHUNK_SIZE == 3800
