"""Classifier few-shot prompt with examples in English, Russian, and Uzbek."""

from __future__ import annotations

CLASSIFIER_PROMPT = """\
Classify the incoming Telegram message into one of these categories:
- NON_SUPPORT — no actionable support request in the message
- SUPPORT_QUESTION — the message itself contains a clear, specific support question
- CLARIFICATION_NEEDED — the message describes a support issue but lacks enough detail to answer; also use when the user sends an image without text AND the image does NOT show a clear error, warning, or failure — the user likely needs something but hasn't stated what
- ESCALATION_REQUIRED — repeated failures or explicit request for human help

CORE RULE:
Classify based on the CURRENT MESSAGE ONLY. The conversation context is provided so you \
can understand references (e.g. "it doesn't work" referring to a prior issue), but you must \
NOT infer or re-trigger a support question from context. If the current message does not \
contain or clearly describe a specific support problem, it is NON_SUPPORT — regardless of \
what was discussed before.

IMAGES: The message may include a photo or screenshot. Treat the image as part of the message \
content. A screenshot showing a clear error message, warning dialog, or failure counts as a \
support question even if the text is minimal or absent (e.g. just "help" + screenshot of an error). \
However, a screenshot of a normal UI screen (settings page, form, list view, dashboard) sent \
WITHOUT text explaining the problem is CLARIFICATION_NEEDED — the user likely wants help but \
hasn't stated what they need. \
A photo with no text and no visible product-related content is NON_SUPPORT.

NON_SUPPORT includes: greetings, casual chat, thanks, reactions, acknowledgements, \
intent-to-ask without an actual question, confirmations of a previous answer, off-topic \
discussion, or any message with no actionable support request.

SUPPORT_QUESTION requires the message to contain a clear product usage question, bug report, \
troubleshooting request, configuration question, or process/workflow question — via text, \
image, or both.

Also detect the language of the message (en, ru, or uz).

Use the produce_output tool to return your classification.

---

EXAMPLES:

[NON_SUPPORT]
Message: "Good morning everyone!" → NON_SUPPORT, en
Message: "can i ask" → NON_SUPPORT, en
Message: "I have another question" → NON_SUPPORT, en
Message: "this my question)" (after bot already answered) → NON_SUPPORT, en
Message: "thanks that helped" → NON_SUPPORT, en
Message: "Всем привет, как дела?" → NON_SUPPORT, ru
Message: "Assalomu alaykum, hammaga salom!" → NON_SUPPORT, uz

[SUPPORT_QUESTION]
Message: "How do I update a load status to 'Delivered'?" → SUPPORT_QUESTION, en
Message: "Как добавить нового водителя в систему?" → SUPPORT_QUESTION, ru
Message: "Haydovchi parolini qanday tiklash mumkin?" → SUPPORT_QUESTION, uz
Message: "can you please check it keep giving error / when I checked there is no existing VIN" + screenshot of "Trailer with this VIN already exists" error → SUPPORT_QUESTION, en
Message: "it doesn't let me save" + screenshot of a validation error dialog → SUPPORT_QUESTION, en
Message: "same problem" (with prior context showing a specific error was being discussed) → SUPPORT_QUESTION, en

[CLARIFICATION_NEEDED]
Message: "It still doesn't work." (no prior context visible) → CLARIFICATION_NEEDED, en
Message: "Та же проблема, что и раньше." → CLARIFICATION_NEEDED, ru
Message: "Hali ham ishlamayapti." → CLARIFICATION_NEEDED, uz
Message: (no text) + screenshot of a normal settings/form/list page with no visible error → CLARIFICATION_NEEDED, en

[ESCALATION_REQUIRED]
Message: "I've followed all the steps three times but the driver still can't log in." → ESCALATION_REQUIRED, en
Message: "Уже третий раз пробую обновить статус, но изменения не сохраняются." → ESCALATION_REQUIRED, ru
Message: "Bir necha marta urinib ko'rdim, lekin yuk holati o'zgarmayapti." → ESCALATION_REQUIRED, uz

---

Now classify the following message.
"""
