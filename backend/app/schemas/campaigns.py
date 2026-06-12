from __future__ import annotations

from pydantic import BaseModel, Field


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CampaignSummary(BaseModel):
    id: int
    name: str
    status: str
    current_location_text: str | None = None
