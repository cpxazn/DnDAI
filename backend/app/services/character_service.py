from __future__ import annotations

from sqlite3 import Connection

from backend.app.schemas.characters import CharacterCreateRequest, CharacterSummary, CharacterUpdateRequest
from backend.app.services.utils import json_dumps, json_loads, row_to_dict, utc_now


def _hydrate_character(row: dict) -> CharacterSummary:
    row["ability_modifiers"] = json_loads(row.pop("ability_modifiers_json"), {})
    weapon_loadout = json_loads(row.pop("weapon_loadout_json"), {})
    equipped_weapon = json_loads(row.pop("equipped_weapon_json"), {})
    row["weapon_loadout"] = weapon_loadout if weapon_loadout else None
    row["equipped_weapon"] = equipped_weapon if equipped_weapon else None
    row["conditions"] = json_loads(row.pop("conditions_json"), [])
    row["spell_slots"] = json_loads(row.pop("spell_slots_json"), {})
    row["inventory_highlights"] = json_loads(row.pop("inventory_highlights_json"), [])
    return CharacterSummary.model_validate(row)


def derive_effective_armor_class(*, armor_class: int | None, weapon_loadout: dict | None) -> int | None:
    if armor_class is None:
        return None
    if not isinstance(weapon_loadout, dict) or not weapon_loadout:
        return armor_class

    active_slot = weapon_loadout.get("active_slot", "primary")
    if active_slot == "ranged":
        return armor_class

    shield_bonus = weapon_loadout.get("shield_bonus", 0)
    if isinstance(shield_bonus, bool):
        return armor_class
    if not isinstance(shield_bonus, int):
        return armor_class
    if shield_bonus <= 0:
        return armor_class
    return armor_class + shield_bonus


def _character_select_sql() -> str:
    return """
        SELECT
          id,
          campaign_id,
          name,
          class_name,
          level,
          ancestry,
          background,
          current_hp,
          max_hp,
          armor_class,
          speed,
          proficiency_bonus,
          ability_modifiers_json,
          equipped_weapon_json,
          weapon_loadout_json,
          conditions_json,
          spell_slots_json,
          inventory_highlights_json,
          notes
    """


def list_characters(connection: Connection, campaign_id: int) -> list[CharacterSummary]:
    rows = connection.execute(
        f"""
        {_character_select_sql()}
        FROM characters
        WHERE campaign_id = ?
        ORDER BY name
        """,
        (campaign_id,),
    ).fetchall()
    return [_hydrate_character(row_to_dict(row)) for row in rows]


