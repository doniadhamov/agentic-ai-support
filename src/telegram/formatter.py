"""Format :class:`AgentOutput` into a Telegram MarkdownV2 reply string."""

from __future__ import annotations

import re

from src.agent.schemas import AgentOutput

_MAX_LEN = 4096  # Telegram hard limit
_SCREENSHOT_RE = re.compile(r"\n?screenshot\(https?://[^)]+\)\n?")

# Characters that must be escaped in Telegram MarkdownV2 (outside of entities).
_ESCAPE_CHARS = set(r"_[]()~`>#+=|{}.!-")

# Placeholders using Unicode private-use-area characters (safe from regex issues)
_PH = {
    "B1": "\ue001",  # bold start
    "B2": "\ue002",  # bold end
    "I1": "\ue003",  # italic start
    "I2": "\ue004",  # italic end
    "S1": "\ue005",  # strikethrough start
    "S2": "\ue006",  # strikethrough end
}


def format_reply(output: AgentOutput) -> str:
    """Convert an :class:`AgentOutput` to a Telegram MarkdownV2 string.

    Args:
        output: The agent's processing result.

    Returns:
        A non-empty string ready to be sent with ``ParseMode.MARKDOWN_V2``.
    """
    text = _build_text(output)
    text = _strip_screenshots(text)
    text = _markdown_to_telegram(text)

    if len(text) > _MAX_LEN:
        text = _smart_truncate(text, _MAX_LEN)

    return text


# ---------------------------------------------------------------------------
# Markdown → Telegram MarkdownV2 conversion
# ---------------------------------------------------------------------------


