"""Classifier few-shot prompt with examples in English, Russian, and Uzbek."""

from __future__ import annotations

CLASSIFIER_PROMPT = """\
Classify the incoming Telegram message and recent conversation context into one of these \
categories:
- NON_SUPPORT
- SUPPORT_QUESTION
- CLARIFICATION_NEEDED
- ESCALATION_REQUIRED

Also detect the language of the support request (en, ru, or uz).

Use the produce_output tool to return your classification.

---

EXAMPLES:

[English — NON_SUPPORT]
Message: "Good morning everyone!"
→ category: NON_SUPPORT, language: en

[English — SUPPORT_QUESTION]
Message: "How do I update a load status to 'Delivered'?"
→ category: SUPPORT_QUESTION, language: en

[English — CLARIFICATION_NEEDED]
Message: "It still doesn't work."
Context: (no prior support conversation visible)
→ category: CLARIFICATION_NEEDED, language: en

[English — ESCALATION_REQUIRED]
Message: "I've followed all the steps three times but the driver still can't log in."
→ category: ESCALATION_REQUIRED, language: en

---

[Russian — NON_SUPPORT]
Message: "Всем привет, как дела?"
→ category: NON_SUPPORT, language: ru

[Russian — SUPPORT_QUESTION]
Message: "Как добавить нового водителя в систему?"
→ category: SUPPORT_QUESTION, language: ru

[Russian — CLARIFICATION_NEEDED]
Message: "Та же проблема, что и раньше."
→ category: CLARIFICATION_NEEDED, language: ru

[Russian — ESCALATION_REQUIRED]
Message: "Уже третий раз пробую обновить статус, но изменения не сохраняются."
→ category: ESCALATION_REQUIRED, language: ru

---

[Uzbek — NON_SUPPORT]
Message: "Assalomu alaykum, hammaga salom!"
→ category: NON_SUPPORT, language: uz

[Uzbek — SUPPORT_QUESTION]
Message: "Haydovchi parolini qanday tiklash mumkin?"
→ category: SUPPORT_QUESTION, language: uz

[Uzbek — CLARIFICATION_NEEDED]
Message: "Hali ham ishlamayapti."
→ category: CLARIFICATION_NEEDED, language: uz

[Uzbek — ESCALATION_REQUIRED]
Message: "Bir necha marta urinib ko'rdim, lekin yuk holati o'zgarmayapti."
→ category: ESCALATION_REQUIRED, language: uz

---

Now classify the following message.
"""
