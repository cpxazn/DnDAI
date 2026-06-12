from __future__ import annotations

from pydantic import BaseModel, Field


class CombatantInput(BaseModel):
    source_character_id: str | None = None
    name: str
    initiative: int | None = None
    current_hp: int | None = None
    max_hp: int | None = None
    armor_class: int | None = None
    speed: int | None = None
    size: str = Field(default="Medium", pattern="^(Tiny|Small|Medium|Large|Huge|Gargantuan)$")
    saving_throw_bonuses: dict[str, int] = Field(default_factory=dict)
    position_x: int | None = None
    position_y: int | None = None
    conditions: list[str] = Field(default_factory=list)
    is_player: bool = False
    party_order: int | None = None


class CombatStartRequest(BaseModel):
    campaign_id: int
    session_id: int
    name: str | None = None
    combatants: list[CombatantInput] = Field(default_factory=list)


class CombatEndRequest(BaseModel):
    campaign_id: int
    session_id: int
    encounter_id: int | None = None


class CombatAdvanceTurnRequest(BaseModel):
    campaign_id: int
    session_id: int
    encounter_id: int


class CombatOperationRequest(BaseModel):
    operation: str = Field(pattern="^(start|end|advance_turn|update_position)$")
    campaign_id: int
    session_id: int
    name: str | None = None
    encounter_id: int | None = None
    combatant_ref: str | None = None
    position_x: int | None = None
    position_y: int | None = None
    combatants: list[CombatantInput] = Field(default_factory=list)


class CombatantSummary(BaseModel):
    id: int
    source_character_id: str | None = None
    name: str
    initiative: int | None = None
    current_hp: int | None = None
    max_hp: int | None = None
    base_armor_class: int | None = None
    armor_class: int | None = None
    base_speed: int | None = None
    speed: int | None = None
    size: str
    saving_throw_bonuses: dict[str, int] = Field(default_factory=dict)
    position_x: int | None = None
    position_y: int | None = None
    conditions: list[str] = Field(default_factory=list)
    effects: list[dict] = Field(default_factory=list)
    is_player: bool
    party_order: int | None = None


class CombatStateResponse(BaseModel):
    encounter_id: int
    campaign_id: int
    session_id: int
    status: str
    name: str | None = None
    round_number: int
    turn_index: int
    active_combatant_id: int | None = None
    winning_side: str | None = None
    outcome_summary: str | None = None
    combatants: list[CombatantSummary] = Field(default_factory=list)
