from __future__ import annotations

import re
from sqlite3 import Connection

from backend.app.schemas.combat import CombatOperationRequest, CombatStateResponse, CombatantInput, CombatantSummary
from backend.app.services.character_service import derive_effective_armor_class
from backend.app.services.utils import json_dumps, json_loads, row_to_dict, utc_now


def get_active_combat(connection: Connection, campaign_id: int, session_id: int) -> CombatStateResponse | None:
    encounter = connection.execute(
        """
        SELECT id, campaign_id, session_id, status, name, round_number, turn_index
        FROM combat_encounters
        WHERE campaign_id = ? AND session_id = ? AND status = 'active'
        ORDER BY id DESC
        LIMIT 1
        """,
        (campaign_id, session_id),
    ).fetchone()
    if encounter is None:
        return None
    return _build_combat_state(connection, int(encounter["id"]))


def start_combat(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    name: str | None,
    combatants: list[CombatantInput],
) -> CombatStateResponse:
    current = get_active_combat(connection, campaign_id, session_id)
    if current is not None:
        return current

    cursor = connection.execute(
        """
        INSERT INTO combat_encounters (
          campaign_id, session_id, status, name, round_number, turn_index, started_at
        ) VALUES (?, ?, 'active', ?, 1, 0, ?)
        """,
        (campaign_id, session_id, name, utc_now()),
    )
    encounter_id = int(cursor.lastrowid)

    inputs = combatants or _default_party_combatants(connection, campaign_id)
    for combatant in inputs:
        _insert_combatant(connection, encounter_id, combatant)
    _sync_character_state_from_combatants(connection, encounter_id)
    return _build_combat_state(connection, encounter_id)


def end_combat(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    encounter_id: int | None = None,
    winning_side: str | None = None,
    outcome_summary: str | None = None,
) -> CombatStateResponse | None:
    if encounter_id is None:
        current = get_active_combat(connection, campaign_id, session_id)
        if current is None:
            return None
        encounter_id = current.encounter_id

    connection.execute(
        """
        UPDATE combat_encounters
        SET status = 'ended',
            ended_at = ?,
            winning_side = COALESCE(?, winning_side),
            outcome_summary = COALESCE(?, outcome_summary)
        WHERE id = ? AND campaign_id = ? AND session_id = ?
        """,
        (utc_now(), winning_side, outcome_summary, encounter_id, campaign_id, session_id),
    )
    return _build_combat_state(connection, encounter_id)


def advance_turn(
    connection: Connection,
    *,
    encounter_id: int,
) -> CombatStateResponse:
    state = _build_combat_state(connection, encounter_id)
    combatant_count = len(state.combatants)
    if combatant_count == 0:
        return state

    resolved = finalize_encounter_if_resolved(connection, encounter_id)
    if resolved is not None:
        return resolved
    if 0 <= state.turn_index < combatant_count:
        _tick_effects_for_combatant(connection, state.combatants[state.turn_index].id)

    conscious_indexes = [
        index
        for index, combatant in enumerate(state.combatants)
        if combatant.current_hp is None or combatant.current_hp > 0
    ]
    if not conscious_indexes:
        return state

    next_turn_index = state.turn_index
    next_round = state.round_number
    for _ in range(combatant_count):
        next_turn_index += 1
        if next_turn_index >= combatant_count:
            next_turn_index = 0
            next_round += 1
        candidate = state.combatants[next_turn_index]
        if candidate.current_hp is None or candidate.current_hp > 0:
            break

    connection.execute(
        """
        UPDATE combat_encounters
        SET turn_index = ?, round_number = ?
        WHERE id = ?
        """,
        (next_turn_index, next_round, encounter_id),
    )
    return _build_combat_state(connection, encounter_id)


