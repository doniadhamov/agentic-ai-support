"""Think node — ONE unified decision call replacing classifier + extractor + thread_router.

Uses Claude Haiku with tool-use pattern.
"""

from __future__ import annotations

import base64
import json
import time

import anthropic
from loguru import logger

from src.agent.prompts.system_prompt import SYSTEM_PROMPT
from src.agent.prompts.think_prompt import HARDCODED_DECISION_EXAMPLES, THINK_PROMPT
from src.agent.state import SupportState
from src.config.settings import get_settings
from src.utils.retry import async_retry

_TOOL_NAME = "produce_decision"

_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": "Return the unified routing and classification decision.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["answer", "ignore", "wait", "escalate"],
                "description": "What happens in Telegram",
            },
            "urgency": {
                "type": "string",
                "enum": ["normal", "high", "critical"],
                "description": "Zendesk prioritization",
            },
            "ticket_action": {
                "type": "string",
                "enum": ["route_existing", "create_new", "skip", "follow_up"],
                "description": "What happens in Zendesk",
            },
            "ticket_id": {
                "type": ["integer", "null"],
                "description": "Existing ticket to route to (for route_existing)",
            },
            "follow_up_source_id": {
                "type": ["integer", "null"],
                "description": "Solved ticket to create follow-up from",
            },
            "extracted_question": {
                "type": ["string", "null"],
                "description": "Clean standalone question (if action=answer)",
            },
            "language": {
                "type": "string",
                "enum": ["en", "ru", "uz"],
                "description": "Detected message language",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief reasoning for the decision",
            },
            "file_description": {
                "type": ["string", "null"],
                "description": "Description of photo/document content (null if no files or voice)",
            },
        },
        "required": ["action", "urgency", "ticket_action", "language", "reasoning"],
    },
}


def _build_context_text(state: SupportState) -> str:
    """Build the context section for the think prompt."""
    parts: list[str] = []

    # Conversation history
    history = state.get("conversation_history", [])
    if history:
        lines = [
            msg.get("formatted", f"{msg.get('username', '')}: {msg.get('text', '')}")
            for msg in history
        ]
        parts.append("CONVERSATION HISTORY (oldest first):\n" + "\n".join(lines))

    # Active tickets
    active = state.get("active_tickets", [])
    if active:
        ticket_lines = []
        for t in active:
            ticket_lines.append(
                f'  Ticket #{t["ticket_id"]}: "{t["subject"]}" '
                f"(user_id={t['user_id']}, status={t['status']}, urgency={t['urgency']})"
            )
        parts.append("ACTIVE TICKETS IN THIS GROUP:\n" + "\n".join(ticket_lines))
    else:
        parts.append("ACTIVE TICKETS IN THIS GROUP: (none)")

    # User's active ticket
    user_ticket = state.get("user_active_ticket")
    if user_ticket:
        parts.append(
            f"THIS USER'S ACTIVE TICKET: #{user_ticket['ticket_id']} "
            f'"{user_ticket["subject"]}" (status={user_ticket["status"]})'
        )

    # Recently solved tickets
    solved = state.get("recently_solved_tickets", [])
    if solved:
        solved_lines = []
        for t in solved:
            solved_lines.append(
                f'  Ticket #{t["ticket_id"]}: "{t["subject"]}" '
                f"(closed {t.get('closed_at', 'recently')})"
            )
        parts.append("RECENTLY SOLVED TICKETS (last 7 days):\n" + "\n".join(solved_lines))

    # Bot's last response
    bot_resp = state.get("bot_last_response")
    if bot_resp:
        parts.append(f"BOT'S LAST RESPONSE IN THIS GROUP:\n{bot_resp[:500]}")

    # Reply-to context
    reply_text = state.get("reply_to_text")
    reply_ticket = state.get("reply_to_ticket_id")
    if reply_text:
        reply_info = f'REPLYING TO MESSAGE: "{reply_text[:300]}"'
        if reply_ticket:
            reply_info += f" (belongs to ticket #{reply_ticket})"
        parts.append(reply_info)

    return "\n\n".join(parts)


@async_retry(min_wait=5.0, max_wait=65.0)
async def _call_think(
    client: anthropic.AsyncAnthropic,
    model: str,
    system: str,
    user_content: str | list[dict],
) -> dict:
    """Make the Haiku tool-use call."""
    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=0.0,
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
    raise ValueError(f"No '{_TOOL_NAME}' tool_use block found in think response")


async def think_node(state: SupportState) -> dict:
    """Run the unified decision call."""
    t0 = time.monotonic()
    settings = get_settings()

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    model = settings.anthropic_fast_model

    # Build prompt
    prompt = THINK_PROMPT.format(decision_examples=HARDCODED_DECISION_EXAMPLES)
    context = _build_context_text(state)

    message_section = (
        f"CURRENT MESSAGE:\n"
        f"From: {state['sender_name']} (user_id={state['sender_id']})\n"
        f"Group: {state['group_name']} (group_id={state['group_id']})\n"
        f"Text: {state['raw_text']}"
    )

    full_prompt = f"{prompt}\n\n{context}\n\n{message_section}"

    # Include images if present
    images = state.get("images", [])
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
        user_content.append({"type": "text", "text": full_prompt})
    else:
        user_content = full_prompt

    # Call Haiku
    decision = await _call_think(client, model, SYSTEM_PROMPT, user_content)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    action = decision.get("action", "ignore")
    ticket_action = decision.get("ticket_action", "skip")

    logger.info(
        "think: action={} ticket_action={} urgency={} lang={} elapsed={}ms | {}",
        action,
        ticket_action,
        decision.get("urgency", "normal"),
        decision.get("language", "en"),
        elapsed_ms,
        decision.get("reasoning", "")[:100],
    )

    return {
        "action": action,
        "urgency": decision.get("urgency", "normal"),
        "ticket_action": ticket_action,
        "target_ticket_id": decision.get("ticket_id"),
        "follow_up_source_id": decision.get("follow_up_source_id"),
        "extracted_question": decision.get("extracted_question"),
        "language": decision.get("language", "en"),
        "decision_reasoning": decision.get("reasoning", ""),
        "file_description": decision.get("file_description"),
        "think_ms": elapsed_ms,
    }
