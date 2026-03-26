"""Unit tests for format_reply() — MarkdownV2 conversion, screenshot stripping,
source links, 4096-char truncation, plain-text fallback."""

from __future__ import annotations

from src.agent.schemas import AgentOutput, KnowledgeSource, MessageCategory
from src.telegram.formatter import _MAX_LEN, format_reply

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _output(
    answer: str = "",
    follow_up: str = "",
    needs_escalation: bool = False,
    escalation_reason: str = "",
    sources: list[KnowledgeSource] | None = None,
) -> AgentOutput:
    return AgentOutput(
        category=MessageCategory.SUPPORT_QUESTION,
        should_reply=True,
        answer=answer,
        follow_up_question=follow_up,
        needs_escalation=needs_escalation,
        escalation_reason=escalation_reason,
        knowledge_sources_used=sources or [],
    )


# ---------------------------------------------------------------------------
# Basic answer
# ---------------------------------------------------------------------------


def test_plain_answer() -> None:
    result = format_reply(_output(answer="Hello world"))
    assert "Hello world" in result


def test_answer_with_doc_source_link() -> None:
    src = KnowledgeSource(
        type="documentation", title="Guide", id="1", url="https://example.com/guide"
    )
    result = format_reply(_output(answer="See the guide.", sources=[src]))
    assert "For more information" in result
    # URL is inside a MarkdownV2 escaped string, so check the domain is present
    assert "example" in result
    assert "guide" in result


def test_non_doc_source_omitted() -> None:
    src = KnowledgeSource(type="approved_memory", title="Q&A", id="2", url="https://example.com/qa")
    result = format_reply(_output(answer="Answer here.", sources=[src]))
    assert "For more information" not in result


# ---------------------------------------------------------------------------
# Follow-up question (no answer)
# ---------------------------------------------------------------------------


def test_follow_up_only() -> None:
    result = format_reply(_output(follow_up="Which account?"))
    assert "Which account" in result


def test_answer_with_follow_up() -> None:
    result = format_reply(_output(answer="Try this.", follow_up="Did that help?"))
    assert "Try this" in result
    assert "Did that help" in result


# ---------------------------------------------------------------------------
# Fallback (no answer, no follow-up, no escalation)
# ---------------------------------------------------------------------------


def test_fallback_message() -> None:
    result = format_reply(_output())
    assert "could not find" in result.lower() or "rephrasing" in result.lower()


# ---------------------------------------------------------------------------
# Screenshot stripping
# ---------------------------------------------------------------------------


def test_screenshot_stripped() -> None:
    answer = "Step 1\nscreenshot(https://img.example.com/shot.png)\nStep 2"
    result = format_reply(_output(answer=answer))
    assert "screenshot" not in result.lower()
    assert "Step 1" in result
    assert "Step 2" in result


def test_multiple_screenshots_stripped() -> None:
    answer = "A\nscreenshot(https://a.png)\nB\nscreenshot(http://b.png)\nC"
    result = format_reply(_output(answer=answer))
    assert "screenshot" not in result
    assert "A" in result
    assert "C" in result


# ---------------------------------------------------------------------------
# MarkdownV2 conversion
# ---------------------------------------------------------------------------


def test_bold_converted() -> None:
    result = format_reply(_output(answer="**important**"))
    assert "*important*" in result


def test_italic_asterisk_converted() -> None:
    result = format_reply(_output(answer="*note*"))
    assert "_note_" in result


def test_heading_becomes_bold() -> None:
    result = format_reply(_output(answer="## Settings"))
    assert "*Settings*" in result


def test_code_block_preserved() -> None:
    result = format_reply(_output(answer="Use:\n```\ncommand\n```"))
    assert "```" in result
    assert "command" in result


def test_inline_code_preserved() -> None:
    result = format_reply(_output(answer="Run `pip install`."))
    assert "`pip install`" in result


def test_link_converted() -> None:
    result = format_reply(_output(answer="See [docs](https://example.com)."))
    assert "[docs](https://example.com)" in result


def test_strikethrough_converted() -> None:
    result = format_reply(_output(answer="~~old~~"))
    assert "~old~" in result


def test_bold_italic_converted() -> None:
    result = format_reply(_output(answer="***both***"))
    # Should contain both bold (*) and italic (_) markers
    assert "*" in result
    assert "_" in result


# ---------------------------------------------------------------------------
# Special character escaping
# ---------------------------------------------------------------------------


