"""Pydantic schemas for the AI agent layer.

Only the types still used by the formatter and respond node are kept here.
The old pipeline schemas (ClassifierResult, ExtractorResult, GeneratorResult,
ThreadRoutingAction, ThreadRoutingResult, AgentInput) were removed in the
LangGraph redesign — replaced by SupportState TypedDict.
"""

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
