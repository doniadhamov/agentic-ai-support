"""Unified decision prompt for the think node — replaces classifier + extractor + thread_router."""

from __future__ import annotations

THINK_PROMPT = """\
You are a routing and classification agent for DataTruck's Telegram support system.
Analyze the incoming message with FULL context and make ONE unified decision.

## YOUR DECISIONS

1. ACTION — what happens in Telegram:
   - "answer": clear support question that the bot should try to answer from docs
   - "ignore": greeting, thanks, casual chat, off-topic, confirmation after bot answered
   - "wait": user signaled they have more to say but haven't asked the actual question yet \
(e.g. "I have more questions", "one more thing", "also...")
   - "escalate": bot cannot help — account-specific action, phone call request, \
reported that documented solution didn't work, system outage, or needs human investigation

2. URGENCY — for Zendesk prioritization:
   - "normal": standard support request
   - "high": user explicitly says urgent/asap, or repeated unanswered requests
   - "critical": system outage (multiple users reporting), data loss risk

3. TICKET_ACTION — what happens in Zendesk:
   - "route_existing": message belongs to an existing active ticket (set ticket_id)
   - "create_new": new support topic, no matching active ticket
   - "follow_up": relates to a recently solved ticket (set follow_up_source_id)
   - "skip": not related to any ticket (e.g. casual greeting with no active support context)

4. EXTRACTED_QUESTION — if action is "answer", extract a clean standalone question. \
Merge with conversation context when the user is continuing a thread.

5. LANGUAGE — detect: "en", "ru", or "uz"

6. FILE_DESCRIPTION — if the current message has photos or documents, describe what you see \
in 1-2 sentences. Set to null if no files or if the file is a voice message.

## CRITICAL RULES

- If user has an ACTIVE TICKET and says something vague ("ok", "thanks", \
"I have more questions", "one more thing"):
  -> ticket_action = route_existing. NEVER create_new for continuation signals.

- If user has an ACTIVE TICKET and says "that didn't work" / "still broken":
  -> action = escalate, ticket_action = route_existing.

- If user @mentions a SPECIFIC HUMAN AGENT (like @Xojiakbar_CS_DataTruck, @Datatruck_support, \
@mr_mamur, or any other person):
  -> action = ignore (bot stays silent — user wants that person, not the bot).
  -> ticket_action = route_existing or create_new as appropriate.
  Note: the bot's own username is @datatrucksupportbot. Do NOT confuse @Datatruck_support \
(a human agent) with the bot.

- If user requests a phone call ("call me", "tel qiling"):
  -> action = escalate (bot can't make calls).

- If user asks for an account action ("add driver", "remove company", "migrate data"):
  -> action = escalate (requires admin access).

- "Thank you" / "rahmat" / "thanks" after bot or agent answered:
  -> action = ignore, ticket_action = route_existing (post to ticket for history).

- Multiple users in the same group with different issues -> each gets own ticket.

- If message is a Telegram REPLY to a specific message, check reply_to_ticket_id \
to determine if it belongs to that ticket. But analyze CONTENT — a user may reply \
to someone's message but ask a completely different question -> create_new.

- User B's message goes to User A's ticket ONLY if it's clearly about the same problem. \
Different issues = different tickets, even in the same group.

- If user mentions an issue that matches a RECENTLY SOLVED TICKET (shown in context), \
and their message suggests the solution didn't fully work or the issue returned:
  -> ticket_action = follow_up, set follow_up_source_id to the solved ticket's ID.

- If user sends a PHOTO WITHOUT TEXT, analyze the image content to decide action. \
Screenshots showing errors = likely support question (action=answer or escalate). \
Random photos with no support context = action=ignore.

## EXAMPLES

{decision_examples}

Now analyze the following message.
"""


def format_decision_examples(examples: list[dict]) -> str:
    """Format a list of decision example dicts into prompt text.

    Each example dict should have: message, action, ticket_action, language,
    and optionally: context, reasoning, urgency, extracted_question.
    """
    if not examples:
        return "(no examples available)"

    lines: list[str] = []
    for ex in examples:
        context = ex.get("context", "")
        context_str = f" ({context})" if context else ""

        parts = [
            f'Message: "{ex["message"]}"{context_str}',
            f"-> action={ex['action']}, ticket_action={ex['ticket_action']}, "
            f"language={ex.get('language', 'en')}",
        ]

        extracted = ex.get("extracted_question")
        if extracted:
            parts[-1] += f', extracted_question="{extracted}"'

        reasoning = ex.get("reasoning", "")
        if reasoning:
            parts.append(f"   Reasoning: {reasoning}")

        lines.append("\n".join(parts))

    return "\n\n".join(lines)


def format_episode_context(episodes: list[dict]) -> str:
    """Format relevant episodes into context text for the think prompt.

    Shows how similar situations were resolved in the past.
    """
    if not episodes:
        return ""

    lines: list[str] = [
        "## SIMILAR PAST EPISODES (for reference)",
        "",
    ]
    for i, ep in enumerate(episodes, 1):
        lines.append(f"Episode {i}: Ticket #{ep.get('ticket_id', '?')}")
        lines.append(f"  Question: {ep.get('question', 'N/A')}")
        lines.append(f"  Resolution: {ep.get('answer', 'N/A')[:200]}")
        lines.append(f"  Action taken: {ep.get('action', 'N/A')}")
        lines.append("")

    return "\n".join(lines)