def test_special_chars_escaped() -> None:
    result = format_reply(_output(answer="Price is 10.5 + tax!"))
    assert "\\." in result
    assert "\\+" in result
    assert "\\!" in result


# ---------------------------------------------------------------------------
# 4096-char truncation
# ---------------------------------------------------------------------------


def test_truncation_at_max_length() -> None:
    long_answer = "A" * 5000
    result = format_reply(_output(answer=long_answer))
    assert len(result) <= _MAX_LEN
    assert result.endswith("…")


def test_short_answer_not_truncated() -> None:
    result = format_reply(_output(answer="Short"))
    assert len(result) <= _MAX_LEN
    assert "…" not in result


# ---------------------------------------------------------------------------
# Phase 3 — Formatter edge cases
# ---------------------------------------------------------------------------


# --- 3.1 Nested Markdown formatting ----------------------------------------


def test_triple_asterisk_bold_italic() -> None:
    result = format_reply(_output(answer="***important***"))
    # Must contain both bold (*) and italic (_) markers
    assert "*" in result
    assert "_" in result
    assert "important" in result


def test_triple_underscore_bold_italic() -> None:
    result = format_reply(_output(answer="___crucial___"))
    assert "*" in result
    assert "_" in result
    assert "crucial" in result


def test_bold_wrapping_italic() -> None:
    """**_text_** → bold + italic."""
    result = format_reply(_output(answer="**_mixed_**"))
    assert "*" in result
    assert "_" in result
    assert "mixed" in result


def test_italic_wrapping_bold() -> None:
    """_**text**_ → italic + bold."""
    result = format_reply(_output(answer="_**nested**_"))
    assert "*" in result
    assert "_" in result
    assert "nested" in result


# --- 3.2 Code blocks with language identifiers ----------------------------


def test_code_block_with_language() -> None:
    result = format_reply(_output(answer="Example:\n```python\nprint('hi')\n```"))
    assert "```python" in result
    assert "print('hi')" in result


def test_code_block_language_no_newline() -> None:
    """Code block where lang identifier is followed by space, not newline."""
    result = format_reply(_output(answer="Run:\n```bash echo hello```"))
    assert "```bash" in result
    assert "echo hello" in result


def test_code_block_without_language() -> None:
    """Code blocks without a language identifier should still work."""
    result = format_reply(_output(answer="Use:\n```\ncommand\n```"))
    assert "```" in result
    assert "command" in result


def test_code_block_content_not_escaped() -> None:
    """Special chars inside code blocks should NOT be escaped."""
    result = format_reply(_output(answer="```python\nx = 1 + 2\n```"))
    # The + inside a code block should not be escaped
    assert "1 + 2" in result


# --- 3.3 Links with special characters in URLs ----------------------------


def test_link_with_parentheses_in_url() -> None:
    result = format_reply(_output(answer="See [wiki](https://en.wikipedia.org/wiki/Foo_(bar))"))
    assert "wiki" in result
    assert "wikipedia" in result
    assert "Foo" in result


def test_link_with_query_params() -> None:
    result = format_reply(
        _output(answer="Check [results](https://example.com/search?q=test&page=1)")
    )
    assert "results" in result
    assert "example" in result


def test_link_with_hash_fragment() -> None:
    result = format_reply(_output(answer="Jump to [section](https://docs.io/page#heading-1)"))
    assert "section" in result
    assert "docs" in result


# --- 3.4 Smart truncation -------------------------------------------------


def test_truncation_at_sentence_boundary() -> None:
    """Truncation should prefer cutting at sentence end rather than mid-word."""
    # Build text with sentences that exceeds the limit
    sentence = "This is a complete sentence. "
    answer = sentence * 200  # way over 4096
    result = format_reply(_output(answer=answer))
    assert len(result) <= _MAX_LEN
    assert result.endswith("…")
    # The text before the ellipsis should end at a sentence boundary (period)
    body = result[:-1].rstrip()
    assert body.endswith(".") or body.endswith("\\.")


def test_truncation_at_paragraph_boundary() -> None:
    """Truncation should prefer paragraph breaks when available."""
    para = "Short paragraph here.\n\n"
    answer = para * 300  # way over 4096
    result = format_reply(_output(answer=answer))
    assert len(result) <= _MAX_LEN
    assert result.endswith("…")


def test_truncation_no_good_boundary_falls_back() -> None:
    """When there's no sentence/paragraph/word boundary, still truncate."""
    answer = "A" * 5000  # no spaces, no punctuation
    result = format_reply(_output(answer=answer))
    assert len(result) <= _MAX_LEN
    assert result.endswith("…")
