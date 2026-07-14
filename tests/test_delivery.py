"""Test delivery — message chunking (4096 limit, semantic unit preservation),
chat ID hashing."""

import hashlib

import pytest

from newsroom.delivery.telegram import MAX_MSG_LEN, TelegramDelivery


# ── Chat ID hashing ─────────────────────────────────────────────

def test_hash_chat_is_sha256_prefix():
    """_hash_chat returns first 16 chars of SHA-256 hex."""
    chat_id = "123456789"
    expected = hashlib.sha256(chat_id.encode()).hexdigest()[:16]
    assert TelegramDelivery._hash_chat(None, chat_id) == expected


def test_hash_chat_deterministic():
    """Same chat ID → same hash."""
    h1 = TelegramDelivery._hash_chat(None, "123")
    h2 = TelegramDelivery._hash_chat(None, "123")
    assert h1 == h2


def test_hash_chat_different_ids_different_hash():
    assert TelegramDelivery._hash_chat(None, "123") != TelegramDelivery._hash_chat(None, "456")


def test_hash_chat_length():
    assert len(TelegramDelivery._hash_chat(None, "test")) == 16


# ── Message chunking ─────────────────────────────────────────────

def test_split_short_message_single_chunk():
    """Text under limit → single chunk."""
    td = TelegramDelivery.__new__(TelegramDelivery)
    text = "short message"
    chunks = td._split_message(text)
    assert chunks == [text]


def test_split_preserves_line_boundaries():
    """Chunking splits on newlines, not mid-line."""
    td = TelegramDelivery.__new__(TelegramDelivery)
    # Each line short, but combined exceeds limit
    line = "a" * 100
    text = "\n".join([line] * 50)  # 50 lines of 100 chars = ~5050 chars
    chunks = td._split_message(text, max_length=500)
    assert len(chunks) >= 2
    # No chunk should exceed max length
    for chunk in chunks:
        assert len(chunk) <= 500
    # Lines should be intact within chunks
    for chunk in chunks:
        for line in chunk.split("\n"):
            assert line == "" or len(line) == 100


def test_split_no_chunk_exceeds_limit():
    """Every chunk must be ≤ 4096."""
    td = TelegramDelivery.__new__(TelegramDelivery)
    text = "\n".join(["line " + str(i) for i in range(1000)])  # ~6000 chars
    chunks = td._split_message(text)
    assert all(len(c) <= MAX_MSG_LEN for c in chunks)


def test_split_exact_limit_single_chunk():
    """Text exactly at limit → single chunk."""
    td = TelegramDelivery.__new__(TelegramDelivery)
    text = "a" * MAX_MSG_LEN
    chunks = td._split_message(text)
    assert chunks == [text]


def test_split_just_over_limit_two_chunks():
    """Text 1 char over limit with newlines → 2 chunks."""
    td = TelegramDelivery.__new__(TelegramDelivery)
    # Use two lines so the splitter can break at newline boundary
    text = "a" * 4000 + "\n" + "b" * 100  # 4101 chars total
    chunks = td._split_message(text)
    assert len(chunks) >= 2
    assert all(len(c) <= MAX_MSG_LEN for c in chunks)


def test_split_long_line_word_boundaries():
    """Very long single line → split into chunks, no chunk exceeds limit."""
    td = TelegramDelivery.__new__(TelegramDelivery)
    word = "hello"
    text = " ".join([word] * 200)  # one line ~1000 chars
    chunks = td._split_message(text, max_length=500)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 500


def test_split_preserves_paragraph_semantic_units():
    """Paragraphs (double newlines) preferred as split points."""
    td = TelegramDelivery.__new__(TelegramDelivery)
    para1 = "paragraph one " + "x " * 2000  # ~4014 chars
    para2 = "paragraph two " + "y " * 2000
    text = para1 + "\n\n" + para2
    chunks = td._split_message(text, max_length=4096)
    assert len(chunks) >= 2
    # para1 content in first chunk
    assert "paragraph one" in chunks[0]


def test_split_empty_text():
    td = TelegramDelivery.__new__(TelegramDelivery)
    assert td._split_message("") == [""]


def test_split_preserves_content():
    """Concatenating chunks (with newlines) preserves all text words."""
    td = TelegramDelivery.__new__(TelegramDelivery)
    words = [f"word{i}" for i in range(500)]
    text = "\n".join(words)
    chunks = td._split_message(text)
    # Every word must appear in some chunk
    all_text = "\n".join(chunks)
    for w in words:
        assert w in all_text


def test_max_msg_len_constant():
    """MAX_MSG_LEN is Telegram's 4096 char limit."""
    assert MAX_MSG_LEN == 4096
