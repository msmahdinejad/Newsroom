"""Rendering tests — semantic chunking, HTML escaping, RTL-safe."""

from newsroom.delivery.render import (
    DEFAULT_CHUNK_SIZE,
    escape_html,
    format_link,
    render_chunks,
    render_report_html,
)


def test_escape_html_basic():
    assert escape_html("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"
    assert escape_html("a & b") == "a &amp; b"
    assert escape_html('"quotes"') == '"quotes"'


def test_escape_html_persian():
    text = "\u0627\u06cc\u0646 \u06cc\u06a9 \u0645\u062a\u0646 \u0641\u0627\u0631\u0633\u06cc \u0627\u0633\u062a"
    assert escape_html(text) == text


def test_escape_html_mixed():
    text = "\u0627\u062e\u0628\u0627\u0631 <script>alert(1)</script> \u0641\u0646\u0627\u0648\u0631\u06cc"
    escaped = escape_html(text)
    assert "<script>" not in escaped
    assert "\u0627\u062e\u0628\u0627\u0631" in escaped
    assert "\u0641\u0646\u0627\u0648\u0631\u06cc" in escaped


def test_format_link_safe():
    link = format_link("Google", "https://google.com")
    assert link == '<a href="https://google.com">Google</a>'


def test_format_link_escapes_text():
    link = format_link("<b>bold</b>", "https://example.com")
    assert "&lt;b&gt;bold&lt;/b&gt;" in link


def test_format_link_rejects_javascript():
    link = format_link("click", "javascript:alert(1)")
    assert "href" not in link
    assert "click" in link


def test_format_link_rejects_data():
    link = format_link("click", "data:text/html,<script>")
    assert "href" not in link


def test_render_chunks_short_single():
    text = "short message"
    assert render_chunks(text) == [text]


def test_render_chunks_empty():
    assert render_chunks("") == [""]


def test_render_chunks_multi_paragraph():
    para1 = "a" * 2000
    para2 = "b" * 2000
    para3 = "c" * 2000
    text = f"{para1}\n\n{para2}\n\n{para3}"
    chunks = render_chunks(text, max_size=2500)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 2500


def test_render_chunks_no_chunk_exceeds_default():
    text = "\n".join([f"line {i}" for i in range(1000)])
    chunks = render_chunks(text)
    for c in chunks:
        assert len(c) <= DEFAULT_CHUNK_SIZE


def test_render_chunks_preserves_paragraphs():
    """Paragraph boundaries are preferred as split points."""
    para1 = "headline\nexplanation"
    para2 = "second story\nsource link"
    text = f"{para1}\n\n{para2}"
    chunks = render_chunks(text, max_size=100)
    # With short text it's one chunk
    if len(chunks) == 1:
        assert para1 in chunks[0]
        assert para2 in chunks[0]


def test_render_chunks_headline_with_link_not_split():
    """Headline and its source link must not be in different chunks."""
    # Simulate a story: headline line + link line, as one paragraph
    story = "🔹 \u062e\u0628\u0631 \u0645\u0647\u0645\n🔗 https://example.com/story1"
    # Make it long enough to need chunking
    stories = "\n\n".join([story] * 50)
    chunks = render_chunks(stories, max_size=500)
    for c in chunks:
        # If a chunk contains the headline, it must also contain its link
        if "🔹 \u062e\u0628\u0631 \u0645\u0647\u0645" in c:
            assert "🔗 https://example.com/story1" in c


def test_render_report_html_escapes_content():
    """Report content with HTML chars is escaped."""
    content = "\u0627\u062e\u0628\u0627\u0631 <b>\u0645\u0647\u0645</b> & \u0641\u0646\u0627\u0648\u0631\u06cc"
    chunks = render_report_html(content)
    assert len(chunks) == 1
    assert "&lt;b&gt;" in chunks[0]
    assert "&amp;" in chunks[0]


def test_render_report_html_long_content():
    """Long report content is split into multiple chunks."""
    para = "\u0627\u06cc\u0646 \u06cc\u06a9 \u067e\u0627\u0631\u0627\u06af\u0631\u0627\u0641 \u0641\u0627\u0631\u0633\u06cc \u0627\u0633\u062a. " * 20  # ~640 chars
    text = "\n\n".join([para] * 20)  # ~12800 chars
    chunks = render_report_html(text)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= DEFAULT_CHUNK_SIZE


def test_render_chunks_deterministic_order():
    """Same input always produces same chunk sequence."""
    text = "\n\n".join([f"paragraph {i} " + "x" * 100 for i in range(20)])
    c1 = render_chunks(text, max_size=500)
    c2 = render_chunks(text, max_size=500)
    assert c1 == c2


def test_render_chunks_long_line_word_boundaries():
    """Very long single line split at word boundaries."""
    line = " ".join(["word"] * 500)
    chunks = render_chunks(line, max_size=500)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 500
    # No word should be split across chunks
    for c in chunks:
        for w in c.split(" "):
            assert w == "word" or w == ""


def test_default_chunk_size_below_platform_max():
    """Configurable chunk size must be below Telegram's 4096 max."""
    assert DEFAULT_CHUNK_SIZE < 4096
    assert DEFAULT_CHUNK_SIZE > 0
