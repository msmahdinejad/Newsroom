"""Telegram-safe report rendering — semantic chunking, HTML escaping, RTL-safe.

Parse mode: HTML. User/source-controlled text is HTML-escaped to prevent
entity-breakage. Semantic units (headline + explanation, story + links)
are never split across chunks.
"""

from __future__ import annotations

import html
import re

from newsroom.config import settings

# Configurable safe chunk size below platform max (4096)
DEFAULT_CHUNK_SIZE = settings.telegram_chunk_size

# Persian/RTL marker — Telegram handles RTL automatically based on content
# but we add ZWJ to ensure proper joining for mixed content
RTL_MARK = "\u200d"


def escape_html(text: str) -> str:
    """Escape user/source-controlled text for HTML parse mode."""
    return html.escape(text, quote=False)


def _is_url_safe(url: str) -> bool:
    """Basic URL safety check — prevent javascript: or data: schemes."""
    lower = url.lower().strip()
    if lower.startswith(("http://", "https://")):
        return True
    # telegram supports bare links and t.me links
    return bool(lower.startswith("t.me/"))


def format_link(text: str, url: str) -> str:
    """Format a safe HTML link. Escapes text, validates URL."""
    safe_text = escape_html(text)
    if _is_url_safe(url):
        safe_url = escape_html(url)
        return f'<a href="{safe_url}">{safe_text}</a>'
    return safe_text


def _split_by_paragraphs(text: str, max_size: int) -> list[str]:
    """Split into paragraphs first (double-newline boundaries)."""
    paragraphs = re.split(r"\n\n+", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for \n\n
        if current_len + para_len > max_size and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0

        if para_len > max_size:
            # Paragraph itself is too long — split by lines
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            line_chunks = _split_by_lines(para, max_size)
            # All but last go as chunks; last stays as current
            for lc in line_chunks[:-1]:
                chunks.append(lc)
            if line_chunks:
                current = [line_chunks[-1]]
                current_len = len(line_chunks[-1])
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _split_by_lines(text: str, max_size: int) -> list[str]:
    """Split a long paragraph by single-newline boundaries."""
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_size and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0

        if line_len > max_size:
            # Single line exceeds max — split by words, never break a word
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            word_chunks = _split_by_words(line, max_size)
            for wc in word_chunks[:-1]:
                chunks.append(wc)
            if word_chunks:
                current = [word_chunks[-1]]
                current_len = len(word_chunks[-1])
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def _split_by_words(text: str, max_size: int) -> list[str]:
    """Split a very long line by word boundaries."""
    words = text.split(" ")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in words:
        word_len = len(word) + 1
        if current_len + word_len > max_size and current:
            chunks.append(" ".join(current))
            current = []
            current_len = 0
        current.append(word)
        current_len += word_len

    if current:
        chunks.append(" ".join(current))

    return chunks


def render_chunks(text: str, max_size: int | None = None) -> list[str]:
    """Split report text into Telegram-safe HTML chunks.

    Semantic splitting: paragraphs → lines → words.
    Headlines stay with their explanations because they're in the same paragraph.
    Stories stay with their source links because links follow the headline.
    """
    max_len = max_size or DEFAULT_CHUNK_SIZE
    if not text:
        return [""]
    if len(text) <= max_len:
        return [text]
    return _split_by_paragraphs(text, max_len)


def render_report_html(report_content: str) -> list[str]:
    """Take raw report content and return HTML-safe chunks.

    The editorial module produces plain text with emojis and URLs.
    We escape HTML-special characters to prevent entity-breakage.
    """
    escaped = escape_html(report_content)
    return render_chunks(escaped, DEFAULT_CHUNK_SIZE)
