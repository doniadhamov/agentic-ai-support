"""Pydantic schemas for the AI agent layer."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class MessageCategory(StrEnum):
    NON_SUPPORT = "NON_SUPPORT"
    SUPPORT_QUESTION = "SUPPORT_QUESTION"
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


class KnowledgeSource(BaseModel):
    type: str = Field(..., description="'documentation' or 'approved_memory'")
    title: str = Field(default="")
    id: str = Field(default="")
    url: str = Field(default="", description="Source article URL")


class AgentInput(BaseModel):
    message_text: str = Field(..., description="Raw Telegram message text")
    user_id: int = Field(..., description="Telegram user ID")
    group_id: int = Field(..., description="Telegram group chat ID")
    message_id: int = Field(..., description="Telegram message ID")
    language: str = Field(default="en", description="Detected or fallback language code")
    conversation_context: list[str] = Field(
        default_factory=list,
        description="Recent messages from the same group (oldest first)",
    )
    images: list[bytes] = Field(
        default_factory=list,
        description="Image byte arrays from user messages (photos, image documents)",
        exclude=True,
    )

    @property
    def image_data(self) -> bytes | None:
        """Backward-compatible access to the first image."""
        return self.images[0] if self.images else None


class AgentOutput(BaseModel):
    category: MessageCategory
    language: str = Field(default="en")
    should_reply: bool = Field(default=False)
    extracted_question: str = Field(default="")
    answer: str = Field(default="")
    follow_up_question: str = Field(default="")
    needs_retrieval: bool = Field(default=False)
    needs_escalation: bool = Field(default=False)
    escalation_reason: str = Field(default="")
    conversation_summary: str = Field(default="")
    knowledge_sources_used: list[KnowledgeSource] = Field(default_factory=list)


class ClassifierResult(BaseModel):
    category: MessageCategory
    language: str = Field(default="en", description="Detected language code (en/ru/uz)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")


class ExtractorResult(BaseModel):
    extracted_question: str = Field(..., description="Clean standalone support question")
    language: str = Field(default="en", description="Detected language code")
    conversation_summary: str = Field(
        default="", description="Brief summary of relevant conversation context"
    )


class GeneratorResult(BaseModel):
    answer: str = Field(default="", description="Final reply to send to the user")
    follow_up_question: str = Field(
        default="", description="Clarification question if needed, otherwise empty"
    )
    needs_escalation: bool = Field(default=False)
    escalation_reason: str = Field(default="")
    knowledge_sources_used: list[KnowledgeSource] = Field(default_factory=list)


class ThreadRoutingAction(StrEnum):
    ROUTE_TO_EXISTING = "route_to_existing"
    CREATE_NEW = "create_new"
    SKIP_ZENDESK = "skip_zendesk"


class ThreadRoutingResult(BaseModel):
    """Output of the AI-powered thread router."""

    action: ThreadRoutingAction
    ticket_id: int | None = Field(
        default=None,
        description="Zendesk ticket ID to route to (only for route_to_existing)",
    )
    reasoning: str = Field(default="", description="Explanation for the routing decision")
