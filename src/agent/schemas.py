"""Pydantic schemas for the AI agent layer."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MessageCategory(str, Enum):
    NON_SUPPORT = "NON_SUPPORT"
    SUPPORT_QUESTION = "SUPPORT_QUESTION"
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


class KnowledgeSource(BaseModel):
    type: str = Field(..., description="'documentation' or 'approved_memory'")
    title: str = Field(default="")
    id: str = Field(default="")


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
    ticket_id: str = Field(default="", description="Ticket ID if a ticket was created")
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
