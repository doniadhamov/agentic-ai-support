"""Parse Zendesk article HTML into an ordered sequence of text/image blocks."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag
from loguru import logger


@dataclass
class ContentBlock:
    """A single content block extracted from article HTML.

    Either ``text`` or ``image_url`` is set (never both, never neither).
    """

    text: str | None = None
    image_url: str | None = None

    @property
    def is_text(self) -> bool:
        return self.text is not None

    @property
    def is_image(self) -> bool:
        return self.image_url is not None


def process_article_html(html: str) -> list[ContentBlock]:
    """Convert article HTML to an ordered list of :class:`ContentBlock` objects.

    Text between images is collected as a single text block; each ``<img>`` tag
    produces a separate image block, preserving document order.

    Args:
        html: Raw HTML body from Zendesk article.

    Returns:
        Ordered list of ``ContentBlock`` objects (text and/or image blocks).
    """
    soup = BeautifulSoup(html, "lxml")
    blocks: list[ContentBlock] = []
    pending_text: list[str] = []

    def flush_text() -> None:
        combined = " ".join(pending_text).strip()
        if combined:
            blocks.append(ContentBlock(text=combined))
        pending_text.clear()

    def walk(node: Tag | NavigableString) -> None:
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                pending_text.append(text)
            return

        if node.name == "img":
            src = node.get("src") or node.get("data-src")
            if src:
                flush_text()
                blocks.append(ContentBlock(image_url=str(src)))
            return

        # Skip script / style nodes entirely
        if node.name in {"script", "style"}:
            return

        for child in node.children:
            walk(child)  # type: ignore[arg-type]

        # Add a space after block-level elements to keep words separated
        if node.name in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "div"}:
            pending_text.append(" ")

    walk(soup)
    flush_text()

    logger.debug(f"Extracted {len(blocks)} content blocks from article HTML")
    return blocks