def update_combatant_position(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    encounter_id: int,
    combatant_ref: str,
    position_x: int,
    position_y: int,
) -> CombatStateResponse:
    state = _build_combat_state(connection, encounter_id)
    if state.campaign_id != campaign_id or state.session_id != session_id:
        raise ValueError("encounter_id does not belong to the requested campaign and session.")
    if state.status != "active":
        raise ValueError("combatant positions can only be updated for an active encounter.")
    combatant = find_active_combatant(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        target_ref=combatant_ref,
    )
    if combatant is None or int(combatant["encounter_id"]) != encounter_id:
        raise ValueError("combatant_ref was not found in the active encounter.")
    connection.execute(
        """
        UPDATE combatants
        SET position_x = ?, position_y = ?
        WHERE id = ?
        """,
        (position_x, position_y, int(combatant["id"])),
    )
    return _build_combat_state(connection, encounter_id)


def get_active_encounter_id(connection: Connection, campaign_id: int, session_id: int) -> int | None:
    row = connection.execute(
        """
        SELECT id
        FROM combat_encounters
        WHERE campaign_id = ? AND session_id = ? AND status = 'active'
        ORDER BY id DESC
        LIMIT 1
        """,
        (campaign_id, session_id),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def apply_combat_operation(connection: Connection, payload: CombatOperationRequest) -> CombatStateResponse | None:
    if payload.operation == "start":
        return start_combat(
            connection,
            campaign_id=payload.campaign_id,
            session_id=payload.session_id,
            name=payload.name,
            combatants=payload.combatants,
        )
    if payload.operation == "end":
        return end_combat(
            connection,
            campaign_id=payload.campaign_id,
            session_id=payload.session_id,
            encounter_id=payload.encounter_id,
        )
    if payload.operation == "advance_turn":
        if payload.encounter_id is None:
            raise ValueError("encounter_id is required for advance_turn.")
        return advance_turn(connection, encounter_id=payload.encounter_id)
    if payload.operation == "update_position":
        if payload.encounter_id is None:
            raise ValueError("encounter_id is required for update_position.")
        if not payload.combatant_ref:
            raise ValueError("combatant_ref is required for update_position.")
        if payload.position_x is None or payload.position_y is None:
            raise ValueError("position_x and position_y are required for update_position.")
        return update_combatant_position(
            connection,
            campaign_id=payload.campaign_id,
            session_id=payload.session_id,
            encounter_id=payload.encounter_id,
            combatant_ref=payload.combatant_ref,
            position_x=payload.position_x,
            position_y=payload.position_y,
        )
    raise ValueError(f"Unsupported combat operation: {payload.operation}")


def find_active_combatant(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    target_ref: str,
) -> dict | None:
    encounter_id = get_active_encounter_id(connection, campaign_id, session_id)
    if encounter_id is None:
        return None

    normalized = target_ref.strip()
    if not normalized:
        return None

    rows = connection.execute(
        """
      SELECT
        c.id,
        c.encounter_id,
        c.source_character_id,
        c.name,
        c.initiative,
        c.current_hp,
        c.max_hp,
        c.base_armor_class,
        c.armor_class,
        c.base_speed,
        c.speed,
        c.size,
        c.saving_throw_bonuses_json,
        c.position_x,
        c.position_y,
        c.conditions_json,
        c.effects_json,
        c.is_player,
        c.party_order
        FROM combatants c
        WHERE c.encounter_id = ?
          AND (
            c.source_character_id = ?
            OR CAST(c.id AS TEXT) = ?
            OR LOWER(c.name) = LOWER(?)
          )
        """,
        (encounter_id, normalized, normalized, normalized),
    ).fetchall()
    if rows:
        return row_to_dict(rows[0])

    normalized_key = _normalize_combatant_ref(normalized)
    fuzzy_rows = connection.execute(
        """
      SELECT
        c.id,
        c.encounter_id,
        c.source_character_id,
        c.name,
        c.initiative,
        c.current_hp,
        c.max_hp,
        c.base_armor_class,
        c.armor_class,
        c.base_speed,
        c.speed,
        c.size,
        c.saving_throw_bonuses_json,
        c.position_x,
        c.position_y,
        c.conditions_json,
        c.effects_json,
        c.is_player,
        c.party_order
        FROM combatants c
        WHERE c.encounter_id = ?
        ORDER BY c.id
        """,
        (encounter_id,),
    ).fetchall()
    for row in fuzzy_rows:
        candidate = row_to_dict(row)
        if _normalize_combatant_ref(str(candidate["name"])) == normalized_key:
            return candidate
        if candidate["source_character_id"] and _normalize_combatant_ref(str(candidate["source_character_id"])) == normalized_key:
            return candidate
    return None


def is_active_turn_for_ref(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    actor_ref: str,
) -> bool:
    state = get_active_combat(connection, campaign_id, session_id)
    if state is None or state.active_combatant_id is None:
        return False
    combatant = find_active_combatant(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        target_ref=actor_ref,
    )
    if combatant is None:
        return False
    return int(combatant["id"]) == int(state.active_combatant_id)


def apply_damage_to_combatant(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    target_ref: str,
    amount: int,
) -> dict | None:
    combatant = find_active_combatant(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        target_ref=target_ref,
    )
    if combatant is None or amount <= 0:
        return None

    current_hp = combatant["current_hp"]
    if current_hp is None:
        return None
    new_hp = max(0, int(current_hp) - amount)
    connection.execute(
        """
        UPDATE combatants
        SET current_hp = ?
        WHERE id = ?
        """,
        (new_hp, combatant["id"]),
    )
    if combatant["source_character_id"]:
        connection.execute(
            """
            UPDATE characters
            SET current_hp = ?, updated_at = ?
            WHERE id = ? AND campaign_id = ?
            """,
            (new_hp, utc_now(), combatant["source_character_id"], campaign_id),
        )
    combatant["current_hp"] = new_hp
    return combatant


def add_combat_effect(
    connection: Connection,
    *,
    combatant_id: int,
    effect_name: str,
    effect_type: str,
    modifier: int = 0,
    duration_rounds: int | None = None,
    source_combatant_id: int | None = None,
    requires_concentration: bool = False,
) -> dict | None:
    row = connection.execute(
        """
        SELECT base_armor_class, base_speed, effects_json
        FROM combatants
        WHERE id = ?
        """,
        (combatant_id,),
    ).fetchone()
    if row is None:
        return None
    effects = json_loads(row["effects_json"], [])
    if not isinstance(effects, list):
        effects = []
    removed_concentration = []
    if requires_concentration and source_combatant_id is not None:
        removed_concentration = clear_concentration_effects_for_source(
            connection,
            source_combatant_id=source_combatant_id,
        )
        row = connection.execute(
            """
            SELECT base_armor_class, base_speed, effects_json
            FROM combatants
            WHERE id = ?
            """,
            (combatant_id,),
        ).fetchone()
        if row is None:
            return None
        effects = json_loads(row["effects_json"], [])
        if not isinstance(effects, list):
            effects = []
    effects.append(
        {
            "name": effect_name,
            "type": effect_type,
            "modifier": modifier,
            "duration_rounds": duration_rounds,
            "source_combatant_id": source_combatant_id,
            "requires_concentration": requires_concentration,
        }
    )
    armor_class = _calculate_effective_armor_class(row["base_armor_class"], effects)
    speed = _calculate_effective_speed(row["base_speed"], effects)
    connection.execute(
        """
        UPDATE combatants
        SET effects_json = ?, armor_class = ?, speed = ?
        WHERE id = ?
        """,
        (json_dumps(effects), armor_class, speed, combatant_id),
    )
    return {
        "combatant_id": combatant_id,
        "armor_class": armor_class,
        "speed": speed,
        "effects": effects,
        "removed_concentration": removed_concentration,
    }


def remove_combat_effect(connection: Connection, *, combatant_id: int, effect_name: str) -> dict | None:
    row = connection.execute(
        """
        SELECT base_armor_class, base_speed, effects_json
        FROM combatants
        WHERE id = ?
        """,
        (combatant_id,),
    ).fetchone()
    if row is None:
        return None
    effects = json_loads(row["effects_json"], [])
    if not isinstance(effects, list):
        effects = []
    remaining = [effect for effect in effects if str(effect.get("name", "")).strip().lower() != effect_name.strip().lower()]
    if len(remaining) == len(effects):
        return None
    armor_class = _calculate_effective_armor_class(row["base_armor_class"], remaining)
    speed = _calculate_effective_speed(row["base_speed"], remaining)
    connection.execute(
        """
        UPDATE combatants
        SET effects_json = ?, armor_class = ?, speed = ?
        WHERE id = ?
        """,
        (json_dumps(remaining), armor_class, speed, combatant_id),
    )
    return {"combatant_id": combatant_id, "armor_class": armor_class, "speed": speed, "effects": remaining}


def get_combatant_effect_modifier(combatant: dict | None, effect_type: str) -> int:
    if combatant is None:
        return 0
    effects = json_loads(combatant.get("effects_json"), []) if isinstance(combatant, dict) else []
    if not isinstance(effects, list):
        return 0
    total = 0
    normalized_type = effect_type.strip().lower()
    for effect in effects:
        if not isinstance(effect, dict):
            continue
        if str(effect.get("type", "")).strip().lower() != normalized_type:
            continue
        modifier = effect.get("modifier", 0)
        if isinstance(modifier, int) and not isinstance(modifier, bool):
            total += modifier
    return total


def clear_concentration_effects_for_source(connection: Connection, *, source_combatant_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT id, base_armor_class, base_speed, effects_json
        FROM combatants
        """
    ).fetchall()
    removed: list[dict] = []
    for row in rows:
        effects = json_loads(row["effects_json"], [])
        if not isinstance(effects, list) or not effects:
            continue
        remaining: list[dict] = []
        removed_here: list[dict] = []
        for effect in effects:
            if not isinstance(effect, dict):
                continue
            if (
                bool(effect.get("requires_concentration"))
                and effect.get("source_combatant_id") == source_combatant_id
            ):
                removed_here.append(effect)
                continue
            remaining.append(effect)
        if not removed_here:
            continue
        connection.execute(
            """
            UPDATE combatants
            SET effects_json = ?, armor_class = ?, speed = ?
            WHERE id = ?
            """,
            (
                json_dumps(remaining),
                _calculate_effective_armor_class(row["base_armor_class"], remaining),
                _calculate_effective_speed(row["base_speed"], remaining),
                row["id"],
            ),
        )
        removed.append(
            {
                "combatant_id": row["id"],
                "effects": removed_here,
            }
        )
    return removed


def finalize_encounter_if_resolved(connection: Connection, encounter_id: int) -> CombatStateResponse | None:
    current_state = _build_combat_state(connection, encounter_id)
    if current_state.status != "active":
        return current_state if current_state.winning_side or current_state.outcome_summary else None
    outcome = determine_encounter_outcome(connection, encounter_id)
    if outcome is None:
        return None
    connection.execute(
        """
        UPDATE combat_encounters
        SET status = 'ended', ended_at = ?, winning_side = ?, outcome_summary = ?
        WHERE id = ?
        """,
        (utc_now(), outcome["winning_side"], outcome["outcome_summary"], encounter_id),
    )
    return _build_combat_state(connection, encounter_id)


def determine_encounter_outcome(connection: Connection, encounter_id: int) -> dict[str, str] | None:
    rows = connection.execute(
        """
        SELECT is_player, current_hp
        FROM combatants
        WHERE encounter_id = ?
        """,
        (encounter_id,),
    ).fetchall()
    if not rows:
        return None

    players_alive = False
    enemies_alive = False
    for row in rows:
        current_hp = row["current_hp"]
        alive = current_hp is None or int(current_hp) > 0
        if not alive:
            continue
        if bool(row["is_player"]):
            players_alive = True
        else:
            enemies_alive = True

    if players_alive and enemies_alive:
        return None
    if players_alive:
        return {
            "winning_side": "players",
            "outcome_summary": "Players defeated all hostile combatants.",
        }
    if enemies_alive:
        return {
            "winning_side": "enemies",
            "outcome_summary": "Enemies defeated the party.",
        }
    return {
        "winning_side": "stalemate",
        "outcome_summary": "No conscious combatants remain.",
    }


def _build_combat_state(connection: Connection, encounter_id: int) -> CombatStateResponse:
    encounter = connection.execute(
        """
        SELECT id, campaign_id, session_id, status, name, round_number, turn_index, winning_side, outcome_summary
        FROM combat_encounters
        WHERE id = ?
        """,
        (encounter_id,),
    ).fetchone()
    if encounter is None:
        raise ValueError("Combat encounter not found.")

    rows = connection.execute(
        """
      SELECT
        id,
        source_character_id,
        name,
        initiative,
        current_hp,
        max_hp,
        base_armor_class,
        armor_class,
        base_speed,
        speed,
        size,
        saving_throw_bonuses_json,
        position_x,
        position_y,
        conditions_json,
        effects_json,
        is_player,
        party_order
        FROM combatants
        WHERE encounter_id = ?
        ORDER BY
          CASE WHEN initiative IS NULL THEN 1 ELSE 0 END,
          initiative DESC,
          CASE WHEN party_order IS NULL THEN 1 ELSE 0 END,
          party_order ASC,
          id ASC
        """,
        (encounter_id,),
    ).fetchall()
    combatants = [
        CombatantSummary(
            id=int(row["id"]),
            source_character_id=row["source_character_id"],
            name=row["name"],
            initiative=row["initiative"],
            current_hp=row["current_hp"],
            max_hp=row["max_hp"],
            base_armor_class=row["base_armor_class"],
            armor_class=row["armor_class"],
            base_speed=row["base_speed"],
            speed=row["speed"],
            size=row["size"],
            saving_throw_bonuses=json_loads(row["saving_throw_bonuses_json"], {}),
            position_x=row["position_x"],
            position_y=row["position_y"],
            conditions=json_loads(row["conditions_json"], []),
            effects=json_loads(row["effects_json"], []),
            is_player=bool(row["is_player"]),
            party_order=row["party_order"],
        )
        for row in rows
    ]
    turn_index = int(encounter["turn_index"])
    active_combatant_id = combatants[turn_index].id if 0 <= turn_index < len(combatants) else None
    return CombatStateResponse(
        encounter_id=int(encounter["id"]),
        campaign_id=int(encounter["campaign_id"]),
        session_id=int(encounter["session_id"]),
        status=str(encounter["status"]),
        name=encounter["name"],
        round_number=int(encounter["round_number"]),
        turn_index=turn_index,
        active_combatant_id=active_combatant_id,
        winning_side=encounter["winning_side"],
        outcome_summary=encounter["outcome_summary"],
        combatants=combatants,
    )


def _default_party_combatants(connection: Connection, campaign_id: int) -> list[CombatantInput]:
    rows = connection.execute(
        """
        SELECT
          c.id,
          c.name,
          c.class_name,
          c.current_hp,
          c.max_hp,
          c.armor_class,
          c.speed,
          c.proficiency_bonus,
          c.weapon_loadout_json,
          c.ability_modifiers_json,
          c.conditions_json,
          pm.party_order
        FROM party_members pm
        JOIN characters c ON c.id = pm.character_id
        WHERE pm.campaign_id = ? AND pm.is_active = 1
        ORDER BY pm.party_order
        """,
        (campaign_id,),
    ).fetchall()
    return [
        CombatantInput(
            source_character_id=row["id"],
            name=row["name"],
            current_hp=row["current_hp"],
            max_hp=row["max_hp"],
            armor_class=derive_effective_armor_class(
                armor_class=row["armor_class"],
                weapon_loadout=json_loads(row["weapon_loadout_json"], {}),
            ),
            speed=row["speed"],
            size="Medium",
            saving_throw_bonuses=_default_saving_throw_bonuses_from_character(
                row["ability_modifiers_json"],
                class_name=row["class_name"],
                proficiency_bonus=row["proficiency_bonus"],
            ),
            conditions=json_loads(row["conditions_json"], []),
            is_player=True,
            party_order=row["party_order"],
        )
        for row in rows
    ]


def _insert_combatant(connection: Connection, encounter_id: int, combatant: CombatantInput) -> None:
    base_armor_class = combatant.armor_class
    saving_throw_bonuses = _resolve_combatant_input_saving_throw_bonuses(connection, combatant)
    connection.execute(
        """
        INSERT INTO combatants (
          encounter_id, source_character_id, name, initiative, current_hp, max_hp,
          base_armor_class, armor_class, base_speed, speed, size, saving_throw_bonuses_json, position_x, position_y, conditions_json, effects_json, is_player, party_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            encounter_id,
            combatant.source_character_id,
            combatant.name,
            combatant.initiative,
            combatant.current_hp,
            combatant.max_hp,
            base_armor_class,
            combatant.armor_class,
            combatant.speed,
            combatant.speed,
            combatant.size,
            json_dumps(saving_throw_bonuses),
            combatant.position_x,
            combatant.position_y,
            json_dumps(combatant.conditions),
            json_dumps([]),
            1 if combatant.is_player else 0,
            combatant.party_order,
        ),
    )


def sync_character_to_active_combatant(connection: Connection, campaign_id: int, session_id: int, character_id: str) -> None:
    encounter_id = get_active_encounter_id(connection, campaign_id, session_id)
    if encounter_id is None:
        return
    character = connection.execute(
        """
        SELECT current_hp, max_hp, armor_class, speed, weapon_loadout_json, conditions_json
        FROM characters
        WHERE id = ? AND campaign_id = ?
        """,
        (character_id, campaign_id),
    ).fetchone()
    if character is None:
        return
    current = connection.execute(
        """
        SELECT effects_json
        FROM combatants
        WHERE encounter_id = ? AND source_character_id = ?
        """,
        (encounter_id, character_id),
    ).fetchone()
    effects = json_loads(current["effects_json"], []) if current is not None else []
    base_armor_class = derive_effective_armor_class(
        armor_class=character["armor_class"],
        weapon_loadout=json_loads(character["weapon_loadout_json"], {}),
    )
    connection.execute(
        """
        UPDATE combatants
        SET current_hp = ?, max_hp = ?, base_armor_class = ?, armor_class = ?, base_speed = ?, speed = ?, conditions_json = ?
        WHERE encounter_id = ? AND source_character_id = ?
        """,
        (
            character["current_hp"],
            character["max_hp"],
            base_armor_class,
            _calculate_effective_armor_class(base_armor_class, effects),
            character["speed"],
            _calculate_effective_speed(character["speed"], effects),
            character["conditions_json"],
            encounter_id,
            character_id,
        ),
    )


def _sync_character_state_from_combatants(connection: Connection, encounter_id: int) -> None:
    rows = connection.execute(
        """
        SELECT source_character_id, current_hp, max_hp, conditions_json
        FROM combatants
        WHERE encounter_id = ? AND source_character_id IS NOT NULL
        """,
        (encounter_id,),
    ).fetchall()
    for row in rows:
        connection.execute(
            """
            UPDATE characters
            SET current_hp = COALESCE(?, current_hp),
                max_hp = COALESCE(?, max_hp),
                conditions_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                row["current_hp"],
                row["max_hp"],
                row["conditions_json"],
                utc_now(),
                row["source_character_id"],
            ),
        )


def _normalize_combatant_ref(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"^(npc|pc)", "", lowered)
    lowered = re.sub(r"[_\-\s]+", "", lowered)
    lowered = re.sub(r"\d+$", "", lowered)
    lowered = re.sub(r"[^a-z0-9]", "", lowered)
    return lowered


CLASS_SAVE_PROFICIENCIES = {
    "barbarian": {"STR", "CON"},
    "bard": {"DEX", "CHA"},
    "cleric": {"WIS", "CHA"},
    "druid": {"INT", "WIS"},
    "fighter": {"STR", "CON"},
    "monk": {"STR", "DEX"},
    "paladin": {"WIS", "CHA"},
    "ranger": {"STR", "DEX"},
    "rogue": {"DEX", "INT"},
    "sorcerer": {"CON", "CHA"},
    "warlock": {"WIS", "CHA"},
    "wizard": {"INT", "WIS"},
}


ABILITY_SYMBOLS = ("STR", "DEX", "CON", "INT", "WIS", "CHA")


def _default_saving_throw_bonuses_from_character(
    ability_modifiers_json: str | None,
    *,
    class_name: str | None = None,
    proficiency_bonus: int | None = None,
) -> dict[str, int]:
    loaded = json_loads(ability_modifiers_json, {})
    if not isinstance(loaded, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        normalized[key.strip().upper()] = value
    save_proficiencies = _default_save_proficiencies_for_class(class_name)
    resolved_proficiency_bonus = int(proficiency_bonus or 0)
    if save_proficiencies and resolved_proficiency_bonus > 0:
        for ability_symbol in save_proficiencies:
            if ability_symbol in normalized:
                normalized[ability_symbol] += resolved_proficiency_bonus
    return normalized


def _default_save_proficiencies_for_class(class_name: str | None) -> set[str]:
    if not isinstance(class_name, str):
        return set()
    return CLASS_SAVE_PROFICIENCIES.get(class_name.strip().lower(), set())


def _resolve_combatant_input_saving_throw_bonuses(connection: Connection, combatant: CombatantInput) -> dict[str, int]:
    if combatant.saving_throw_bonuses:
        return dict(combatant.saving_throw_bonuses)
    if not combatant.source_character_id:
        return {ability: 0 for ability in ABILITY_SYMBOLS}
    row = connection.execute(
        """
        SELECT class_name, proficiency_bonus, ability_modifiers_json
        FROM characters
        WHERE id = ?
        """,
        (combatant.source_character_id,),
    ).fetchone()
    if row is None:
        return {}
    return _default_saving_throw_bonuses_from_character(
        row["ability_modifiers_json"],
        class_name=row["class_name"],
        proficiency_bonus=row["proficiency_bonus"],
    )


def _calculate_effective_armor_class(base_armor_class: int | None, effects: list[dict]) -> int | None:
    if base_armor_class is None:
        return None
    total = int(base_armor_class)
    floors: list[int] = []
    for effect in effects:
        if not isinstance(effect, dict):
            continue
        effect_type = str(effect.get("type", "")).strip().lower()
        modifier = effect.get("modifier", 0)
        if not isinstance(modifier, int) or isinstance(modifier, bool):
            continue
        if effect_type == "ac_bonus":
            total += modifier
        elif effect_type == "ac_floor":
            floors.append(modifier)
    if floors:
        total = max(total, max(floors))
    return total


def _calculate_effective_speed(base_speed: int | None, effects: list[dict]) -> int | None:
    if base_speed is None:
        return None
    total = int(base_speed)
    for effect in effects:
        if not isinstance(effect, dict):
            continue
        effect_type = str(effect.get("type", "")).strip().lower()
        if effect_type not in {"speed_bonus", "speed_penalty", "mastery_slow_speed_penalty"}:
            continue
        modifier = effect.get("modifier", 0)
        if isinstance(modifier, int) and not isinstance(modifier, bool):
            total += modifier
    return max(0, total)


def _tick_effects_for_combatant(connection: Connection, combatant_id: int) -> None:
    row = connection.execute(
        """
        SELECT base_armor_class, base_speed, effects_json
        FROM combatants
        WHERE id = ?
        """,
        (combatant_id,),
    ).fetchone()
    if row is None:
        return
    effects = json_loads(row["effects_json"], [])
    if not isinstance(effects, list) or not effects:
        return
    remaining: list[dict] = []
    changed = False
    for effect in effects:
        if not isinstance(effect, dict):
            changed = True
            continue
        duration = effect.get("duration_rounds")
        if duration is None:
            remaining.append(effect)
            continue
        if not isinstance(duration, int):
            changed = True
            continue
        next_duration = duration - 1
        changed = True
        if next_duration > 0:
            updated = dict(effect)
            updated["duration_rounds"] = next_duration
            remaining.append(updated)
    if not changed:
        return
    connection.execute(
        """
        UPDATE combatants
        SET effects_json = ?, armor_class = ?, speed = ?
        WHERE id = ?
        """,
        (
            json_dumps(remaining),
            _calculate_effective_armor_class(row["base_armor_class"], remaining),
            _calculate_effective_speed(row["base_speed"], remaining),
            combatant_id,
        ),
    )