def _markdown_to_telegram(text: str) -> str:
    """Convert standard Markdown to Telegram MarkdownV2."""
    # 1. Stash code blocks and inline code (protect from further processing)
    code_blocks: list[str] = []
    inline_codes: list[str] = []
    links: list[str] = []

    def _stash_code_block(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = m.group(2)
        # Normalize: ensure newline between language identifier and code
        if code and not code.startswith("\n"):
            code = code.lstrip()
            code = "\n" + code
        idx = len(code_blocks)
        code_blocks.append(f"```{lang}{code}```")
        return f"\uf000CB{idx}\uf000"

    def _stash_inline_code(m: re.Match) -> str:
        code = m.group(1)
        idx = len(inline_codes)
        inline_codes.append(f"`{code}`")
        return f"\uf000IC{idx}\uf000"

    def _stash_link(m: re.Match) -> str:
        link_text = _escape_mdv2(m.group(1))
        url = m.group(2)
        # Escape special MarkdownV2 characters in the URL (parentheses are
        # allowed inside Telegram's link syntax but ) and \ must be escaped)
        url = url.replace("\\", "\\\\").replace(")", "\\)")
        idx = len(links)
        links.append(f"[{link_text}]({url})")
        return f"\uf000LN{idx}\uf000"

    text = re.sub(r"```(\w*)\n(.*?)```", _stash_code_block, text, flags=re.DOTALL)
    # Also handle code blocks where lang identifier has no newline (e.g. ```python code```)
    text = re.sub(r"```(\w+)([ \t]+.*?)```", _stash_code_block, text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", _stash_inline_code, text)

    # 2. Headings → bold
    lines = text.split("\n")
    processed: list[str] = []
    for line in lines:
        m = re.match(r"^#{1,6}\s+(.+)$", line)
        if m:
            processed.append(f"{_PH['B1']}{m.group(1).strip()}{_PH['B2']}")
        else:
            processed.append(line)
    text = "\n".join(processed)

    # 3. Bold-italic ***text*** or ___text___
    text = re.sub(
        r"\*{3}(.+?)\*{3}",
        lambda m: f"{_PH['B1']}{_PH['I1']}{m.group(1)}{_PH['I2']}{_PH['B2']}",
        text,
    )
    text = re.sub(
        r"___(.+?)___",
        lambda m: f"{_PH['B1']}{_PH['I1']}{m.group(1)}{_PH['I2']}{_PH['B2']}",
        text,
    )

    # 3b. Mixed nesting: **_text_** and _**text**_
    text = re.sub(
        r"\*{2}_(.+?)_\*{2}",
        lambda m: f"{_PH['B1']}{_PH['I1']}{m.group(1)}{_PH['I2']}{_PH['B2']}",
        text,
    )
    text = re.sub(
        r"_\*{2}(.+?)\*{2}_",
        lambda m: f"{_PH['I1']}{_PH['B1']}{m.group(1)}{_PH['B2']}{_PH['I2']}",
        text,
    )

    # 4. Bold **text**
    text = re.sub(
        r"\*{2}(.+?)\*{2}",
        lambda m: f"{_PH['B1']}{m.group(1)}{_PH['B2']}",
        text,
    )

    # 5. Italic *text* (single asterisk)
    text = re.sub(
        r"(?<!\*)\*([^*]+?)\*(?!\*)",
        lambda m: f"{_PH['I1']}{m.group(1)}{_PH['I2']}",
        text,
    )

    # 6. Italic _text_ (single underscore, not __)
    text = re.sub(
        r"(?<!_)_([^_]+?)_(?!_)",
        lambda m: f"{_PH['I1']}{m.group(1)}{_PH['I2']}",
        text,
    )

    # 7. Strikethrough ~~text~~
    text = re.sub(
        r"~~(.+?)~~",
        lambda m: f"{_PH['S1']}{m.group(1)}{_PH['S2']}",
        text,
    )

    # 8. Links [text](url) — supports balanced parentheses and special chars in URLs
    text = re.sub(
        r"\[([^\]]+)\]\(((?:[^()]*|\([^()]*\))*)\)",
        _stash_link,
        text,
    )

    # 9. Escape all remaining special characters
    text = _escape_mdv2(text)

    # 10. Restore placeholders
    text = text.replace(_PH["B1"], "*").replace(_PH["B2"], "*")
    text = text.replace(_PH["I1"], "_").replace(_PH["I2"], "_")
    text = text.replace(_PH["S1"], "~").replace(_PH["S2"], "~")

    for i, link in enumerate(links):
        text = text.replace(f"\uf000LN{i}\uf000", link)
    for i, code in enumerate(code_blocks):
        text = text.replace(f"\uf000CB{i}\uf000", code)
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\uf000IC{i}\uf000", code)

    return text


def _escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    result: list[str] = []
    for ch in text:
        if ch in _ESCAPE_CHARS:
            result.append("\\")
        result.append(ch)
    return "".join(result)


# ---------------------------------------------------------------------------
# Smart truncation
# ---------------------------------------------------------------------------

# Minimum portion of the limit to keep when searching for a break point.
# If no sentence/paragraph break is found within the last 20%, hard-cut.
_TRUNCATION_SEARCH_RATIO = 0.8


def _smart_truncate(text: str, limit: int) -> str:
    """Truncate *text* at a sentence or paragraph boundary when possible.

    Tries, in order:
    1. Last paragraph break (``\\n\\n``) before *limit*.
    2. Last sentence-ending punctuation (``. ! ?``) followed by a space or newline.
    3. Last whitespace boundary (avoid splitting a word).
    4. Hard cut as a last resort.
    """
    # Reserve 1 char for the ellipsis
    max_content = limit - 1
    search_floor = int(max_content * _TRUNCATION_SEARCH_RATIO)

    window = text[:max_content]

    # 1. Paragraph break
    pos = window.rfind("\n\n", search_floor)
    if pos != -1:
        return text[:pos].rstrip() + "…"

    # 2. Sentence end (. ! ?) followed by space/newline/end-of-window
    sentence_matches = list(re.finditer(r"[.!?](?=\s|$)", window[search_floor:]))
    if sentence_matches:
        cut = search_floor + sentence_matches[-1].end()
        return text[:cut].rstrip() + "…"

    # 3. Word boundary
    pos = window.rfind(" ", search_floor)
    if pos != -1:
        return text[:pos].rstrip() + "…"

    # 4. Hard cut
    return text[:max_content] + "…"


# ---------------------------------------------------------------------------
# Screenshot stripping
# ---------------------------------------------------------------------------


def _strip_screenshots(text: str) -> str:
    """Remove ``screenshot(url)`` markers and collapse extra blank lines."""
    text = _SCREENSHOT_RE.sub("\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Text assembly
# ---------------------------------------------------------------------------


def _build_text(output: AgentOutput) -> str:
    """Assemble the raw (pre-truncation) reply text."""

    # --- Clarification / follow-up question ---------------------------------
    if output.follow_up_question and not output.answer:
        return output.follow_up_question

    # --- Regular answer -----------------------------------------------------
    if output.answer:
        parts: list[str] = [output.answer]

        sources = _format_sources(output)
        if sources:
            parts.append(sources)

        if output.follow_up_question:
            parts.append(f"\n{output.follow_up_question}")

        return "\n\n".join(parts)

    # --- Fallback -----------------------------------------------------------
    return "I could not find a relevant answer. Please try rephrasing your question."


def _format_sources(output: AgentOutput) -> str:
    """Return a 'For more information' line with article URL, or empty string."""
    for source in output.knowledge_sources_used:
        if source.url and source.type == "documentation":
            return f"For more information: {source.url}"
    return ""