def create_character(connection: Connection, payload: CharacterCreateRequest) -> CharacterSummary:
    timestamp = utc_now()
    equipped_weapon = _derive_equipped_weapon(payload.equipped_weapon, payload.weapon_loadout)
    connection.execute(
        """
        INSERT INTO characters (
          id, campaign_id, name, class_name, level, ancestry, background,
          current_hp, max_hp, armor_class, speed, proficiency_bonus,
          ability_modifiers_json, equipped_weapon_json, weapon_loadout_json,
          conditions_json, spell_slots_json, inventory_highlights_json, notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.id,
            payload.campaign_id,
            payload.name.strip(),
            payload.class_name,
            payload.level,
            payload.ancestry,
            payload.background,
            payload.current_hp,
            payload.max_hp,
            payload.armor_class,
            payload.speed,
            payload.proficiency_bonus,
            json_dumps(payload.ability_modifiers),
            json_dumps(equipped_weapon),
            json_dumps(payload.weapon_loadout.model_dump() if payload.weapon_loadout else {}),
            json_dumps(payload.conditions),
            json_dumps(payload.spell_slots),
            json_dumps(payload.inventory_highlights),
            payload.notes,
            timestamp,
            timestamp,
        ),
    )
    row = connection.execute(
        f"""
        {_character_select_sql()}
        FROM characters
        WHERE id = ?
        """,
        (payload.id,),
    ).fetchone()
    return _hydrate_character(row_to_dict(row))


def update_character(
    connection: Connection,
    *,
    campaign_id: int,
    character_id: str,
    payload: CharacterUpdateRequest,
) -> CharacterSummary | None:
    existing = connection.execute(
        """
        SELECT *
        FROM characters
        WHERE id = ? AND campaign_id = ?
        """,
        (character_id, campaign_id),
    ).fetchone()
    if existing is None:
        return None

    updates = payload.model_dump(exclude_unset=True)
    assignments: list[str] = []
    values: list[object] = []

    scalar_fields = [
        "name",
        "class_name",
        "level",
        "ancestry",
        "background",
        "current_hp",
        "max_hp",
        "armor_class",
        "speed",
        "proficiency_bonus",
        "notes",
    ]
    for field in scalar_fields:
        if field not in updates:
            continue
        assignments.append(f"{field} = ?")
        value = updates[field]
        if field == "name" and isinstance(value, str):
            value = value.strip()
        values.append(value)

    json_fields = {
        "ability_modifiers": "ability_modifiers_json",
        "conditions": "conditions_json",
        "spell_slots": "spell_slots_json",
        "inventory_highlights": "inventory_highlights_json",
    }
    for payload_field, db_field in json_fields.items():
        if payload_field not in updates:
            continue
        assignments.append(f"{db_field} = ?")
        values.append(json_dumps(updates[payload_field]))

    if payload.clear_equipped_weapon:
        assignments.append("equipped_weapon_json = ?")
        values.append(json_dumps({}))
        if "clear_weapon_loadout" not in updates:
            assignments.append("weapon_loadout_json = ?")
            values.append(json_dumps({}))
    elif "equipped_weapon" in updates:
        assignments.append("equipped_weapon_json = ?")
        equipped_weapon = payload.equipped_weapon.model_dump() if payload.equipped_weapon else {}
        values.append(json_dumps(equipped_weapon))

    if payload.clear_weapon_loadout:
        assignments.append("weapon_loadout_json = ?")
        values.append(json_dumps({}))
        if "clear_equipped_weapon" not in updates and "equipped_weapon" not in updates:
            assignments.append("equipped_weapon_json = ?")
            values.append(json_dumps({}))
    elif "weapon_loadout" in updates:
        assignments.append("weapon_loadout_json = ?")
        loadout = payload.weapon_loadout.model_dump() if payload.weapon_loadout else {}
        values.append(json_dumps(loadout))
        if "equipped_weapon" not in updates and not payload.clear_equipped_weapon:
            assignments.append("equipped_weapon_json = ?")
            values.append(json_dumps(_derive_equipped_weapon(payload.equipped_weapon, payload.weapon_loadout)))

    if not assignments:
        row = connection.execute(
            f"""
            {_character_select_sql()}
            FROM characters
            WHERE id = ?
            """,
            (character_id,),
        ).fetchone()
        return _hydrate_character(row_to_dict(row))

    assignments.append("updated_at = ?")
    values.append(utc_now())
    values.extend([character_id, campaign_id])
    connection.execute(
        f"""
        UPDATE characters
        SET {", ".join(assignments)}
        WHERE id = ? AND campaign_id = ?
        """,
        values,
    )
    row = connection.execute(
        f"""
        {_character_select_sql()}
        FROM characters
        WHERE id = ?
        """,
        (character_id,),
    ).fetchone()
    return _hydrate_character(row_to_dict(row))


def _derive_equipped_weapon(equipped_weapon, weapon_loadout) -> dict:
    if equipped_weapon:
        return equipped_weapon.model_dump()
    if not weapon_loadout:
        return {}
    active_slot = weapon_loadout.active_slot
    active_weapon = getattr(weapon_loadout, active_slot, None)
    return active_weapon.model_dump() if active_weapon else {}


def set_active_weapon_slot(
    connection: Connection,
    *,
    campaign_id: int,
    character_id: str,
    active_slot: str,
) -> CharacterSummary | None:
    row = connection.execute(
        """
        SELECT weapon_loadout_json
        FROM characters
        WHERE id = ? AND campaign_id = ?
        """,
        (character_id, campaign_id),
    ).fetchone()
    if row is None:
        return None

    loadout = json_loads(row["weapon_loadout_json"], {})
    if not isinstance(loadout, dict) or not loadout:
        return None
    if active_slot not in {"primary", "secondary", "ranged"}:
        return None
    weapon = loadout.get(active_slot)
    if not isinstance(weapon, dict) or not weapon:
        return None

    loadout["active_slot"] = active_slot
    connection.execute(
        """
        UPDATE characters
        SET weapon_loadout_json = ?, equipped_weapon_json = ?, updated_at = ?
        WHERE id = ? AND campaign_id = ?
        """,
        (json_dumps(loadout), json_dumps(weapon), utc_now(), character_id, campaign_id),
    )
    updated = connection.execute(
        f"""
        {_character_select_sql()}
        FROM characters
        WHERE id = ?
        """,
        (character_id,),
    ).fetchone()
    return _hydrate_character(row_to_dict(updated)) if updated is not None else None
