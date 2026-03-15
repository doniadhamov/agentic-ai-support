"""Unit tests for ArticleProcessor — HTML to content blocks, image extraction."""

from __future__ import annotations

from src.ingestion.article_processor import ContentBlock, process_article_html


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def test_plain_text_paragraph() -> None:
    blocks = process_article_html("<p>Hello world</p>")
    assert len(blocks) == 1
    assert blocks[0].is_text
    assert "Hello world" in blocks[0].text


def test_multiple_paragraphs() -> None:
    html = "<p>First</p><p>Second</p>"
    blocks = process_article_html(html)
    assert len(blocks) == 1  # adjacent text merges into one block
    assert "First" in blocks[0].text
    assert "Second" in blocks[0].text


def test_nested_tags_extracted() -> None:
    html = "<div><p>Inside a <strong>div</strong></p></div>"
    blocks = process_article_html(html)
    assert len(blocks) == 1
    assert "Inside a" in blocks[0].text
    assert "div" in blocks[0].text


def test_empty_html_returns_empty() -> None:
    assert process_article_html("") == []


def test_whitespace_only_html_returns_empty() -> None:
    assert process_article_html("   ") == []


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------


def test_single_image() -> None:
    html = '<p>Text</p><img src="https://example.com/img.png"/><p>More</p>'
    blocks = process_article_html(html)
    images = [b for b in blocks if b.is_image]
    assert len(images) == 1
    assert images[0].image_url == "https://example.com/img.png"


def test_image_with_data_src() -> None:
    html = '<img data-src="https://example.com/lazy.png"/>'
    blocks = process_article_html(html)
    assert len(blocks) == 1
    assert blocks[0].is_image
    assert blocks[0].image_url == "https://example.com/lazy.png"


def test_image_without_src_skipped() -> None:
    html = "<img alt='no source'/>"
    blocks = process_article_html(html)
    assert all(not b.is_image for b in blocks)


def test_multiple_images_interleaved_with_text() -> None:
    html = (
        "<p>A</p>"
        '<img src="https://example.com/1.png"/>'
        "<p>B</p>"
        '<img src="https://example.com/2.png"/>'
        "<p>C</p>"
    )
    blocks = process_article_html(html)
    images = [b for b in blocks if b.is_image]
    texts = [b for b in blocks if b.is_text]
    assert len(images) == 2
    assert len(texts) == 3


# ---------------------------------------------------------------------------
# Document order preserved
# ---------------------------------------------------------------------------


def test_order_preserved() -> None:
    html = (
        "<p>Before</p>"
        '<img src="https://example.com/mid.png"/>'
        "<p>After</p>"
    )
    blocks = process_article_html(html)
    assert blocks[0].is_text
    assert blocks[1].is_image
    assert blocks[2].is_text


# ---------------------------------------------------------------------------
# Script/style excluded
# ---------------------------------------------------------------------------


def test_script_tags_excluded() -> None:
    html = "<p>Visible</p><script>alert('x')</script>"
    blocks = process_article_html(html)
    assert len(blocks) == 1
    assert "alert" not in blocks[0].text


def test_style_tags_excluded() -> None:
    html = "<p>Visible</p><style>body{color:red}</style>"
    blocks = process_article_html(html)
    assert len(blocks) == 1
    assert "color" not in blocks[0].text


# ---------------------------------------------------------------------------
# ContentBlock properties
# ---------------------------------------------------------------------------


def test_text_block_properties() -> None:
    b = ContentBlock(text="hello")
    assert b.is_text is True
    assert b.is_image is False


def test_image_block_properties() -> None:
    b = ContentBlock(image_url="https://example.com/img.png")
    assert b.is_image is True
    assert b.is_text is False
