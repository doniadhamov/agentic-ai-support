"""Classifier few-shot prompt with examples in English, Russian, and Uzbek."""

from __future__ import annotations

CLASSIFIER_PROMPT = """\
Classify the incoming Telegram message into one of these categories:
- NON_SUPPORT — no actionable support request AND no connection to an ongoing support conversation
- SUPPORT_QUESTION — the message contains a clear, specific support question
- CLARIFICATION_NEEDED — the user appears to need support but hasn't provided enough detail to answer
- ESCALATION_REQUIRED — repeated failures or explicit request for human help

HOW TO CLASSIFY:
Think like a human support agent. Read the message together with the conversation context \
and decide the user's intent.

- If the message BY ITSELF is a clear support question → SUPPORT_QUESTION.
- If context shows the user is in an active support conversation and their message is a \
follow-up, continuation, or signal that they need more help (e.g. "I have more questions", \
"one more thing", "also...", "what about...") → CLARIFICATION_NEEDED. The user is still \
in a support interaction and needs attention, even if the current message alone is vague.
- If the message references a problem from context (e.g. "it doesn't work", "same issue") \
→ SUPPORT_QUESTION or CLARIFICATION_NEEDED depending on specificity.
- If there is NO support conversation in context and the message has no support intent \
(greetings, casual chat, off-topic) → NON_SUPPORT.
- A "thank you" or confirmation after a bot answer with no further questions → NON_SUPPORT.

KEY PRINCIPLE: A message that would be NON_SUPPORT in isolation may be CLARIFICATION_NEEDED \
or SUPPORT_QUESTION when there is a recent support conversation in context. Use your judgment \
— do not follow rigid pattern matching.

IMAGES: Treat attached images as part of the message. A screenshot showing an error/warning \
counts as a support question even with minimal text. A screenshot of a normal UI screen \
without text explaining the problem is CLARIFICATION_NEEDED. A photo with no text and no \
product-related content is NON_SUPPORT.

Also detect the language of the message (en, ru, or uz).

Use the produce_output tool to return your classification.

---

EXAMPLES (for guidance — reason from context, do not pattern-match):

Message: "Good morning everyone!" (no support context) → NON_SUPPORT, en
Message: "thanks that helped" (after bot answered) → NON_SUPPORT, en
Message: "Всем привет, как дела?" → NON_SUPPORT, ru

Message: "How do I update a load status to 'Delivered'?" → SUPPORT_QUESTION, en
Message: "Как добавить нового водителя в систему?" → SUPPORT_QUESTION, ru
Message: "same problem" (context shows a specific error being discussed) → SUPPORT_QUESTION, en
Message: "it doesn't let me save" + screenshot of a validation error → SUPPORT_QUESTION, en

Message: "I have more questions" (after bot just answered a support question) → CLARIFICATION_NEEDED, en
Message: "It still doesn't work." (no prior context visible) → CLARIFICATION_NEEDED, en
Message: (no text) + screenshot of normal UI with no visible error → CLARIFICATION_NEEDED, en

Message: "I've followed all the steps three times but the driver still can't log in." → ESCALATION_REQUIRED, en
Message: "Уже третий раз пробую обновить статус, но изменения не сохраняются." → ESCALATION_REQUIRED, ru

---

Now classify the following message.
"""
