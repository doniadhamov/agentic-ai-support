"""Parse uploaded files (PDF, DOCX, TXT) into ContentBlock lists."""

from __future__ import annotations

import io
from pathlib import Path

from loguru import logger

from src.ingestion.article_processor import ContentBlock

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def parse_file(filename: str, content: bytes) -> list[ContentBlock]:
    """Dispatch to the correct parser based on file extension.

    Args:
        filename: Original filename (used to detect format).
        content: Raw file bytes.

    Returns:
        Ordered list of :class:`ContentBlock` objects.

    Raises:
        ValueError: If the file extension is not supported.
    """
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(content)
    if ext == ".docx":
        return _parse_docx(content)
    if ext in {".txt", ".md"}:
        return _parse_text(content)
    raise ValueError(f"Unsupported file type: {ext}")


def _parse_pdf(content: bytes) -> list[ContentBlock]:
    """Extract text from a PDF, one ContentBlock per page."""
    import pymupdf

    blocks: list[ContentBlock] = []
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        for page_num, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                blocks.append(ContentBlock(text=text))
            else:
                logger.debug("PDF page {} is empty, skipping", page_num)
    logger.debug("Parsed PDF: {} non-empty page(s)", len(blocks))
    return blocks


def _parse_docx(content: bytes) -> list[ContentBlock]:
    """Extract text from a DOCX file, one ContentBlock per non-empty paragraph."""
    from docx import Document

    doc = Document(io.BytesIO(content))
    paragraphs: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            paragraphs.append(text)

    if not paragraphs:
        return []

    # Combine all paragraphs into a single block to let the chunker handle splitting
    combined = "\n\n".join(paragraphs)
    logger.debug("Parsed DOCX: {} paragraph(s)", len(paragraphs))
    return [ContentBlock(text=combined)]


def _parse_text(content: bytes) -> list[ContentBlock]:
    """Decode a plain text / Markdown file into a single ContentBlock."""
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    logger.debug("Parsed text file: {} chars", len(text))
    return [ContentBlock(text=text)]
