"""Extractor prompt: derives a clean standalone support question from the conversation."""

from __future__ import annotations

EXTRACTOR_PROMPT = """\
Given the incoming Telegram message and recent conversation context, extract:
1. A clean, standalone support question that captures the real support intent.
2. The language of the support request (en, ru, or uz).
3. A brief summary of the relevant conversation context (1-2 sentences max).

Rules for the extracted question:
- Remove greetings, filler text, and emotional wording that does not change the issue.
- Combine recent relevant messages from the same user if they belong to the same issue.
- Use context only when it is clearly relevant to the current question.
- Do not merge unrelated issues from different users.
- Write the question as a clear, specific, standalone support question.
- Keep it in the same language as the user's support request.

Use the produce_output tool to return your result.
"""
