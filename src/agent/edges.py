"""Conditional edge routing functions for the support agent graph."""

from __future__ import annotations

from src.agent.state import SupportState


def route_after_think(state: SupportState) -> str:
    """Route based on think node's action decision."""
    return state.get("action", "ignore")  # "answer" | "ignore" | "wait" | "escalate"


def route_after_generate(state: SupportState) -> str:
    """Route based on whether generate produced an answer or needs escalation."""
    if state.get("needs_escalation"):
        return "escalate"
    return "respond"
