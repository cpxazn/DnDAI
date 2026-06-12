from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryTurn(BaseModel):
    id: int
    turn_index: int
    speaker_role: str
    speaker_entity_id: str | None = None
    user_text: str | None = None
    assistant_text: str | None = None
    created_at: str


class SceneSummary(BaseModel):
    id: int
    summary_kind: str
    summary_text: str
    created_at: str


class MemoryFact(BaseModel):
    id: int
    fact_type: str
    fact_text: str
    tags: list[str] = Field(default_factory=list)
    created_at: str


class MemoryDebugResponse(BaseModel):
    recent_turns: list[MemoryTurn] = Field(default_factory=list)
    scene_summaries: list[SceneSummary] = Field(default_factory=list)
    facts: list[MemoryFact] = Field(default_factory=list)
