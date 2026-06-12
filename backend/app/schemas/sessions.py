from __future__ import annotations

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    campaign_id: int
    name: str = Field(min_length=1, max_length=200)


class SessionSummary(BaseModel):
    id: int
    campaign_id: int
    name: str
    status: str
    started_at: str
    ended_at: str | None = None
