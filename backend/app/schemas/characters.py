from __future__ import annotations

from pydantic import BaseModel, Field


class WeaponProfile(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    damage_dice: str = Field(min_length=2, max_length=20)
    versatile_damage_dice: str | None = Field(default=None, min_length=1, max_length=20)
    attack_ability: str | None = Field(default=None, max_length=10)
    damage_bonus: int | None = None
    reach: int | None = Field(default=None, ge=0)
    normal_range: int | None = Field(default=None, ge=0)
    long_range: int | None = Field(default=None, ge=0)
    proficient: bool = True
    finesse: bool = False
    ranged: bool = False
    thrown: bool = False
    light: bool = False
    loading: bool = False
    ammunition_item: str | None = Field(default=None, min_length=1, max_length=100)
    track_ammunition: bool = False
    mastery_property: str | None = Field(default=None, min_length=1, max_length=30)
    mastery_enabled: bool = False
    notes: str | None = None


class WeaponLoadout(BaseModel):
    primary: WeaponProfile | None = None
    secondary: WeaponProfile | None = None
    ranged: WeaponProfile | None = None
    active_slot: str = Field(default="primary", pattern="^(primary|secondary|ranged)$")
    shield_bonus: int = 0


class CharacterCreateRequest(BaseModel):
    campaign_id: int
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    class_name: str | None = None
    level: int = Field(default=1, ge=1, le=20)
    ancestry: str | None = None
    background: str | None = None
    current_hp: int = Field(default=1, ge=0)
    max_hp: int = Field(default=1, ge=1)
    armor_class: int | None = Field(default=None, ge=0)
    speed: int | None = Field(default=None, ge=0)
    proficiency_bonus: int = Field(default=2, ge=0, le=10)
    ability_modifiers: dict[str, int] = Field(default_factory=dict)
    equipped_weapon: WeaponProfile | None = None
    weapon_loadout: WeaponLoadout | None = None
    conditions: list[str] = Field(default_factory=list)
    spell_slots: dict[str, int] = Field(default_factory=dict)
    inventory_highlights: list[str] = Field(default_factory=list)
    notes: str | None = None


class CharacterUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    class_name: str | None = None
    level: int | None = Field(default=None, ge=1, le=20)
    ancestry: str | None = None
    background: str | None = None
    current_hp: int | None = Field(default=None, ge=0)
    max_hp: int | None = Field(default=None, ge=1)
    armor_class: int | None = Field(default=None, ge=0)
    speed: int | None = Field(default=None, ge=0)
    proficiency_bonus: int | None = Field(default=None, ge=0, le=10)
    ability_modifiers: dict[str, int] | None = None
    equipped_weapon: WeaponProfile | None = None
    weapon_loadout: WeaponLoadout | None = None
    clear_equipped_weapon: bool = False
    clear_weapon_loadout: bool = False
    conditions: list[str] | None = None
    spell_slots: dict[str, int] | None = None
    inventory_highlights: list[str] | None = None
    notes: str | None = None


class CharacterSummary(BaseModel):
    id: str
    campaign_id: int
    name: str
    class_name: str | None = None
    level: int
    ancestry: str | None = None
    background: str | None = None
    current_hp: int
    max_hp: int
    armor_class: int | None = None
    speed: int | None = None
    proficiency_bonus: int
    ability_modifiers: dict[str, int]
    equipped_weapon: WeaponProfile | None = None
    weapon_loadout: WeaponLoadout | None = None
    conditions: list[str]
    spell_slots: dict[str, int]
    inventory_highlights: list[str]
    notes: str | None = None


class PartyAssignRequest(BaseModel):
    campaign_id: int
    character_id: str
    party_order: int = Field(ge=1, le=4)


class PartyMemberSummary(BaseModel):
    campaign_id: int
    party_order: int
    character: CharacterSummary
