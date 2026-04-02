"""Generate node — answer from retrieved docs using Claude Sonnet."""

from __future__ import annotations

import base64
import json
import time
from collections import OrderedDict

import anthropic
from loguru import logger

from src.agent.prompts.generate_prompt import GENERATOR_PROMPT
from src.agent.prompts.system_prompt import SYSTEM_PROMPT
from src.agent.state import SupportState
from src.config.settings import get_settings
from src.utils.retry import async_retry

_TOOL_NAME = "produce_output"

_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": "Return the generated support answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "Final reply to send to the user",
            },
            "follow_up_question": {
                "type": "string",
                "description": "Clarification question if needed, otherwise empty string",
            },
            "needs_escalation": {
                "type": "boolean",
                "description": "True if the question cannot be answered from available knowledge",
            },
            "escalation_reason": {
                "type": "string",
                "description": "Brief reason for escalation if needs_escalation is true",
            },
        },
        "required": ["answer", "needs_escalation"],
    },
}


def _format_chunks(docs: list[dict]) -> str:
    """Render retrieved chunks grouped by article for the prompt."""
    if not docs:
        return "(no relevant documentation found)"

    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for chunk in docs:
        if chunk.get("source") == "docs" and chunk.get("article_id") is not None:
            key = f"docs_{chunk['article_id']}"
        else:
            key = f"{chunk.get('source', 'unknown')}_{chunk['point_id']}"
        if key not in groups:
            groups[key] = []
        groups[key].append(chunk)

    parts: list[str] = []
    for i, (_, group) in enumerate(groups.items(), start=1):
        group.sort(key=lambda c: c.get("chunk_index", 0))
        first = group[0]
        source_label = "documentation" if first.get("source") == "docs" else "approved memory"
        title = first.get("article_title") or "Untitled"
        best_score = max(c.get("score", 0) for c in group)
        header = f"[{i}] Source: {source_label} | Title: {title} | Score: {best_score:.3f}"
        url = first.get("article_url")
        if url:
            header += f" | URL: {url}"

        text_parts: list[str] = []
        for chunk in group:
            img_url = chunk.get("image_url")
            if img_url:
                text_parts.append(f"screenshot({img_url})")
            text_parts.append(chunk.get("text", "").strip())

        parts.append(f"{header}\n" + "\n".join(text_parts))
    return "\n\n".join(parts)


@async_retry(min_wait=5.0, max_wait=65.0)
async def _call_generate(
    client: anthropic.AsyncAnthropic,
    model: str,
    system: str,
    user_content: str | list[dict],
) -> dict:
    """Make the Sonnet tool-use call."""
    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.2,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == _TOOL_NAME:
            if isinstance(block.input, str):
                return json.loads(block.input)
            return block.input  # type: ignore[return-value]
    raise ValueError(f"No '{_TOOL_NAME}' tool_use block found in generate response")


async def generate_node(state: SupportState) -> dict:
    """Generate an answer from retrieved docs."""
    t0 = time.monotonic()
    settings = get_settings()

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    model = settings.anthropic_model

    question = state.get("extracted_question") or state.get("raw_text", "")
    language = state.get("language", "en")
    docs = state.get("retrieved_docs", [])
    confidence = state.get("retrieval_confidence", 0.0)

    # If no docs at all, escalate immediately without LLM call
    if not docs or confidence < settings.support_min_confidence_score:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info("generate: no docs or low confidence ({:.3f}), escalating", confidence)
        return {
            "answer_text": None,
            "follow_up_question": None,
            "needs_escalation": True,
            "escalation_reason": f"No relevant documentation found (confidence={confidence:.3f})",
            "knowledge_sources": [],
            "generate_ms": elapsed_ms,
        }

    chunks_text = _format_chunks(docs)
    prompt_text = GENERATOR_PROMPT.format(
        chunks=chunks_text,
        question=question,
        language=language,
    )

    # Include images so Sonnet can see what the user sees
    images = state.get("recent_image_bytes", [])
    if images:
        user_content: str | list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(img).decode(),
                },
            }
            for img in images[:5]
        ]
        user_content.append({"type": "text", "text": prompt_text})
    else:
        user_content = prompt_text

    result = await _call_generate(client, model, SYSTEM_PROMPT, user_content)

    # Build knowledge_sources from chunks
    seen: set[str] = set()
    knowledge_sources: list[dict] = []
    for chunk in docs:
        key = chunk.get("article_url") or chunk.get("article_title") or chunk["point_id"]
        if key in seen:
            continue
        seen.add(key)
        knowledge_sources.append(
            {
                "type": "documentation" if chunk.get("source") == "docs" else "approved_memory",
                "title": chunk.get("article_title", ""),
                "url": chunk.get("article_url", ""),
                "id": chunk["point_id"],
            }
        )

    needs_escalation = result.get("needs_escalation", False)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if needs_escalation:
        logger.info("generate: escalating — {}", result.get("escalation_reason", "")[:100])
    else:
        logger.info(
            "generate: answer produced (sources={}) elapsed={}ms",
            len(knowledge_sources),
            elapsed_ms,
        )

    return {
        "answer_text": result.get("answer", "") or None,
        "follow_up_question": result.get("follow_up_question", "") or None,
        "needs_escalation": needs_escalation,
        "escalation_reason": result.get("escalation_reason", ""),
        "knowledge_sources": knowledge_sources,
        "generate_ms": elapsed_ms,
    }
