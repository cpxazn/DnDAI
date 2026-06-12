from __future__ import annotations

from pydantic import BaseModel, Field


class DiceRollRequest(BaseModel):
    formula: str = Field(min_length=2, max_length=50)
    roll_type: str | None = None
    advantage_state: str = Field(default="normal", pattern="^(normal|advantage|disadvantage)$")


class DieResult(BaseModel):
    sides: int
    result: int


class DiceRollResponse(BaseModel):
    formula: str
    roll_type: str | None = None
    advantage_state: str
    dice: list[DieResult]
    modifier_total: int
    total: int
    kept_total: int | None = None
    dropped_total: int | None = None
