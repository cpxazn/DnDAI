from __future__ import annotations

from pydantic import BaseModel, Field


class ChatOptions(BaseModel):
    apply_deterministic_actions: bool = True
    include_debug: bool = False
    stream: bool = False


class ChatClientContext(BaseModel):
    active_character_id: str | None = None
    ui_mode: str | None = None


class ChatRequest(BaseModel):
    campaign_id: int
    session_id: int
    speaker_entity_id: str | None = None
    message: str = Field(min_length=1)
    client_context: ChatClientContext | None = None
    options: ChatOptions = Field(default_factory=ChatOptions)


class ProposedAction(BaseModel):
    type: str
    actor_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    parameters: dict = Field(default_factory=dict)
    reason: str | None = None
    confidence: float | None = None


class AppliedAction(BaseModel):
    type: str
    event_id: int | None = None
    outcome: dict | None = None


class RejectedAction(BaseModel):
    type: str
    actor_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    parameters: dict = Field(default_factory=dict)
    reason: str


class Citation(BaseModel):
    source_type: str
    document_id: str
    heading_path: list[str]


class StateSummary(BaseModel):
    active_combat_encounter_id: int | None = None
    changed_entities: list[str] = Field(default_factory=list)


class ChatResponseData(BaseModel):
    turn_id: int
    session_id: int
    campaign_id: int
    narration: str
    proposed_actions: list[ProposedAction]
    applied_actions: list[AppliedAction]
    rejected_actions: list[RejectedAction]
    citations: list[Citation]
    state_summary: StateSummary
    debug: dict | None = None
