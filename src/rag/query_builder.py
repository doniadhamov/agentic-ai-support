"""Query builder: prepare the retrieval query string from a user question."""

from __future__ import annotations


def build_query(question: str, language: str) -> str:  # noqa: ARG001
    """Build a retrieval query string from the user's question.

    Strips and normalises the question. The ``language`` parameter is accepted
    for future language-aware query augmentation (e.g. adding language-specific
    stop-word removal or prefix prompts).

    Args:
        question: The cleaned standalone question to retrieve answers for.
        language: Language code (en/ru/uz).

    Returns:
        Query string ready to be embedded for retrieval.
    """
    return question.strip()
