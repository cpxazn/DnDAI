from __future__ import annotations

from dataclasses import dataclass
import math
import re
from sqlite3 import Connection

from backend.app.schemas.chat import AppliedAction, ProposedAction, RejectedAction
from backend.app.schemas.combat import CombatantInput
from backend.app.services.combat_service import (
    add_combat_effect,
    apply_damage_to_combatant,
    advance_turn,
    clear_concentration_effects_for_source,
    finalize_encounter_if_resolved,
    end_combat,
    find_active_combatant,
    get_combatant_effect_modifier,
    get_active_encounter_id,
    is_active_turn_for_ref,
    remove_combat_effect,
    start_combat,
    sync_character_to_active_combatant,
)
from backend.app.services.inventory_service import add_item, remove_item
from backend.app.services.quest_service import create_quest, update_quest_status
from backend.app.services.character_service import set_active_weapon_slot
from backend.app.services.utils import json_dumps, json_loads, utc_now


SUPPORTED_ACTION_TYPES = {
    "attack_roll",
    "apply_damage",
    "apply_healing",
    "add_condition",
    "remove_condition",
    "spend_spell_slot",
    "restore_spell_slot",
    "add_inventory_item",
    "remove_inventory_item",
    "recover_ammunition",
    "create_quest",
    "advance_quest",
    "complete_quest",
    "set_location",
    "advance_turn",
    "set_active_weapon_slot",
    "add_combat_effect",
    "remove_combat_effect",
    "cast_shield_of_faith",
    "cast_barkskin",
    "cast_shield",
    "start_combat",
    "end_combat",
}


SHIELD_OF_FAITH_RANGE_FEET = 60
BARKSKIN_TOUCH_RANGE_FEET = 5
BARKSKIN_AC_FLOOR = 17
SHIELD_AC_BONUS = 5


SRD_WEAPON_FALLBACK_PROFILES = {
    "battleaxe": {"name": "Battleaxe", "damage_dice": "1d8", "versatile_damage_dice": "1d10", "attack_ability": "STR"},
    "blowgun": {"name": "Blowgun", "damage_dice": "1", "attack_ability": "DEX", "ranged": True, "normal_range": 25, "long_range": 100, "loading": True, "ammunition_item": "Needle"},
    "club": {"name": "Club", "damage_dice": "1d4", "attack_ability": "STR", "light": True},
    "dagger": {"name": "Dagger", "damage_dice": "1d4", "finesse": True, "thrown": True, "light": True, "normal_range": 20, "long_range": 60},
    "dart": {"name": "Dart", "damage_dice": "1d4", "finesse": True, "ranged": True, "thrown": True, "normal_range": 20, "long_range": 60},
    "flail": {"name": "Flail", "damage_dice": "1d8", "attack_ability": "STR"},
    "glaive": {"name": "Glaive", "damage_dice": "1d10", "attack_ability": "STR", "reach": 10},
    "greataxe": {"name": "Greataxe", "damage_dice": "1d12", "attack_ability": "STR"},
    "greatclub": {"name": "Greatclub", "damage_dice": "1d8", "attack_ability": "STR"},
    "greatsword": {"name": "Greatsword", "damage_dice": "2d6", "attack_ability": "STR"},
    "halberd": {"name": "Halberd", "damage_dice": "1d10", "attack_ability": "STR", "reach": 10},
    "hand crossbow": {"name": "Hand Crossbow", "damage_dice": "1d6", "attack_ability": "DEX", "ranged": True, "normal_range": 30, "long_range": 120, "loading": True, "ammunition_item": "Bolt"},
    "handaxe": {"name": "Handaxe", "damage_dice": "1d6", "attack_ability": "STR", "thrown": True, "light": True, "normal_range": 20, "long_range": 60},
    "heavy crossbow": {"name": "Heavy Crossbow", "damage_dice": "1d10", "attack_ability": "DEX", "ranged": True, "normal_range": 100, "long_range": 400, "loading": True, "ammunition_item": "Bolt"},
    "javelin": {"name": "Javelin", "damage_dice": "1d6", "attack_ability": "STR", "thrown": True, "normal_range": 30, "long_range": 120},
    "lance": {"name": "Lance", "damage_dice": "1d10", "attack_ability": "STR", "reach": 10},
    "light crossbow": {"name": "Light Crossbow", "damage_dice": "1d8", "attack_ability": "DEX", "ranged": True, "normal_range": 80, "long_range": 320, "loading": True, "ammunition_item": "Bolt"},
    "light hammer": {"name": "Light Hammer", "damage_dice": "1d4", "attack_ability": "STR", "thrown": True, "light": True, "normal_range": 20, "long_range": 60},
    "longbow": {"name": "Longbow", "damage_dice": "1d8", "attack_ability": "DEX", "ranged": True, "normal_range": 150, "long_range": 600, "ammunition_item": "Arrow"},
    "longsword": {"name": "Longsword", "damage_dice": "1d8", "versatile_damage_dice": "1d10", "attack_ability": "STR"},
    "mace": {"name": "Mace", "damage_dice": "1d6", "attack_ability": "STR"},
    "maul": {"name": "Maul", "damage_dice": "2d6", "attack_ability": "STR"},
    "morningstar": {"name": "Morningstar", "damage_dice": "1d8", "attack_ability": "STR"},
    "musket": {"name": "Musket", "damage_dice": "1d12", "attack_ability": "DEX", "ranged": True, "normal_range": 40, "long_range": 120, "loading": True, "ammunition_item": "Bullet"},
    "pike": {"name": "Pike", "damage_dice": "1d10", "attack_ability": "STR", "reach": 10},
    "pistol": {"name": "Pistol", "damage_dice": "1d10", "attack_ability": "DEX", "ranged": True, "normal_range": 30, "long_range": 90, "loading": True, "ammunition_item": "Bullet"},
    "quarterstaff": {"name": "Quarterstaff", "damage_dice": "1d6", "versatile_damage_dice": "1d8", "attack_ability": "STR"},
    "rapier": {"name": "Rapier", "damage_dice": "1d8", "attack_ability": "DEX", "finesse": True},
    "scimitar": {"name": "Scimitar", "damage_dice": "1d6", "attack_ability": "DEX", "finesse": True, "light": True},
    "shortbow": {"name": "Shortbow", "damage_dice": "1d6", "attack_ability": "DEX", "ranged": True, "normal_range": 80, "long_range": 320, "ammunition_item": "Arrow"},
    "shortsword": {"name": "Shortsword", "damage_dice": "1d6", "attack_ability": "DEX", "finesse": True, "light": True},
    "sickle": {"name": "Sickle", "damage_dice": "1d4", "attack_ability": "STR", "light": True},
    "sling": {"name": "Sling", "damage_dice": "1d4", "attack_ability": "DEX", "ranged": True, "normal_range": 30, "long_range": 120, "ammunition_item": "Bullet"},
    "spear": {"name": "Spear", "damage_dice": "1d6", "versatile_damage_dice": "1d8", "attack_ability": "STR", "thrown": True, "normal_range": 20, "long_range": 60},
    "trident": {"name": "Trident", "damage_dice": "1d8", "versatile_damage_dice": "1d10", "attack_ability": "STR", "thrown": True, "normal_range": 20, "long_range": 60},
    "war pick": {"name": "War Pick", "damage_dice": "1d8", "versatile_damage_dice": "1d10", "attack_ability": "STR"},
    "warhammer": {"name": "Warhammer", "damage_dice": "1d8", "versatile_damage_dice": "1d10", "attack_ability": "STR"},
    "whip": {"name": "Whip", "damage_dice": "1d4", "attack_ability": "DEX", "finesse": True, "reach": 10},
}


SRD_WEAPON_MASTERY_PROPERTIES = {
    "battleaxe": "topple",
    "blowgun": "vex",
    "club": "slow",
    "dagger": "nick",
    "dart": "vex",
    "flail": "sap",
    "glaive": "graze",
    "greataxe": "cleave",
    "greatclub": "push",
    "greatsword": "graze",
    "halberd": "cleave",
    "hand crossbow": "vex",
    "handaxe": "vex",
    "heavy crossbow": "push",
    "javelin": "slow",
    "lance": "topple",
    "light crossbow": "slow",
    "light hammer": "nick",
    "longbow": "slow",
    "longsword": "sap",
    "mace": "sap",
    "maul": "topple",
    "morningstar": "sap",
    "musket": "slow",
    "pike": "push",
    "pistol": "vex",
    "quarterstaff": "topple",
    "rapier": "vex",
    "scimitar": "nick",
    "shortbow": "vex",
    "shortsword": "vex",
    "sickle": "nick",
    "sling": "slow",
    "spear": "sap",
    "trident": "topple",
    "war pick": "sap",
    "warhammer": "push",
    "whip": "slow",
}


@dataclass
class AppliedActionResult:
    applied_actions: list[AppliedAction]
    rejected_actions: list[RejectedAction]
    changed_entities: list[str]


def apply_actions(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    turn_id: int,
    actions: list[ProposedAction],
) -> AppliedActionResult:
    applied_actions: list[AppliedAction] = []
    rejected_actions: list[RejectedAction] = []
    changed_entities: list[str] = []
    event_index = 1

    for action in actions:
        if action.type not in SUPPORTED_ACTION_TYPES:
            rejected_actions.append(_reject(action, "Unsupported action type."))
            continue

        if action.type == "attack_roll":
            event_index = _apply_attack_roll_action(
                connection=connection,
                campaign_id=campaign_id,
                session_id=session_id,
                turn_id=turn_id,
                action=action,
                event_index=event_index,
                applied_actions=applied_actions,
                rejected_actions=rejected_actions,
                changed_entities=changed_entities,
            )
            continue

        if action.type in {"apply_damage", "apply_healing", "add_condition", "remove_condition", "spend_spell_slot", "restore_spell_slot"}:
            event_index = _apply_character_action(
                connection=connection,
                campaign_id=campaign_id,
                session_id=session_id,
                turn_id=turn_id,
                action=action,
                event_index=event_index,
                applied_actions=applied_actions,
                rejected_actions=rejected_actions,
                changed_entities=changed_entities,
            )
            continue

        if action.type in {"add_inventory_item", "remove_inventory_item", "recover_ammunition", "create_quest", "advance_quest", "complete_quest"}:
            event_index = _apply_inventory_or_quest_action(
                connection=connection,
                campaign_id=campaign_id,
                session_id=session_id,
                turn_id=turn_id,
                action=action,
                event_index=event_index,
                applied_actions=applied_actions,
                rejected_actions=rejected_actions,
                changed_entities=changed_entities,
            )
            continue

        if action.type == "set_location":
            event_index = _apply_campaign_action(
                connection=connection,
                campaign_id=campaign_id,
                session_id=session_id,
                turn_id=turn_id,
                action=action,
                event_index=event_index,
                applied_actions=applied_actions,
                rejected_actions=rejected_actions,
            )
            continue

        if action.type in {
            "advance_turn",
            "set_active_weapon_slot",
            "add_combat_effect",
            "remove_combat_effect",
            "cast_shield_of_faith",
            "cast_barkskin",
            "cast_shield",
        }:
            event_index = _apply_combat_utility_action(
                connection=connection,
                campaign_id=campaign_id,
                session_id=session_id,
                turn_id=turn_id,
                action=action,
                event_index=event_index,
                applied_actions=applied_actions,
                rejected_actions=rejected_actions,
            )
            continue

        if action.type in {"start_combat", "end_combat"}:
            event_index = _apply_combat_action(
                connection=connection,
                campaign_id=campaign_id,
                session_id=session_id,
                turn_id=turn_id,
                action=action,
                event_index=event_index,
                applied_actions=applied_actions,
                rejected_actions=rejected_actions,
            )
            continue

    return AppliedActionResult(
        applied_actions=applied_actions,
        rejected_actions=rejected_actions,
        changed_entities=changed_entities,
    )


def _apply_attack_roll_action(
    *,
    connection: Connection,
    campaign_id: int,
    session_id: int,
    turn_id: int,
    action: ProposedAction,
    event_index: int,
    applied_actions: list[AppliedAction],
    rejected_actions: list[RejectedAction],
    changed_entities: list[str],
) -> int:
    target_ids = action.target_ids
    if not target_ids:
        rejected_actions.append(_reject(action, "attack_roll requires a target combatant or character reference."))
        return event_index
    if action.actor_id and get_active_encounter_id(connection, campaign_id, session_id) is not None:
        if not is_active_turn_for_ref(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            actor_ref=action.actor_id,
        ):
            rejected_actions.append(_reject(action, "attack_roll can only be used by the active combatant during combat."))
            return event_index

    actor_character = _get_character(connection, action.actor_id, campaign_id) if action.actor_id else None
    actor_combatant = (
        find_active_combatant(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            target_ref=action.actor_id,
        )
        if action.actor_id
        else None
    )
    if _combatant_has_incapacitating_condition(actor_combatant):
        rejected_actions.append(_reject(action, "attack_roll cannot be used while the acting combatant is incapacitated."))
        return event_index
    target_ref = target_ids[0]
    combatant = find_active_combatant(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        target_ref=target_ref,
    )
    if combatant is None:
        rejected_actions.append(_reject(action, "Target combatant was not found in the active encounter."))
        return event_index
    if combatant["armor_class"] is None:
        rejected_actions.append(_reject(action, "Target combatant has no armor class to resolve against."))
        return event_index

    prior_attack_details = _find_prior_attack_details(connection, turn_id=turn_id, actor_id=action.actor_id) if action.actor_id else []
    turn_attack_state_before = _summarize_turn_attack_state(prior_attack_details, actor_character=actor_character)
    weapon = _coerce_text(action.parameters.get("weapon"))
    weapon_profile = _resolve_weapon_profile(weapon, actor_character)
    mastery_property = _resolve_mastery_property(weapon_profile)
    light_extra_attack = _resolve_light_extra_attack(
        prior_attack_details=prior_attack_details,
        action=action,
        weapon_profile=weapon_profile,
    )
    attack_timing = _resolve_attack_timing(action, light_extra_attack=light_extra_attack, mastery_property=mastery_property)
    encounter_id = int(actor_combatant["encounter_id"]) if actor_combatant is not None else int(combatant["encounter_id"])
    if light_extra_attack:
        light_validation_reason = _validate_light_extra_attack(
            actor_id=action.actor_id,
            prior_attack_details=prior_attack_details,
            weapon_profile=weapon_profile,
            mastery_property=mastery_property,
            attack_timing=attack_timing,
        )
        if light_validation_reason is not None:
            rejected_actions.append(_reject(action, light_validation_reason))
            return event_index
    attack_action_slot_reason = _validate_attack_action_slot(
        actor_character=actor_character,
        prior_attack_details=prior_attack_details,
        attack_timing=attack_timing,
        light_extra_attack=light_extra_attack,
    )
    if attack_action_slot_reason is not None:
        rejected_actions.append(_reject(action, attack_action_slot_reason))
        return event_index
    attack_timing_slot_reason = _validate_attack_timing_slot(
        prior_attack_details=prior_attack_details,
        attack_timing=attack_timing,
    )
    if attack_timing_slot_reason is not None:
        rejected_actions.append(_reject(action, attack_timing_slot_reason))
        return event_index
    ammunition_item = _resolve_ammunition_item(weapon_profile)
    if _is_loading_weapon_attack_blocked(
        prior_attack_details=prior_attack_details,
        weapon_profile=weapon_profile,
        attack_timing=attack_timing,
    ):
        rejected_actions.append(
            _reject(
                action,
                f"Loading weapons can be fired only once per {attack_timing.replace('_', ' ')}.",
            )
        )
        return event_index
    track_ammunition = actor_character is not None and _should_track_ammunition(weapon_profile) and ammunition_item is not None
    if track_ammunition and ammunition_item:
        ammo_available = _get_inventory_quantity(connection, character_id=action.actor_id or "", item_name=ammunition_item)
        if ammo_available < 1:
            rejected_actions.append(
                _reject(
                    action,
                    f"attack_roll requires at least 1 {ammunition_item} for the selected weapon.",
                )
            )
            return event_index
    attack_bonus, attack_bonus_reason = _resolve_attack_bonus(action, actor_character)
    if attack_bonus is None:
        rejected_actions.append(_reject(action, attack_bonus_reason or "Could not resolve attack bonus."))
        return event_index
    attack_bonus += get_combatant_effect_modifier(actor_combatant, "attack_bonus")

    damage_spec, damage_reason = _resolve_damage_spec(
        action,
        actor_character,
        suppress_positive_ability_modifier=light_extra_attack,
    )
    if damage_spec is None:
        rejected_actions.append(_reject(action, damage_reason or "Could not resolve damage amount."))
        return event_index
    damage_bonus_modifier = get_combatant_effect_modifier(actor_combatant, "damage_bonus")
    target_distance_feet, distance_source = _resolve_target_distance_feet(
        action=action,
        actor_combatant=actor_combatant,
        target_combatant=combatant,
    )
    is_ranged_attack = _is_ranged_attack(
        action,
        actor_character,
        weapon_profile=weapon_profile,
        target_distance_feet=target_distance_feet,
    )
    long_range = _coerce_integer(weapon_profile.get("long_range")) if weapon_profile is not None else None
    if (
        weapon_profile is not None
        and is_ranged_attack
        and target_distance_feet is not None
        and long_range is not None
        and target_distance_feet > long_range
    ):
        rejected_actions.append(
            _reject(
                action,
                f"Target is {target_distance_feet} feet away, beyond the weapon's long range of {long_range} feet.",
            )
        )
        return event_index
    melee_reach = _resolve_melee_reach_feet(weapon_profile, actor_character)
    if (
        not is_ranged_attack
        and target_distance_feet is not None
        and target_distance_feet > melee_reach
    ):
        rejected_actions.append(
            _reject(
                action,
                f"Target is {target_distance_feet} feet away, beyond the attack's reach of {melee_reach} feet.",
            )
        )
        return event_index

    advantage_state, roll_values, condition_sources = _resolve_attack_roll_state(
        actor_combatant=actor_combatant,
        target_combatant=combatant,
        action=action,
        actor_character=actor_character,
        weapon_profile=weapon_profile,
        target_distance_feet=target_distance_feet,
        is_ranged_attack=is_ranged_attack,
    )
    roll_value = max(roll_values) if advantage_state == "advantage" else min(roll_values) if advantage_state == "disadvantage" else roll_values[0]
    total = roll_value + attack_bonus
    hit = roll_value == 20 or (roll_value != 1 and total >= int(combatant["armor_class"]))

    details = dict(action.parameters)
    details.update(
        {
            "actor_ref": action.actor_id,
            "resolved_actor_combatant_id": actor_combatant["id"] if actor_combatant is not None else None,
            "target_ref": target_ref,
            "resolved_target_combatant_id": combatant["id"],
            "advantage_state": advantage_state,
            "roll_values": roll_values,
            "condition_sources": condition_sources,
            "attack_roll": roll_value,
            "attack_bonus": attack_bonus,
            "attack_total": total,
            "target_armor_class": combatant["armor_class"],
            "hit": hit,
            "damage_amount": 0,
            "encounter_id": encounter_id,
            "attack_timing": attack_timing,
            "loading_weapon": bool(weapon_profile.get("loading")) if weapon_profile is not None else False,
            "ammunition_item": ammunition_item,
            "ammunition_expended": bool(track_ammunition and ammunition_item),
            "weapon_name": _coerce_text(weapon_profile.get("name")) if weapon_profile is not None else weapon,
            "weapon_light": bool(weapon_profile.get("light")) if weapon_profile is not None else False,
            "light_extra_attack": light_extra_attack,
            "turn_attack_state_before": turn_attack_state_before,
            "turn_attack_state_after": None,
            "mastery_property": mastery_property,
            "mastery_effects_applied": [],
            "mastery_push_distance_feet": None,
            "mastery_target_position_before": None,
            "mastery_target_position_after": None,
            "mastery_target_speed_before": None,
            "mastery_target_speed_after": None,
            "topple_save_dc": None,
            "topple_save_roll": None,
            "topple_save_bonus": None,
            "topple_save_total": None,
            "topple_save_succeeded": None,
            "cleave_target_id": None,
            "cleave_target_name": None,
            "cleave_hit": None,
            "cleave_attack_roll": None,
            "cleave_attack_total": None,
            "cleave_damage_amount": None,
            "target_distance_feet": target_distance_feet,
            "distance_source": distance_source,
        }
    )

    if track_ammunition and ammunition_item:
        removed = remove_item(
            connection,
            character_id=str(action.actor_id),
            item_name=ammunition_item,
            quantity=1,
        )
        if not removed:
            rejected_actions.append(_reject(action, f"attack_roll could not expend required ammunition: {ammunition_item}."))
            return event_index
        if str(action.actor_id) not in changed_entities:
            changed_entities.append(str(action.actor_id))

    if hit:
        damage_amount = _roll_damage_from_spec(damage_spec)
        damage_amount += damage_bonus_modifier
        if damage_amount < 0:
            damage_amount = 0
        details["damage_amount"] = damage_amount
        updated = apply_damage_to_combatant(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            target_ref=str(combatant["id"]),
            amount=damage_amount,
        )
        if updated is None:
            rejected_actions.append(_reject(action, "Attack hit, but damage could not be applied to the target combatant."))
            return event_index
        changed_ref = updated["source_character_id"] or str(updated["id"])
        if changed_ref not in changed_entities:
            changed_entities.append(changed_ref)
        resolved_state = finalize_encounter_if_resolved(connection, int(combatant["encounter_id"]))
        if resolved_state is not None:
            details["encounter_status"] = resolved_state.status
            details["winning_side"] = resolved_state.winning_side
            details["outcome_summary"] = resolved_state.outcome_summary
        _apply_mastery_on_hit(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            actor_combatant=actor_combatant,
            actor_character=actor_character,
            target_combatant=combatant,
            weapon_profile=weapon_profile,
            mastery_property=mastery_property,
            damage_amount=damage_amount,
            details=details,
            turn_id=turn_id,
            action=action,
            changed_entities=changed_entities,
            light_extra_attack=light_extra_attack,
        )
    else:
        graze_damage = _apply_graze_mastery_on_miss(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            actor_character=actor_character,
            target_combatant=combatant,
            weapon_profile=weapon_profile,
            mastery_property=mastery_property,
        )
        if graze_damage > 0:
            details["damage_amount"] = graze_damage
            details["mastery_effects_applied"].append("graze_damage")
            changed_ref = combatant["source_character_id"] or str(combatant["id"])
            if changed_ref not in changed_entities:
                changed_entities.append(changed_ref)
            resolved_state = finalize_encounter_if_resolved(connection, int(combatant["encounter_id"]))
            if resolved_state is not None:
                details["encounter_status"] = resolved_state.status
                details["winning_side"] = resolved_state.winning_side
                details["outcome_summary"] = resolved_state.outcome_summary
    _consume_attack_mastery_effects(
        connection,
        actor_combatant=actor_combatant,
        target_combatant=combatant,
        condition_sources=condition_sources,
    )
    details["turn_attack_state_after"] = _summarize_turn_attack_state([*prior_attack_details, details], actor_character=actor_character)
    event_id = _record_event(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        event_index=event_index,
        event_type=action.type,
        actor_id=action.actor_id,
        target_id=str(combatant["id"]),
        details=details,
    )
    applied_actions.append(
        AppliedAction(
            type=action.type,
            event_id=event_id,
            outcome={
                "target_id": str(combatant["id"]),
                "target_name": combatant["name"],
                "hit": hit,
                "advantage_state": advantage_state,
                "roll_values": roll_values,
                "condition_sources": condition_sources,
                "attack_roll": roll_value,
                "attack_bonus": attack_bonus,
                "attack_total": total,
                "target_armor_class": combatant["armor_class"],
                "damage_amount": details["damage_amount"],
                "encounter_id": encounter_id,
                "attack_timing": attack_timing,
                "loading_weapon": details["loading_weapon"],
                "ammunition_item": ammunition_item,
                "ammunition_expended": details["ammunition_expended"],
                "weapon_name": details["weapon_name"],
                "light_extra_attack": details["light_extra_attack"],
                "turn_attack_state_before": details["turn_attack_state_before"],
                "turn_attack_state_after": details["turn_attack_state_after"],
                "mastery_property": mastery_property,
                "mastery_effects_applied": details["mastery_effects_applied"],
                "mastery_target_size": details.get("mastery_target_size"),
                "mastery_push_distance_feet": details.get("mastery_push_distance_feet"),
                "mastery_push_blocked_reason": details.get("mastery_push_blocked_reason"),
                "mastery_target_position_before": details.get("mastery_target_position_before"),
                "mastery_target_position_after": details.get("mastery_target_position_after"),
                "mastery_target_speed_before": details.get("mastery_target_speed_before"),
                "mastery_target_speed_after": details.get("mastery_target_speed_after"),
                "topple_save_dc": details.get("topple_save_dc"),
                "topple_save_roll": details.get("topple_save_roll"),
                "topple_save_bonus": details.get("topple_save_bonus"),
                "topple_save_total": details.get("topple_save_total"),
                "topple_save_succeeded": details.get("topple_save_succeeded"),
                "cleave_target_id": details.get("cleave_target_id"),
                "cleave_target_name": details.get("cleave_target_name"),
                "cleave_hit": details.get("cleave_hit"),
                "cleave_attack_roll": details.get("cleave_attack_roll"),
                "cleave_attack_total": details.get("cleave_attack_total"),
                "cleave_damage_amount": details.get("cleave_damage_amount"),
                "target_distance_feet": target_distance_feet,
                "distance_source": distance_source,
                "encounter_status": details.get("encounter_status", "active"),
                "winning_side": details.get("winning_side"),
                "outcome_summary": details.get("outcome_summary"),
            },
        )
    )
    return event_index + 1


def _apply_character_action(
    *,
    connection: Connection,
    campaign_id: int,
    session_id: int,
    turn_id: int,
    action: ProposedAction,
    event_index: int,
    applied_actions: list[AppliedAction],
    rejected_actions: list[RejectedAction],
    changed_entities: list[str],
) -> int:
    targets = action.target_ids or []
    if action.type in {"add_condition", "remove_condition"} and not targets and action.actor_id:
        targets = [action.actor_id]
    if action.type in {"spend_spell_slot", "restore_spell_slot"} and not targets and action.actor_id:
        targets = [action.actor_id]

    if not targets:
        rejected_actions.append(_reject(action, "Action requires at least one target character."))
        return event_index

    any_applied = False
    any_valid_character = False
    for target_id in targets:
        character = _get_character(connection, target_id, campaign_id)
        if character is None:
            continue
        any_valid_character = True

        applied = False
        reason: str | None = None
        if action.type == "apply_damage":
            amount = _coerce_positive_int(action.parameters.get("amount"))
            if amount is None:
                reason = "apply_damage requires a positive integer amount."
            else:
                new_hp = max(0, int(character["current_hp"]) - amount)
                if new_hp == int(character["current_hp"]):
                    reason = "Damage produced no state change."
                else:
                    _update_character_hp(connection, target_id, new_hp)
                    applied = True
        elif action.type == "apply_healing":
            amount = _coerce_positive_int(action.parameters.get("amount"))
            if amount is None:
                reason = "apply_healing requires a positive integer amount."
            else:
                new_hp = min(int(character["max_hp"]), int(character["current_hp"]) + amount)
                if new_hp == int(character["current_hp"]):
                    reason = "Healing produced no state change."
                else:
                    _update_character_hp(connection, target_id, new_hp)
                    applied = True
        elif action.type == "add_condition":
            condition = _coerce_condition(action.parameters.get("condition"))
            if not condition:
                reason = "add_condition requires a non-empty condition."
            else:
                current_conditions = json_loads(character["conditions_json"], [])
                if condition in current_conditions:
                    reason = "Character already has that condition."
                else:
                    current_conditions.append(condition)
                    _update_character_conditions(connection, target_id, current_conditions)
                    applied = True
        elif action.type == "remove_condition":
            condition = _coerce_condition(action.parameters.get("condition"))
            if not condition:
                reason = "remove_condition requires a non-empty condition."
            else:
                current_conditions = json_loads(character["conditions_json"], [])
                if condition not in current_conditions:
                    reason = "Character does not have that condition."
                else:
                    remaining = [item for item in current_conditions if item != condition]
                    _update_character_conditions(connection, target_id, remaining)
                    applied = True
        elif action.type == "spend_spell_slot":
            level = _coerce_positive_int(action.parameters.get("level"))
            if level is None:
                reason = "spend_spell_slot requires a positive integer level."
            else:
                updated_slots, slot_reason = _change_spell_slots(character["spell_slots_json"], level=level, delta=-1)
                if updated_slots is None:
                    reason = slot_reason
                else:
                    _update_character_spell_slots(connection, target_id, updated_slots)
                    applied = True
        elif action.type == "restore_spell_slot":
            level = _coerce_positive_int(action.parameters.get("level"))
            amount = _coerce_positive_int(action.parameters.get("amount")) or 1
            if level is None:
                reason = "restore_spell_slot requires a positive integer level."
            else:
                updated_slots, slot_reason = _change_spell_slots(character["spell_slots_json"], level=level, delta=amount)
                if updated_slots is None:
                    reason = slot_reason
                else:
                    _update_character_spell_slots(connection, target_id, updated_slots)
                    applied = True

        if applied:
            updated_conditions: list[str] | None = None
            if action.type == "add_condition":
                updated_conditions = current_conditions
            elif action.type == "remove_condition":
                updated_conditions = remaining
            event_id = _record_event(
                connection,
                campaign_id=campaign_id,
                session_id=session_id,
                turn_id=turn_id,
                event_index=event_index,
                event_type=action.type,
                actor_id=action.actor_id,
                target_id=target_id,
                details=dict(action.parameters),
            )
            applied_actions.append(
                AppliedAction(
                    type=action.type,
                    event_id=event_id,
                    outcome={"target_id": target_id},
                )
            )
            if target_id not in changed_entities:
                changed_entities.append(target_id)
            sync_character_to_active_combatant(connection, campaign_id, session_id, target_id)
            if updated_conditions is not None and _conditions_impose_incapacitated(updated_conditions):
                _break_concentration_for_character_if_active(
                    connection,
                    campaign_id=campaign_id,
                    session_id=session_id,
                    character_id=target_id,
                )
            event_index += 1
            any_applied = True
        elif reason:
            rejected_actions.append(_reject(action, f"{target_id}: {reason}"))

    if not any_valid_character:
        rejected_actions.append(_reject(action, "No valid target characters were found in this campaign."))
    elif not any_applied and not any(item.type == action.type and item.actor_id == action.actor_id and item.parameters == action.parameters for item in rejected_actions):
        rejected_actions.append(_reject(action, "Action did not produce any valid state change."))

    return event_index


def _apply_inventory_or_quest_action(
    *,
    connection: Connection,
    campaign_id: int,
    session_id: int,
    turn_id: int,
    action: ProposedAction,
    event_index: int,
    applied_actions: list[AppliedAction],
    rejected_actions: list[RejectedAction],
    changed_entities: list[str],
) -> int:
    if action.type in {"add_inventory_item", "remove_inventory_item"}:
        target_ids = action.target_ids or ([action.actor_id] if action.actor_id else [])
        item_name = _coerce_text(action.parameters.get("item_name") or action.parameters.get("name"))
        quantity = _coerce_positive_int(action.parameters.get("quantity")) or 1
        if not target_ids:
            rejected_actions.append(_reject(action, "Inventory action requires a target character."))
            return event_index
        if not item_name:
            rejected_actions.append(_reject(action, "Inventory action requires an item_name."))
            return event_index

        character_id = target_ids[0]
        if _get_character(connection, character_id, campaign_id) is None:
            rejected_actions.append(_reject(action, "Target character was not found in this campaign."))
            return event_index

        changed = (
            add_item(
                connection,
                campaign_id=campaign_id,
                character_id=character_id,
                item_name=item_name,
                quantity=quantity,
                details=action.parameters.get("details") if isinstance(action.parameters.get("details"), dict) else None,
            )
            if action.type == "add_inventory_item"
            else remove_item(
                connection,
                character_id=character_id,
                item_name=item_name,
                quantity=quantity,
            )
        )
        if not changed:
            rejected_actions.append(_reject(action, "Inventory update could not be applied."))
            return event_index

        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=character_id,
            details=dict(action.parameters),
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={
                    "target_id": character_id,
                    "item_name": item_name,
                    "quantity": quantity,
                },
            )
        )
        if character_id not in changed_entities:
            changed_entities.append(character_id)
        return event_index + 1

    if action.type == "recover_ammunition":
        target_ids = action.target_ids or ([action.actor_id] if action.actor_id else [])
        if not target_ids:
            rejected_actions.append(_reject(action, "recover_ammunition requires a target character."))
            return event_index
        character_id = target_ids[0]
        if _get_character(connection, character_id, campaign_id) is None:
            rejected_actions.append(_reject(action, "Target character was not found in this campaign."))
            return event_index
        encounter_id = _coerce_positive_int(action.parameters.get("encounter_id"))
        if encounter_id is None:
            rejected_actions.append(_reject(action, "recover_ammunition requires a positive integer encounter_id."))
            return event_index
        if _is_encounter_active(connection, campaign_id=campaign_id, session_id=session_id, encounter_id=encounter_id):
            rejected_actions.append(_reject(action, "recover_ammunition can only be used after the encounter has ended."))
            return event_index
        recovered_items = _recover_ammunition_for_encounter(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            character_id=character_id,
            encounter_id=encounter_id,
        )
        if not recovered_items:
            rejected_actions.append(_reject(action, "No recoverable ammunition was found for that encounter."))
            return event_index

        details = dict(action.parameters)
        details["recovered_items"] = recovered_items
        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=character_id,
            details=details,
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={
                    "target_id": character_id,
                    "encounter_id": encounter_id,
                    "recovered_items": recovered_items,
                },
            )
        )
        if character_id not in changed_entities:
            changed_entities.append(character_id)
        return event_index + 1

    if action.type == "create_quest":
        title = _coerce_text(action.parameters.get("title"))
        if not title:
            rejected_actions.append(_reject(action, "create_quest requires a title."))
            return event_index
        quest_id = create_quest(
            connection,
            campaign_id=campaign_id,
            title=title,
            summary=_coerce_text(action.parameters.get("summary")),
            notes=_coerce_text(action.parameters.get("notes")),
        )
        if quest_id is None:
            rejected_actions.append(_reject(action, "Quest could not be created."))
            return event_index
        details = dict(action.parameters)
        details["quest_id"] = quest_id
        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=None,
            details=details,
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={"quest_id": quest_id, "title": title},
            )
        )
        return event_index + 1

    quest_id = _coerce_positive_int(action.parameters.get("quest_id"))
    if quest_id is None:
        rejected_actions.append(_reject(action, f"{action.type} requires a positive integer quest_id."))
        return event_index

    row = connection.execute(
        "SELECT status FROM quests WHERE id = ? AND campaign_id = ?",
        (quest_id, campaign_id),
    ).fetchone()
    if row is None:
        rejected_actions.append(_reject(action, "Quest was not found in this campaign."))
        return event_index

    target_status = "completed" if action.type == "complete_quest" else "active"
    if row["status"] == target_status and not action.parameters.get("notes") and not action.parameters.get("summary"):
        rejected_actions.append(_reject(action, "Quest already has the requested status."))
        return event_index

    updated = update_quest_status(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        status=target_status,
        notes=_coerce_text(action.parameters.get("notes")),
        summary=_coerce_text(action.parameters.get("summary")),
    )
    if not updated:
        rejected_actions.append(_reject(action, "Quest update could not be applied."))
        return event_index
    event_id = _record_event(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        event_index=event_index,
        event_type=action.type,
        actor_id=action.actor_id,
        target_id=str(quest_id),
        details=dict(action.parameters),
    )
    applied_actions.append(
        AppliedAction(
            type=action.type,
            event_id=event_id,
            outcome={"quest_id": quest_id, "status": target_status},
        )
    )
    return event_index + 1


def _apply_campaign_action(
    *,
    connection: Connection,
    campaign_id: int,
    session_id: int,
    turn_id: int,
    action: ProposedAction,
    event_index: int,
    applied_actions: list[AppliedAction],
    rejected_actions: list[RejectedAction],
) -> int:
    location = _coerce_text(action.parameters.get("location"))
    if not location:
        rejected_actions.append(_reject(action, "set_location requires a non-empty location string."))
        return event_index

    current = connection.execute(
        "SELECT current_location_text FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()
    if current is None:
        rejected_actions.append(_reject(action, "Campaign was not found."))
        return event_index
    if current["current_location_text"] == location:
        rejected_actions.append(_reject(action, "Campaign is already at that location."))
        return event_index

    connection.execute(
        """
        UPDATE campaigns
        SET current_location_text = ?, updated_at = ?
        WHERE id = ?
        """,
        (location, utc_now(), campaign_id),
    )
    event_id = _record_event(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        event_index=event_index,
        event_type=action.type,
        actor_id=action.actor_id,
        target_id=str(campaign_id),
        details=dict(action.parameters),
    )
    applied_actions.append(
        AppliedAction(
            type=action.type,
            event_id=event_id,
            outcome={"location": location},
        )
    )
    return event_index + 1


def _apply_combat_action(
    *,
    connection: Connection,
    campaign_id: int,
    session_id: int,
    turn_id: int,
    action: ProposedAction,
    event_index: int,
    applied_actions: list[AppliedAction],
    rejected_actions: list[RejectedAction],
) -> int:
    if action.type == "start_combat":
        active_id = get_active_encounter_id(connection, campaign_id, session_id)
        if active_id is not None:
            rejected_actions.append(_reject(action, "An active combat encounter already exists for this session."))
            return event_index
        state = start_combat(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            name=_coerce_text(action.parameters.get("name")),
            combatants=_coerce_combatants(action.parameters.get("combatants")),
        )
        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=str(state.encounter_id),
            details=dict(action.parameters),
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={
                    "encounter_id": state.encounter_id,
                    "status": state.status,
                    "combatant_count": len(state.combatants),
                },
            )
        )
        return event_index + 1

    state = end_combat(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        encounter_id=_coerce_positive_int(action.parameters.get("encounter_id")),
    )
    if state is None:
        rejected_actions.append(_reject(action, "No active combat encounter was available to end."))
        return event_index
    event_id = _record_event(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        event_index=event_index,
        event_type=action.type,
        actor_id=action.actor_id,
        target_id=str(state.encounter_id),
        details=dict(action.parameters),
    )
    applied_actions.append(
        AppliedAction(
            type=action.type,
            event_id=event_id,
            outcome={
                "encounter_id": state.encounter_id,
                "status": "ended",
            },
        )
    )
    return event_index + 1


def _apply_combat_utility_action(
    *,
    connection: Connection,
    campaign_id: int,
    session_id: int,
    turn_id: int,
    action: ProposedAction,
    event_index: int,
    applied_actions: list[AppliedAction],
    rejected_actions: list[RejectedAction],
) -> int:
    if action.type == "advance_turn":
        encounter_id = get_active_encounter_id(connection, campaign_id, session_id)
        if encounter_id is None:
            rejected_actions.append(_reject(action, "No active combat encounter exists for this session."))
            return event_index

        state = advance_turn(connection, encounter_id=encounter_id)
        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=str(encounter_id),
            details={},
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={
                    "encounter_id": encounter_id,
                    "status": state.status,
                    "round_number": state.round_number,
                    "turn_index": state.turn_index,
                    "active_combatant_id": state.active_combatant_id,
                    "winning_side": state.winning_side,
                    "outcome_summary": state.outcome_summary,
                },
            )
        )
        return event_index + 1

    if action.type == "cast_shield":
        actor_ref = action.actor_id
        if not actor_ref:
            rejected_actions.append(_reject(action, "Shield requires an acting combatant."))
            return event_index
        combatant = find_active_combatant(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            target_ref=actor_ref,
        )
        if combatant is None:
            rejected_actions.append(_reject(action, "Acting combatant was not found in the active encounter."))
            return event_index
        if _combatant_has_incapacitating_condition(combatant):
            rejected_actions.append(_reject(action, "Shield cannot be cast while the acting combatant is incapacitated."))
            return event_index
        target_ref = action.target_ids[0] if action.target_ids else actor_ref
        if target_ref != actor_ref:
            rejected_actions.append(_reject(action, "Shield has range Self and can target only the caster."))
            return event_index
        updated = add_combat_effect(
            connection,
            combatant_id=int(combatant["id"]),
            effect_name="Shield",
            effect_type="ac_bonus",
            modifier=SHIELD_AC_BONUS,
            duration_rounds=1,
            source_combatant_id=int(combatant["id"]),
            requires_concentration=False,
        )
        if updated is None:
            rejected_actions.append(_reject(action, "Shield could not be applied."))
            return event_index
        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=str(combatant["id"]),
            details={
                "effect_name": "Shield",
                "effect_type": "ac_bonus",
                "modifier": SHIELD_AC_BONUS,
                "duration_rounds": 1,
                "requires_concentration": False,
                "range": "Self",
                "magic_missile_protection": True,
            },
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={
                    "combatant_id": combatant["id"],
                    "effect_name": "Shield",
                    "effect_type": "ac_bonus",
                    "armor_class": updated["armor_class"],
                    "speed": updated.get("speed"),
                    "duration_rounds": 1,
                    "requires_concentration": False,
                    "range": "Self",
                    "magic_missile_protection": True,
                    "ended_concentration_effects": updated.get("removed_concentration", []),
                },
            )
        )
        return event_index + 1

    if action.type == "cast_barkskin":
        actor_ref = action.actor_id
        if not actor_ref:
            rejected_actions.append(_reject(action, "Barkskin requires an acting combatant."))
            return event_index
        if get_active_encounter_id(connection, campaign_id, session_id) is not None and not is_active_turn_for_ref(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            actor_ref=actor_ref,
        ):
            rejected_actions.append(_reject(action, "Barkskin can only be cast by the active combatant during combat."))
            return event_index
        actor_combatant = find_active_combatant(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            target_ref=actor_ref,
        )
        if actor_combatant is None:
            rejected_actions.append(_reject(action, "Acting combatant was not found in the active encounter."))
            return event_index
        if _combatant_has_incapacitating_condition(actor_combatant):
            rejected_actions.append(_reject(action, "Barkskin cannot be cast while the acting combatant is incapacitated."))
            return event_index
        target_ref = action.target_ids[0] if action.target_ids else actor_ref
        if not target_ref:
            rejected_actions.append(_reject(action, "Barkskin requires a target combatant."))
            return event_index
        combatant = find_active_combatant(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            target_ref=target_ref,
        )
        if combatant is None:
            rejected_actions.append(_reject(action, "Target combatant was not found in the active encounter."))
            return event_index
        distance_feet, distance_source = _resolve_target_distance_feet(
            action=action,
            actor_combatant=actor_combatant,
            target_combatant=combatant,
        )
        if distance_feet is not None and distance_feet > BARKSKIN_TOUCH_RANGE_FEET:
            rejected_actions.append(_reject(action, "Barkskin requires a target within touch range."))
            return event_index
        updated = add_combat_effect(
            connection,
            combatant_id=int(combatant["id"]),
            effect_name="Barkskin",
            effect_type="ac_floor",
            modifier=BARKSKIN_AC_FLOOR,
            source_combatant_id=int(actor_combatant["id"]),
            requires_concentration=False,
        )
        if updated is None:
            rejected_actions.append(_reject(action, "Barkskin could not be applied."))
            return event_index
        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=str(combatant["id"]),
            details={
                "effect_name": "Barkskin",
                "effect_type": "ac_floor",
                "modifier": BARKSKIN_AC_FLOOR,
                "requires_concentration": False,
                "touch_range_feet": BARKSKIN_TOUCH_RANGE_FEET,
                "target_distance_feet": distance_feet,
                "distance_source": distance_source,
            },
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={
                    "combatant_id": combatant["id"],
                    "effect_name": "Barkskin",
                    "effect_type": "ac_floor",
                    "armor_class": updated["armor_class"],
                    "speed": updated.get("speed"),
                    "requires_concentration": False,
                    "touch_range_feet": BARKSKIN_TOUCH_RANGE_FEET,
                    "target_distance_feet": distance_feet,
                    "distance_source": distance_source,
                    "ended_concentration_effects": updated.get("removed_concentration", []),
                },
            )
        )
        return event_index + 1

    if action.type == "cast_shield_of_faith":
        actor_ref = action.actor_id
        if not actor_ref:
            rejected_actions.append(_reject(action, "Shield of Faith requires an acting combatant."))
            return event_index
        if get_active_encounter_id(connection, campaign_id, session_id) is not None and not is_active_turn_for_ref(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            actor_ref=actor_ref,
        ):
            rejected_actions.append(_reject(action, "Shield of Faith can only be cast by the active combatant during combat."))
            return event_index
        actor_combatant = find_active_combatant(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            target_ref=actor_ref,
        )
        if actor_combatant is None:
            rejected_actions.append(_reject(action, "Acting combatant was not found in the active encounter."))
            return event_index
        if _combatant_has_incapacitating_condition(actor_combatant):
            rejected_actions.append(_reject(action, "Shield of Faith cannot be cast while the acting combatant is incapacitated."))
            return event_index
        target_ref = action.target_ids[0] if action.target_ids else actor_ref
        if not target_ref:
            rejected_actions.append(_reject(action, "Shield of Faith requires a target combatant."))
            return event_index
        combatant = find_active_combatant(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            target_ref=target_ref,
        )
        if combatant is None:
            rejected_actions.append(_reject(action, "Target combatant was not found in the active encounter."))
            return event_index
        distance_feet, distance_source = _resolve_target_distance_feet(
            action=action,
            actor_combatant=actor_combatant,
            target_combatant=combatant,
        )
        if distance_feet is not None and distance_feet > SHIELD_OF_FAITH_RANGE_FEET:
            rejected_actions.append(_reject(action, "Shield of Faith requires a target within 60 feet."))
            return event_index
        updated = add_combat_effect(
            connection,
            combatant_id=int(combatant["id"]),
            effect_name="Shield of Faith",
            effect_type="ac_bonus",
            modifier=2,
            source_combatant_id=int(actor_combatant["id"]),
            requires_concentration=True,
        )
        if updated is None:
            rejected_actions.append(_reject(action, "Shield of Faith could not be applied."))
            return event_index
        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=str(combatant["id"]),
            details={
                "effect_name": "Shield of Faith",
                "effect_type": "ac_bonus",
                "modifier": 2,
                "requires_concentration": True,
                "range_feet": SHIELD_OF_FAITH_RANGE_FEET,
                "target_distance_feet": distance_feet,
                "distance_source": distance_source,
            },
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={
                    "combatant_id": combatant["id"],
                    "effect_name": "Shield of Faith",
                    "effect_type": "ac_bonus",
                    "armor_class": updated["armor_class"],
                    "speed": updated.get("speed"),
                    "requires_concentration": True,
                    "range_feet": SHIELD_OF_FAITH_RANGE_FEET,
                    "target_distance_feet": distance_feet,
                    "distance_source": distance_source,
                    "ended_concentration_effects": updated.get("removed_concentration", []),
                },
            )
        )
        return event_index + 1

    if action.type == "add_combat_effect":
        actor_ref = action.actor_id
        if actor_ref and get_active_encounter_id(connection, campaign_id, session_id) is not None and not is_active_turn_for_ref(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            actor_ref=actor_ref,
        ):
            rejected_actions.append(_reject(action, "add_combat_effect can only be used by the active combatant during combat."))
            return event_index
        target_ref = action.target_ids[0] if action.target_ids else actor_ref
        if not target_ref:
            rejected_actions.append(_reject(action, "add_combat_effect requires a target combatant or actor_id."))
            return event_index
        combatant = find_active_combatant(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            target_ref=target_ref,
        )
        if combatant is None:
            rejected_actions.append(_reject(action, "Target combatant was not found in the active encounter."))
            return event_index
        actor_combatant = (
            find_active_combatant(
                connection,
                campaign_id=campaign_id,
                session_id=session_id,
                target_ref=actor_ref,
            )
            if actor_ref
            else None
        )
        if _combatant_has_incapacitating_condition(actor_combatant):
            rejected_actions.append(_reject(action, "add_combat_effect cannot be used while the acting combatant is incapacitated."))
            return event_index
        effect_name = _coerce_text(action.parameters.get("effect_name") or action.parameters.get("name"))
        effect_type = _coerce_text(action.parameters.get("effect_type"))
        modifier = _coerce_integer(action.parameters.get("modifier"))
        duration_rounds = _coerce_integer(action.parameters.get("duration_rounds"))
        requires_concentration = bool(action.parameters.get("requires_concentration") or action.parameters.get("concentration"))
        if not effect_name:
            rejected_actions.append(_reject(action, "add_combat_effect requires an effect_name."))
            return event_index
        if effect_type not in {"ac_bonus", "attack_bonus", "damage_bonus", "speed_bonus", "speed_penalty"}:
            rejected_actions.append(_reject(action, "Supported effect types are ac_bonus, attack_bonus, damage_bonus, speed_bonus, and speed_penalty."))
            return event_index
        if modifier is None:
            rejected_actions.append(_reject(action, "add_combat_effect requires an integer modifier."))
            return event_index
        if duration_rounds is not None and duration_rounds <= 0:
            rejected_actions.append(_reject(action, "duration_rounds must be a positive integer when provided."))
            return event_index
        if requires_concentration and actor_combatant is None:
            rejected_actions.append(_reject(action, "Concentration effects require an acting combatant in the active encounter."))
            return event_index
        updated = add_combat_effect(
            connection,
            combatant_id=int(combatant["id"]),
            effect_name=effect_name,
            effect_type=effect_type,
            modifier=modifier,
            duration_rounds=duration_rounds,
            source_combatant_id=int(actor_combatant["id"]) if actor_combatant is not None else None,
            requires_concentration=requires_concentration,
        )
        if updated is None:
            rejected_actions.append(_reject(action, "Combat effect could not be applied."))
            return event_index
        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=str(combatant["id"]),
            details=dict(action.parameters),
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={
                    "combatant_id": combatant["id"],
                    "effect_name": effect_name,
                    "effect_type": effect_type,
                    "armor_class": updated["armor_class"],
                    "speed": updated.get("speed"),
                    "requires_concentration": requires_concentration,
                    "ended_concentration_effects": updated.get("removed_concentration", []),
                },
            )
        )
        return event_index + 1

    if action.type == "remove_combat_effect":
        actor_ref = action.actor_id
        if actor_ref and get_active_encounter_id(connection, campaign_id, session_id) is not None and not is_active_turn_for_ref(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            actor_ref=actor_ref,
        ):
            rejected_actions.append(_reject(action, "remove_combat_effect can only be used by the active combatant during combat."))
            return event_index
        target_ref = action.target_ids[0] if action.target_ids else actor_ref
        if not target_ref:
            rejected_actions.append(_reject(action, "remove_combat_effect requires a target combatant or actor_id."))
            return event_index
        combatant = find_active_combatant(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            target_ref=target_ref,
        )
        if combatant is None:
            rejected_actions.append(_reject(action, "Target combatant was not found in the active encounter."))
            return event_index
        actor_combatant = (
            find_active_combatant(
                connection,
                campaign_id=campaign_id,
                session_id=session_id,
                target_ref=actor_ref,
            )
            if actor_ref
            else None
        )
        if _combatant_has_incapacitating_condition(actor_combatant):
            rejected_actions.append(_reject(action, "remove_combat_effect cannot be used while the acting combatant is incapacitated."))
            return event_index
        effect_name = _coerce_text(action.parameters.get("effect_name") or action.parameters.get("name"))
        if not effect_name:
            rejected_actions.append(_reject(action, "remove_combat_effect requires an effect_name."))
            return event_index
        updated = remove_combat_effect(
            connection,
            combatant_id=int(combatant["id"]),
            effect_name=effect_name,
        )
        if updated is None:
            rejected_actions.append(_reject(action, "Combat effect was not found on the target combatant."))
            return event_index
        event_id = _record_event(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            event_index=event_index,
            event_type=action.type,
            actor_id=action.actor_id,
            target_id=str(combatant["id"]),
            details=dict(action.parameters),
        )
        applied_actions.append(
            AppliedAction(
                type=action.type,
                event_id=event_id,
                outcome={
                    "combatant_id": combatant["id"],
                    "effect_name": effect_name,
                    "armor_class": updated["armor_class"],
                    "speed": updated.get("speed"),
                },
            )
        )
        return event_index + 1

    character_id = action.actor_id or (action.target_ids[0] if action.target_ids else None)
    if not character_id:
        rejected_actions.append(_reject(action, "set_active_weapon_slot requires an actor_id or target character id."))
        return event_index
    if get_active_encounter_id(connection, campaign_id, session_id) is not None and not is_active_turn_for_ref(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        actor_ref=character_id,
    ):
        rejected_actions.append(_reject(action, "set_active_weapon_slot can only be used by the active combatant during combat."))
        return event_index
    actor_combatant = find_active_combatant(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        target_ref=character_id,
    )
    if _combatant_has_incapacitating_condition(actor_combatant):
        rejected_actions.append(_reject(action, "set_active_weapon_slot cannot be used while the acting combatant is incapacitated."))
        return event_index
    active_slot = _coerce_text(action.parameters.get("active_slot"))
    if active_slot not in {"primary", "secondary", "ranged"}:
        rejected_actions.append(_reject(action, "set_active_weapon_slot requires active_slot of primary, secondary, or ranged."))
        return event_index
    updated = set_active_weapon_slot(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        active_slot=active_slot,
    )
    if updated is None:
        rejected_actions.append(_reject(action, "Character weapon loadout could not switch to that slot."))
        return event_index
    sync_character_to_active_combatant(connection, campaign_id, session_id, character_id)
    event_id = _record_event(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        event_index=event_index,
        event_type=action.type,
        actor_id=action.actor_id,
        target_id=character_id,
        details={"active_slot": active_slot},
    )
    applied_actions.append(
        AppliedAction(
            type=action.type,
            event_id=event_id,
            outcome={
                "character_id": character_id,
                "active_slot": active_slot,
                "equipped_weapon": updated.equipped_weapon.model_dump() if updated.equipped_weapon else None,
            },
        )
    )
    return event_index + 1


def _get_character(connection: Connection, character_id: str, campaign_id: int):
    if not character_id:
        return None
    return connection.execute(
        """
        SELECT
          id,
          class_name,
          level,
          current_hp,
          max_hp,
          conditions_json,
          spell_slots_json,
          proficiency_bonus,
          ability_modifiers_json,
          equipped_weapon_json
          , weapon_loadout_json
        FROM characters
        WHERE id = ? AND campaign_id = ?
        """,
        (character_id, campaign_id),
    ).fetchone()


def _get_inventory_quantity(connection: Connection, *, character_id: str, item_name: str) -> int:
    row = connection.execute(
        """
        SELECT quantity
        FROM inventory_items
        WHERE character_id = ? AND name = ?
        """,
        (character_id, item_name),
    ).fetchone()
    return int(row["quantity"]) if row is not None else 0


def _is_encounter_active(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    encounter_id: int,
) -> bool:
    row = connection.execute(
        """
        SELECT status
        FROM combat_encounters
        WHERE id = ? AND campaign_id = ? AND session_id = ?
        """,
        (encounter_id, campaign_id, session_id),
    ).fetchone()
    return row is not None and str(row["status"]).lower() == "active"


def _recover_ammunition_for_encounter(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    character_id: str,
    encounter_id: int,
) -> list[dict[str, int | str]]:
    spent_by_item: dict[str, int] = {}
    rows = connection.execute(
        """
        SELECT details_json
        FROM game_events
        WHERE campaign_id = ? AND session_id = ? AND actor_id = ? AND event_type = 'attack_roll'
        ORDER BY id ASC
        """,
        (campaign_id, session_id, character_id),
    ).fetchall()
    for row in rows:
        details = json_loads(row["details_json"], {})
        if not isinstance(details, dict):
            continue
        if _coerce_integer(details.get("encounter_id")) != encounter_id:
            continue
        if not bool(details.get("ammunition_expended")):
            continue
        item_name = _coerce_text(details.get("ammunition_item"))
        if not item_name:
            continue
        spent_by_item[item_name] = spent_by_item.get(item_name, 0) + 1

    recovered_by_item: dict[str, int] = {}
    recovery_rows = connection.execute(
        """
        SELECT details_json
        FROM game_events
        WHERE campaign_id = ? AND session_id = ? AND target_id = ? AND event_type = 'recover_ammunition'
        ORDER BY id ASC
        """,
        (campaign_id, session_id, character_id),
    ).fetchall()
    for row in recovery_rows:
        details = json_loads(row["details_json"], {})
        if not isinstance(details, dict):
            continue
        if _coerce_integer(details.get("encounter_id")) != encounter_id:
            continue
        items = details.get("recovered_items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_name = _coerce_text(item.get("item_name"))
            quantity = _coerce_positive_int(item.get("quantity"))
            if not item_name or quantity is None:
                continue
            recovered_by_item[item_name] = recovered_by_item.get(item_name, 0) + quantity

    recovered_items: list[dict[str, int | str]] = []
    for item_name, spent in spent_by_item.items():
        recoverable = (spent // 2) - recovered_by_item.get(item_name, 0)
        if recoverable <= 0:
            continue
        added = add_item(
            connection,
            campaign_id=campaign_id,
            character_id=character_id,
            item_name=item_name,
            quantity=recoverable,
        )
        if not added:
            continue
        recovered_items.append({"item_name": item_name, "quantity": recoverable})
    return recovered_items


def _update_character_hp(connection: Connection, character_id: str, new_hp: int) -> None:
    connection.execute(
        """
        UPDATE characters
        SET current_hp = ?, updated_at = ?
        WHERE id = ?
        """,
        (new_hp, utc_now(), character_id),
    )


def _update_character_conditions(connection: Connection, character_id: str, conditions: list[str]) -> None:
    connection.execute(
        """
        UPDATE characters
        SET conditions_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (json_dumps(conditions), utc_now(), character_id),
    )


def _update_character_spell_slots(connection: Connection, character_id: str, spell_slots: dict[str, int]) -> None:
    connection.execute(
        """
        UPDATE characters
        SET spell_slots_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (json_dumps(spell_slots), utc_now(), character_id),
    )


def _coerce_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        int_value = int(value)
        return int_value if int_value > 0 else None
    if isinstance(value, str) and value.isdigit():
        int_value = int(value)
        return int_value if int_value > 0 else None
    return None


def _coerce_condition(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    condition = value.strip().lower()
    return condition or None


def _coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _coerce_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _change_spell_slots(raw_slots: str, *, level: int, delta: int) -> tuple[dict[str, int] | None, str | None]:
    slots = json_loads(raw_slots, {})
    key = str(level)
    current = slots.get(key)
    if not isinstance(current, int):
        return None, f"Spell slot level {level} is not tracked for this character."
    next_value = current + delta
    if next_value < 0:
        return None, f"Character does not have enough level {level} spell slots remaining."
    slots[key] = next_value
    return slots, None


def _resolve_attack_bonus(action: ProposedAction, actor_character) -> tuple[int | None, str | None]:
    explicit = (
        _coerce_integer(action.parameters.get("attack_bonus"))
        if action.parameters.get("attack_bonus") is not None
        else _coerce_integer(action.parameters.get("to_hit_bonus"))
    )
    if explicit is not None:
        return explicit, None

    weapon = _coerce_text(action.parameters.get("weapon"))
    profile = _resolve_weapon_profile(weapon, actor_character)
    if profile is not None and actor_character is not None:
        return _compute_attack_bonus_from_profile(profile, actor_character), None
    if weapon:
        return 5, None
    return None, "attack_roll requires attack_bonus or a recognizable weapon."


def _resolve_damage_spec(
    action: ProposedAction,
    actor_character,
    *,
    suppress_positive_ability_modifier: bool = False,
) -> tuple[dict | None, str | None]:
    explicit = _coerce_positive_int(action.parameters.get("damage_amount"))
    if explicit is not None:
        return {"kind": "fixed", "value": explicit}, None

    damage_formula = _coerce_text(action.parameters.get("damage_formula"))
    if damage_formula:
        if not _is_valid_formula(damage_formula):
            return None, "damage_formula must look like NdM+K or include supported symbols like STR/PB."
        return {"kind": "formula", "value": damage_formula}, None

    weapon = _coerce_text(action.parameters.get("weapon"))
    profile = _resolve_weapon_profile(weapon, actor_character)
    if profile is not None and actor_character is not None:
        damage_spec = _damage_spec_from_profile(
            profile,
            actor_character,
            action=action,
            suppress_positive_ability_modifier=suppress_positive_ability_modifier,
        )
        if damage_spec is not None:
            return damage_spec, None
    return None, "attack_roll requires damage_amount, damage_formula, or a supported weapon."


def _roll_formula_total(formula: str) -> int:
    context = _default_formula_context()
    return _roll_formula_total_with_context(formula, context)


def _is_valid_formula(formula: str) -> bool:
    try:
        _parse_formula_terms(formula)
        return True
    except ValueError:
        return False


def _roll_damage_from_spec(spec: dict) -> int:
    if spec["kind"] == "fixed":
        return int(spec["value"])
    if spec["kind"] == "formula":
        return _roll_formula_total_with_context(str(spec["value"]), _default_formula_context())
    raise ValueError(f"Unsupported damage spec: {spec['kind']}")


def _roll_die(sides: int) -> int:
    return __import__("random").randint(1, sides)


def _roll_formula_total_with_context(formula: str, context: dict[str, int]) -> int:
    total = 0
    for sign, token in _parse_formula_terms(formula):
        if "d" in token.lower():
            count, sides = _parse_dice_token(token)
            total += sign * sum(_roll_die(sides) for _ in range(count))
            continue
        integer_value = _coerce_integer(token)
        if integer_value is not None:
            total += sign * integer_value
            continue
        symbol = _normalize_formula_symbol(token)
        if symbol not in context:
            raise ValueError(f"Unsupported formula symbol: {token}")
        total += sign * context[symbol]
    return total


def _parse_formula_terms(formula: str) -> list[tuple[int, str]]:
    text = formula.replace(" ", "")
    if not text:
        raise ValueError("Formula must not be empty.")
    if text[0] not in "+-":
        text = f"+{text}"
    parts = re.findall(r"([+-])([^+-]+)", text)
    if not parts or "".join(sign + token for sign, token in parts) != text:
        raise ValueError("Formula must be a sum of dice, integers, or supported symbols.")
    return [(1 if sign == "+" else -1, token) for sign, token in parts]


def _parse_dice_token(token: str) -> tuple[int, int]:
    match = re.match(r"^(\d*)d(\d+)$", token.lower())
    if not match:
        raise ValueError(f"Invalid dice token: {token}")
    count = int(match.group(1) or "1")
    sides = int(match.group(2))
    if count <= 0 or sides <= 0:
        raise ValueError("Dice count and sides must be positive.")
    return count, sides


def _normalize_formula_symbol(token: str) -> str:
    return token.strip().upper()


def _default_formula_context() -> dict[str, int]:
    return {
        "STR": 0,
        "DEX": 0,
        "CON": 0,
        "INT": 0,
        "WIS": 0,
        "CHA": 0,
        "PB": 0,
        "PROF": 0,
        "PROFICIENCY": 0,
    }


def _resolve_weapon_profile(weapon: str | None, actor_character) -> dict | None:
    if actor_character is not None:
        weapon_loadout = json_loads(actor_character["weapon_loadout_json"], {})
        if isinstance(weapon_loadout, dict) and weapon_loadout:
            active_slot = weapon_loadout.get("active_slot", "primary")
            active_weapon = weapon_loadout.get(active_slot)
            if isinstance(active_weapon, dict) and active_weapon:
                if weapon:
                    equipped_name = _coerce_text(active_weapon.get("name"))
                    if not equipped_name or equipped_name.lower() == weapon.lower():
                        return _merge_weapon_profile_with_srd_fallback(active_weapon)
                else:
                    return _merge_weapon_profile_with_srd_fallback(active_weapon)
        equipped_weapon = json_loads(actor_character["equipped_weapon_json"], {})
        if isinstance(equipped_weapon, dict) and equipped_weapon:
            if weapon:
                equipped_name = _coerce_text(equipped_weapon.get("name"))
                if equipped_name and equipped_name.lower() != weapon.lower():
                    return _lookup_srd_weapon_profile(weapon)
            return _merge_weapon_profile_with_srd_fallback(equipped_weapon)
    if weapon:
        return _lookup_srd_weapon_profile(weapon)
    return None


def _resolve_attack_roll_state(
    *,
    actor_combatant,
    target_combatant,
    action: ProposedAction,
    actor_character,
    weapon_profile: dict | None,
    target_distance_feet: int | None,
    is_ranged_attack: bool,
) -> tuple[str, list[int], list[str]]:
    advantages = 0
    disadvantages = 0
    sources: list[str] = []

    actor_conditions = _extract_combatant_conditions(actor_combatant)
    target_conditions = _extract_combatant_conditions(target_combatant)
    actor_effects = _extract_combatant_effects(actor_combatant)
    if "blinded" in actor_conditions:
        disadvantages += 1
        sources.append("actor_blinded")
    if "poisoned" in actor_conditions:
        disadvantages += 1
        sources.append("actor_poisoned")
    if "prone" in actor_conditions:
        disadvantages += 1
        sources.append("actor_prone")
    if "blinded" in target_conditions:
        advantages += 1
        sources.append("target_blinded")
    if "prone" in target_conditions:
        if is_ranged_attack:
            disadvantages += 1
            sources.append("target_prone_vs_ranged")
        else:
            advantages += 1
            sources.append("target_prone_vs_melee")
    if _has_sap_disadvantage_effect(actor_effects):
        disadvantages += 1
        sources.append("mastery_sap")
    if _has_vex_advantage_effect(actor_effects, target_combatant_id=int(target_combatant["id"])):
        advantages += 1
        sources.append("mastery_vex")
    if (
        weapon_profile is not None
        and is_ranged_attack
        and target_distance_feet is not None
    ):
        normal_range = _coerce_integer(weapon_profile.get("normal_range"))
        long_range = _coerce_integer(weapon_profile.get("long_range"))
        if (
            normal_range is not None
            and long_range is not None
            and normal_range < target_distance_feet <= long_range
        ):
            disadvantages += 1
            sources.append("target_beyond_normal_range")

    if advantages > 0 and disadvantages > 0:
        return "normal", [_roll_die(20)], sources
    if advantages > 0:
        return "advantage", [_roll_die(20), _roll_die(20)], sources
    if disadvantages > 0:
        return "disadvantage", [_roll_die(20), _roll_die(20)], sources
    return "normal", [_roll_die(20)], sources


def _is_light_extra_attack(action: ProposedAction) -> bool:
    return _coerce_bool(action.parameters.get("light_extra_attack")) or _coerce_bool(action.parameters.get("light_bonus_attack"))


def _resolve_light_extra_attack(
    *,
    prior_attack_details: list[dict],
    action: ProposedAction,
    weapon_profile: dict | None,
) -> bool:
    if _is_light_extra_attack(action):
        return True
    if weapon_profile is None or not bool(weapon_profile.get("light")):
        return False
    prior = _find_prior_non_extra_light_attack(prior_attack_details)
    if prior is None:
        return False
    current_weapon_name = _coerce_text(weapon_profile.get("name"))
    prior_weapon_name = _coerce_text(prior.get("weapon_name"))
    if not current_weapon_name or not prior_weapon_name:
        return False
    if current_weapon_name.strip().lower() == prior_weapon_name.strip().lower():
        return False
    if _summarize_turn_attack_state(prior_attack_details)["light_extra_attack_used"]:
        return False
    return True


def _validate_attack_action_slot(
    *,
    actor_character,
    prior_attack_details: list[dict],
    attack_timing: str,
    light_extra_attack: bool,
) -> str | None:
    if attack_timing != "action" or light_extra_attack:
        return None
    action_attack_limit = _resolve_attack_action_attack_limit(actor_character)
    action_primary_attacks_used = _count_action_primary_attacks(prior_attack_details)
    if action_primary_attacks_used >= action_attack_limit:
        return (
            f"This combatant can make only {action_attack_limit} attack(s) as part of the Attack action right now. "
            f"Attack action slots used: {action_primary_attacks_used}/{action_attack_limit}."
        )
    return None


def _validate_attack_timing_slot(
    *,
    prior_attack_details: list[dict],
    attack_timing: str,
) -> str | None:
    if attack_timing != "bonus_action":
        return None
    timing_counts = _summarize_turn_attack_state(prior_attack_details)["attack_timing_counts"]
    if int(timing_counts.get("bonus_action", 0)) >= 1:
        return "This combatant has already made a Bonus Action attack this turn."
    return None


def _validate_light_extra_attack(
    *,
    actor_id: str | None,
    prior_attack_details: list[dict],
    weapon_profile: dict | None,
    mastery_property: str | None,
    attack_timing: str,
) -> str | None:
    if actor_id is None:
        return "Light extra attacks require an actor_id."
    if weapon_profile is None or not bool(weapon_profile.get("light")):
        return "The Light property extra attack requires a Light weapon."
    prior = _find_prior_non_extra_light_attack(prior_attack_details)
    if prior is None:
        return "The Light property extra attack requires a prior attack with a different Light weapon on the same turn."
    current_weapon_name = _coerce_text(weapon_profile.get("name"))
    prior_weapon_name = _coerce_text(prior.get("weapon_name"))
    if current_weapon_name and prior_weapon_name and current_weapon_name.strip().lower() == prior_weapon_name.strip().lower():
        return "The Light property extra attack must use a different Light weapon from the earlier attack this turn."
    if _summarize_turn_attack_state(prior_attack_details)["light_extra_attack_used"]:
        return "Only one Light property extra attack can be made per turn."
    if attack_timing == "action" and mastery_property != "nick":
        return "Without Nick mastery, the Light property extra attack must use a Bonus Action."
    return None


def _resolve_attack_timing(action: ProposedAction, *, light_extra_attack: bool = False, mastery_property: str | None = None) -> str:
    timing = _coerce_text(action.parameters.get("attack_timing") or action.parameters.get("timing"))
    if timing:
        normalized = timing.strip().lower().replace(" ", "_")
        if normalized in {"action", "bonus_action", "reaction"}:
            return normalized
    if light_extra_attack:
        return "action" if mastery_property == "nick" else "bonus_action"
    return "action"


def _is_loading_weapon_attack_blocked(
    *,
    prior_attack_details: list[dict],
    weapon_profile: dict | None,
    attack_timing: str,
) -> bool:
    if weapon_profile is None or not bool(weapon_profile.get("loading")):
        return False
    for details in prior_attack_details:
        if not bool(details.get("loading_weapon")):
            continue
        prior_timing = _coerce_text(details.get("attack_timing"))
        if prior_timing and prior_timing.strip().lower() == attack_timing:
            return True
    return False


def _find_prior_attack_details(connection: Connection, *, turn_id: int, actor_id: str) -> list[dict]:
    rows = connection.execute(
        """
        SELECT details_json
        FROM game_events
        WHERE turn_id = ? AND actor_id = ? AND event_type = 'attack_roll'
        ORDER BY event_index ASC
        """,
        (turn_id, actor_id),
    ).fetchall()
    details_list: list[dict] = []
    for row in rows:
        details = json_loads(row["details_json"], {})
        if isinstance(details, dict):
            details_list.append(details)
    return details_list


def _summarize_turn_attack_state(prior_attack_details: list[dict], *, actor_character=None) -> dict:
    timing_counts = {"action": 0, "bonus_action": 0, "reaction": 0}
    action_attack_limit = _resolve_attack_action_attack_limit(actor_character)
    action_primary_attacks_used = 0
    light_primary_attack_used = False
    light_extra_attack_used = False
    cleave_used = False
    loading_timings_used: list[str] = []
    for details in prior_attack_details:
        timing = _coerce_text(details.get("attack_timing"))
        if timing:
            normalized_timing = timing.strip().lower()
            if normalized_timing in timing_counts:
                timing_counts[normalized_timing] += 1
            if normalized_timing == "action" and not bool(details.get("light_extra_attack")):
                action_primary_attacks_used += 1
        if bool(details.get("weapon_light")) and not bool(details.get("light_extra_attack")):
            light_primary_attack_used = True
        if bool(details.get("light_extra_attack")):
            light_extra_attack_used = True
        mastery_effects_applied = details.get("mastery_effects_applied", [])
        if isinstance(mastery_effects_applied, list) and ("cleave_extra_attack" in mastery_effects_applied or bool(details.get("cleave_target_id"))):
            cleave_used = True
        if bool(details.get("loading_weapon")) and timing:
            normalized_timing = timing.strip().lower()
            if normalized_timing not in loading_timings_used:
                loading_timings_used.append(normalized_timing)
    return {
        "attack_count": len(prior_attack_details),
        "attack_timing_counts": timing_counts,
        "action_attack_limit": action_attack_limit,
        "action_primary_attacks_used": action_primary_attacks_used,
        "remaining_action_primary_attacks": max(action_attack_limit - action_primary_attacks_used, 0),
        "bonus_action_attack_used": timing_counts["bonus_action"] > 0,
        "remaining_bonus_action_attacks": max(1 - timing_counts["bonus_action"], 0),
        "light_primary_attack_used": light_primary_attack_used,
        "light_extra_attack_used": light_extra_attack_used,
        "cleave_used": cleave_used,
        "loading_timings_used": loading_timings_used,
    }


def _find_prior_non_extra_light_attack(prior_attack_details: list[dict]) -> dict | None:
    for details in prior_attack_details:
        if bool(details.get("light_extra_attack")):
            continue
        timing = _coerce_text(details.get("attack_timing"))
        if timing is None or timing.strip().lower() != "action":
            continue
        if bool(details.get("weapon_light")):
            return details
        weapon_name = _coerce_text(details.get("weapon_name"))
        if weapon_name:
            profile = _lookup_srd_weapon_profile(weapon_name)
            if profile is not None and bool(profile.get("light")):
                return details
    return None


def _count_action_primary_attacks(prior_attack_details: list[dict]) -> int:
    return int(_summarize_turn_attack_state(prior_attack_details)["action_primary_attacks_used"])


def _resolve_attack_action_attack_limit(actor_character) -> int:
    if actor_character is None:
        return 1
    class_name = _coerce_text(actor_character["class_name"])
    level = _coerce_positive_int(actor_character["level"]) or 1
    if not class_name:
        return 1
    normalized_class = class_name.strip().lower()
    if normalized_class == "fighter":
        if level >= 20:
            return 4
        if level >= 11:
            return 3
        if level >= 5:
            return 2
        return 1
    if normalized_class in {"barbarian", "monk", "paladin", "ranger"} and level >= 5:
        return 2
    return 1


def _has_used_cleave_this_turn(prior_attack_details: list[dict]) -> bool:
    return bool(_summarize_turn_attack_state(prior_attack_details)["cleave_used"])


def _extract_combatant_conditions(combatant) -> set[str]:
    if combatant is None:
        return set()
    loaded = json_loads(combatant.get("conditions_json"), [])
    if not isinstance(loaded, list):
        return set()
    return {
        str(item).strip().lower()
        for item in loaded
        if isinstance(item, str) and item.strip()
    }


def _extract_combatant_effects(combatant) -> list[dict]:
    if combatant is None:
        return []
    loaded = json_loads(combatant.get("effects_json"), [])
    if not isinstance(loaded, list):
        return []
    return [effect for effect in loaded if isinstance(effect, dict)]


def _has_sap_disadvantage_effect(effects: list[dict]) -> bool:
    return any(str(effect.get("type", "")).strip().lower() == "mastery_sap_disadvantage" for effect in effects)


def _has_vex_advantage_effect(effects: list[dict], *, target_combatant_id: int) -> bool:
    for effect in effects:
        if str(effect.get("type", "")).strip().lower() != "mastery_vex_advantage":
            continue
        if _coerce_integer(effect.get("target_combatant_id")) == target_combatant_id:
            return True
    return False


def _resolve_mastery_property(profile: dict | None) -> str | None:
    if profile is None or not bool(profile.get("mastery_enabled")):
        return None
    mastery_property = _coerce_text(profile.get("mastery_property"))
    if mastery_property is None:
        return None
    normalized = mastery_property.strip().lower()
    return normalized if normalized in {"cleave", "graze", "nick", "push", "sap", "slow", "topple", "vex"} else None


def _apply_graze_mastery_on_miss(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    actor_character,
    target_combatant,
    weapon_profile: dict | None,
    mastery_property: str | None,
) -> int:
    if mastery_property != "graze" or actor_character is None or weapon_profile is None:
        return 0
    ability_modifiers = _normalized_ability_modifiers(actor_character["ability_modifiers_json"])
    ability_symbol = _resolve_attack_ability_symbol(weapon_profile, ability_modifiers)
    graze_damage = ability_modifiers.get(ability_symbol, 0)
    if graze_damage <= 0:
        return 0
    updated = apply_damage_to_combatant(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        target_ref=str(target_combatant["id"]),
        amount=graze_damage,
    )
    return graze_damage if updated is not None else 0


def _apply_mastery_on_hit(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    actor_combatant,
    actor_character,
    target_combatant,
    weapon_profile: dict | None,
    mastery_property: str | None,
    damage_amount: int,
    details: dict,
    turn_id: int,
    action: ProposedAction,
    changed_entities: list[str],
    light_extra_attack: bool,
) -> None:
    if mastery_property == "cleave" and actor_combatant is not None and target_combatant is not None and weapon_profile is not None:
        cleave_applied = _apply_cleave_mastery_on_hit(
            connection,
            campaign_id=campaign_id,
            session_id=session_id,
            actor_combatant=actor_combatant,
            actor_character=actor_character,
            first_target_combatant=target_combatant,
            weapon_profile=weapon_profile,
            turn_id=turn_id,
            action=action,
            details=details,
            changed_entities=changed_entities,
        )
        if cleave_applied:
            details["mastery_effects_applied"].append("cleave_extra_attack")
    if mastery_property == "nick" and light_extra_attack:
        details["mastery_effects_applied"].append("nick_light_extra_attack")
    if mastery_property == "push" and actor_combatant is not None and target_combatant is not None:
        push_applied = _apply_push_mastery_on_hit(
            connection,
            actor_combatant=actor_combatant,
            target_combatant=target_combatant,
            details=details,
        )
        if push_applied:
            details["mastery_effects_applied"].append("push_10_feet")
    if mastery_property == "slow" and target_combatant is not None and damage_amount > 0:
        slow_applied = _apply_slow_mastery_on_hit(
            connection,
            target_combatant=target_combatant,
            details=details,
        )
        if slow_applied:
            details["mastery_effects_applied"].append("slow_speed_minus_10")
    if mastery_property == "topple" and actor_character is not None and target_combatant is not None and weapon_profile is not None:
        topple_applied = _apply_topple_mastery_on_hit(
            connection,
            actor_character=actor_character,
            target_combatant=target_combatant,
            weapon_profile=weapon_profile,
            details=details,
        )
        if topple_applied:
            details["mastery_effects_applied"].append("topple_prone")
    if mastery_property == "sap" and actor_combatant is not None and target_combatant is not None:
        _append_combatant_effect(
            connection,
            combatant_id=int(target_combatant["id"]),
            effect={
                "name": "Sap",
                "type": "mastery_sap_disadvantage",
                "duration_rounds": 1,
                "source_combatant_id": int(actor_combatant["id"]),
            },
        )
        details["mastery_effects_applied"].append("sap_disadvantage")
    if mastery_property == "vex" and actor_combatant is not None and target_combatant is not None and damage_amount > 0:
        _append_combatant_effect(
            connection,
            combatant_id=int(actor_combatant["id"]),
            effect={
                "name": "Vex",
                "type": "mastery_vex_advantage",
                "duration_rounds": 2,
                "target_combatant_id": int(target_combatant["id"]),
            },
        )
        details["mastery_effects_applied"].append("vex_advantage")


def _apply_push_mastery_on_hit(connection: Connection, *, actor_combatant, target_combatant, details: dict) -> bool:
    target_size = _normalize_combatant_size(target_combatant.get("size"))
    details["mastery_target_size"] = target_size
    if not _is_push_target_size_eligible(target_size):
        details["mastery_push_blocked_reason"] = "Push affects only Large or smaller targets."
        return False
    actor_position = _extract_combatant_position(actor_combatant)
    target_position = _extract_combatant_position(target_combatant)
    if actor_position is None or target_position is None:
        details["mastery_push_blocked_reason"] = "Push requires known actor and target positions."
        return False
    actor_x, actor_y = actor_position
    target_x, target_y = target_position
    dx = target_x - actor_x
    dy = target_y - actor_y
    distance = math.dist(actor_position, target_position)
    if distance <= 0:
        details["mastery_push_blocked_reason"] = "Push requires the target to be away from the attacker."
        return False
    pushed_x = int(round(target_x + ((dx / distance) * 10)))
    pushed_y = int(round(target_y + ((dy / distance) * 10)))
    if pushed_x == target_x and pushed_y == target_y:
        details["mastery_push_blocked_reason"] = "Push could not resolve a new target position."
        return False
    connection.execute(
        """
        UPDATE combatants
        SET position_x = ?, position_y = ?
        WHERE id = ?
        """,
        (pushed_x, pushed_y, int(target_combatant["id"])),
    )
    details["mastery_push_distance_feet"] = int(round(math.dist((target_x, target_y), (pushed_x, pushed_y))))
    details["mastery_target_position_before"] = {"x": target_x, "y": target_y}
    details["mastery_target_position_after"] = {"x": pushed_x, "y": pushed_y}
    return True


def _apply_slow_mastery_on_hit(connection: Connection, *, target_combatant, details: dict) -> bool:
    combatant_id = int(target_combatant["id"])
    remove_combat_effect(connection, combatant_id=combatant_id, effect_name="Slow")
    updated = add_combat_effect(
        connection,
        combatant_id=combatant_id,
        effect_name="Slow",
        effect_type="mastery_slow_speed_penalty",
        modifier=-10,
        duration_rounds=1,
    )
    if updated is None:
        return False
    details["mastery_target_speed_before"] = target_combatant.get("speed")
    details["mastery_target_speed_after"] = updated.get("speed")
    return True


def _apply_topple_mastery_on_hit(connection: Connection, *, actor_character, target_combatant, weapon_profile: dict, details: dict) -> bool:
    save_bonus = _resolve_combatant_save_bonus(connection, target_combatant=target_combatant, ability_symbol="CON")
    if save_bonus is None:
        return False
    dc = 8 + _resolve_attack_ability_modifier(weapon_profile, actor_character) + int(actor_character["proficiency_bonus"] or 0)
    save_roll = _roll_die(20)
    save_total = save_roll + save_bonus
    save_succeeded = save_total >= dc
    details["topple_save_dc"] = dc
    details["topple_save_roll"] = save_roll
    details["topple_save_bonus"] = save_bonus
    details["topple_save_total"] = save_total
    details["topple_save_succeeded"] = save_succeeded
    if save_succeeded:
        return False
    return _add_combatant_condition(connection, combatant_id=int(target_combatant["id"]), condition="prone")


def _apply_cleave_mastery_on_hit(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    actor_combatant,
    actor_character,
    first_target_combatant,
    weapon_profile: dict,
    turn_id: int,
    action: ProposedAction,
    details: dict,
    changed_entities: list[str],
) -> bool:
    if _is_ranged_attack(action, actor_character, weapon_profile=weapon_profile, target_distance_feet=None):
        return False
    cleave_target_ref = _coerce_text(action.parameters.get("cleave_target_id") or action.parameters.get("secondary_target_id"))
    if not cleave_target_ref:
        return False
    if action.actor_id and _has_used_cleave_this_turn(_find_prior_attack_details(connection, turn_id=turn_id, actor_id=action.actor_id)):
        return False
    second_target = find_active_combatant(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        target_ref=cleave_target_ref,
    )
    if second_target is None or int(second_target["id"]) == int(first_target_combatant["id"]):
        return False
    if not _is_valid_cleave_target(actor_combatant=actor_combatant, first_target_combatant=first_target_combatant, second_target_combatant=second_target, weapon_profile=weapon_profile):
        return False
    attack_bonus = _compute_attack_bonus_from_profile(weapon_profile, actor_character) + get_combatant_effect_modifier(actor_combatant, "attack_bonus")
    second_distance, _ = _resolve_target_distance_feet(action=action, actor_combatant=actor_combatant, target_combatant=second_target)
    advantage_state, roll_values, _ = _resolve_attack_roll_state(
        actor_combatant=actor_combatant,
        target_combatant=second_target,
        action=action,
        actor_character=actor_character,
        weapon_profile=weapon_profile,
        target_distance_feet=second_distance,
        is_ranged_attack=False,
    )
    roll_value = max(roll_values) if advantage_state == "advantage" else min(roll_values) if advantage_state == "disadvantage" else roll_values[0]
    total = roll_value + attack_bonus
    hit = roll_value == 20 or (roll_value != 1 and total >= int(second_target["armor_class"]))
    details["cleave_target_id"] = str(second_target["id"])
    details["cleave_target_name"] = second_target["name"]
    details["cleave_hit"] = hit
    details["cleave_attack_roll"] = roll_value
    details["cleave_attack_total"] = total
    if not hit:
        details["cleave_damage_amount"] = 0
        return False
    damage_spec = _damage_spec_from_profile(weapon_profile, actor_character, action=action, suppress_positive_ability_modifier=True)
    if damage_spec is None:
        return False
    damage_amount = _roll_damage_from_spec(damage_spec) + get_combatant_effect_modifier(actor_combatant, "damage_bonus")
    if damage_amount < 0:
        damage_amount = 0
    updated = apply_damage_to_combatant(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        target_ref=str(second_target["id"]),
        amount=damage_amount,
    )
    if updated is None:
        details["cleave_damage_amount"] = 0
        return False
    details["cleave_damage_amount"] = damage_amount
    changed_ref = updated["source_character_id"] or str(updated["id"])
    if changed_ref not in changed_entities:
        changed_entities.append(changed_ref)
    return True


def _append_combatant_effect(connection: Connection, *, combatant_id: int, effect: dict) -> None:
    row = connection.execute(
        """
        SELECT effects_json, armor_class
        FROM combatants
        WHERE id = ?
        """,
        (combatant_id,),
    ).fetchone()
    if row is None:
        return
    effects = json_loads(row["effects_json"], [])
    if not isinstance(effects, list):
        effects = []
    effects.append(effect)
    connection.execute(
        """
        UPDATE combatants
        SET effects_json = ?, armor_class = ?
        WHERE id = ?
        """,
        (json_dumps(effects), row["armor_class"], combatant_id),
    )


def _consume_attack_mastery_effects(connection: Connection, *, actor_combatant, target_combatant, condition_sources: list[str]) -> None:
    if actor_combatant is None:
        return
    actor_id = int(actor_combatant["id"])
    if "mastery_sap" in condition_sources:
        _remove_first_matching_combatant_effect(
            connection,
            combatant_id=actor_id,
            predicate=lambda effect: str(effect.get("type", "")).strip().lower() == "mastery_sap_disadvantage",
        )
    if "mastery_vex" in condition_sources and target_combatant is not None:
        target_id = int(target_combatant["id"])
        _remove_first_matching_combatant_effect(
            connection,
            combatant_id=actor_id,
            predicate=lambda effect: (
                str(effect.get("type", "")).strip().lower() == "mastery_vex_advantage"
                and _coerce_integer(effect.get("target_combatant_id")) == target_id
            ),
        )


def _remove_first_matching_combatant_effect(connection: Connection, *, combatant_id: int, predicate) -> None:
    row = connection.execute(
        """
        SELECT effects_json, armor_class
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
    removed = False
    for effect in effects:
        if not removed and isinstance(effect, dict) and predicate(effect):
            removed = True
            continue
        remaining.append(effect)
    if not removed:
        return
    connection.execute(
        """
        UPDATE combatants
        SET effects_json = ?, armor_class = ?
        WHERE id = ?
        """,
        (json_dumps(remaining), row["armor_class"], combatant_id),
    )


INCAPACITATING_CONDITIONS = {"incapacitated", "paralyzed", "petrified", "stunned", "unconscious"}


def _conditions_impose_incapacitated(conditions: list[str] | set[str]) -> bool:
    return any(str(item).strip().lower() in INCAPACITATING_CONDITIONS for item in conditions)


def _combatant_has_incapacitating_condition(combatant) -> bool:
    return _conditions_impose_incapacitated(_extract_combatant_conditions(combatant))


def _break_concentration_for_character_if_active(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    character_id: str,
) -> list[dict]:
    combatant = find_active_combatant(
        connection,
        campaign_id=campaign_id,
        session_id=session_id,
        target_ref=character_id,
    )
    if combatant is None:
        return []
    return clear_concentration_effects_for_source(connection, source_combatant_id=int(combatant["id"]))


def _is_ranged_attack(
    action: ProposedAction,
    actor_character,
    *,
    weapon_profile: dict | None = None,
    target_distance_feet: int | None = None,
) -> bool:
    profile = weapon_profile
    if profile is None:
        weapon = _coerce_text(action.parameters.get("weapon"))
        profile = _resolve_weapon_profile(weapon, actor_character)
    if profile is not None:
        if _is_thrown_attack(action, actor_character, weapon_profile=profile, target_distance_feet=target_distance_feet):
            return True
        return bool(profile.get("ranged"))
    return False


def _is_thrown_attack(
    action: ProposedAction,
    actor_character,
    *,
    weapon_profile: dict | None = None,
    target_distance_feet: int | None = None,
) -> bool:
    profile = weapon_profile
    if profile is None:
        weapon = _coerce_text(action.parameters.get("weapon"))
        profile = _resolve_weapon_profile(weapon, actor_character)
    if profile is None or not bool(profile.get("thrown")):
        return False
    explicit_mode = _coerce_text(action.parameters.get("attack_mode") or action.parameters.get("mode"))
    if explicit_mode:
        normalized_mode = explicit_mode.strip().lower()
        if normalized_mode == "thrown":
            return True
        if normalized_mode == "melee":
            return False
    if _coerce_bool(action.parameters.get("thrown")):
        return True
    if bool(profile.get("ranged")):
        return True
    if target_distance_feet is not None:
        return target_distance_feet > _resolve_melee_reach_feet(profile, actor_character)
    return False


def _resolve_ammunition_item(profile: dict | None) -> str | None:
    if profile is None:
        return None
    return _coerce_text(profile.get("ammunition_item"))


def _should_track_ammunition(profile: dict | None) -> bool:
    if profile is None:
        return False
    return bool(profile.get("track_ammunition"))


def _resolve_melee_reach_feet(profile: dict | None, actor_character) -> int:
    if profile is not None:
        explicit_reach = _coerce_integer(profile.get("reach"))
        if explicit_reach is not None and explicit_reach > 0:
            return explicit_reach
        if bool(profile.get("ranged")):
            return 5
    if actor_character is not None:
        equipped = _resolve_weapon_profile(None, actor_character)
        if equipped is not None:
            explicit_reach = _coerce_integer(equipped.get("reach"))
            if explicit_reach is not None and explicit_reach > 0:
                return explicit_reach
    return 5


def _compute_attack_bonus_from_profile(profile: dict, actor_character) -> int:
    ability_modifiers = _normalized_ability_modifiers(actor_character["ability_modifiers_json"])
    if not ability_modifiers and _coerce_text(profile.get("name")):
        return 5
    ability_symbol = _resolve_attack_ability_symbol(profile, ability_modifiers)
    proficiency_bonus = int(actor_character["proficiency_bonus"] or 0)
    proficient = bool(profile.get("proficient", True))
    return ability_modifiers.get(ability_symbol, 0) + (proficiency_bonus if proficient else 0)


def _resolve_attack_ability_modifier(profile: dict, actor_character) -> int:
    ability_modifiers = _normalized_ability_modifiers(actor_character["ability_modifiers_json"])
    if not ability_modifiers:
        return 0
    ability_symbol = _resolve_attack_ability_symbol(profile, ability_modifiers)
    return ability_modifiers.get(ability_symbol, 0)


def _damage_spec_from_profile(
    profile: dict,
    actor_character,
    *,
    action: ProposedAction | None = None,
    suppress_positive_ability_modifier: bool = False,
) -> dict | None:
    damage_dice = _resolve_damage_dice(profile, action=action)
    if not damage_dice:
        return None
    ability_modifiers = _normalized_ability_modifiers(actor_character["ability_modifiers_json"])
    ability_symbol = _resolve_attack_ability_symbol(profile, ability_modifiers)
    damage_bonus = _coerce_integer(profile.get("damage_bonus"))
    if damage_bonus is None:
        damage_bonus = ability_modifiers.get(ability_symbol, 3 if _coerce_text(profile.get("name")) and not ability_modifiers else 0)
        if suppress_positive_ability_modifier and damage_bonus > 0:
            damage_bonus = 0
    if damage_bonus >= 0:
        formula = f"{damage_dice}+{damage_bonus}"
    else:
        formula = f"{damage_dice}{damage_bonus}"
    return {"kind": "formula", "value": formula}


def _resolve_damage_dice(profile: dict, *, action: ProposedAction | None = None) -> str | None:
    damage_dice = _coerce_text(profile.get("damage_dice"))
    if not damage_dice:
        return None
    versatile_damage_dice = _coerce_text(profile.get("versatile_damage_dice"))
    if versatile_damage_dice and _uses_versatile_damage(profile, action):
        return versatile_damage_dice
    return damage_dice


def _resolve_combatant_save_bonus(connection: Connection, *, target_combatant, ability_symbol: str) -> int | None:
    normalized_symbol = ability_symbol.strip().upper()
    if normalized_symbol not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}:
        return None
    save_bonuses = json_loads(target_combatant.get("saving_throw_bonuses_json"), {})
    if isinstance(save_bonuses, dict):
        explicit = save_bonuses.get(normalized_symbol)
        if isinstance(explicit, int) and not isinstance(explicit, bool):
            return explicit
    source_character_id = _coerce_text(target_combatant.get("source_character_id"))
    if source_character_id:
        row = connection.execute(
            """
            SELECT ability_modifiers_json
            FROM characters
            WHERE id = ?
            """,
            (source_character_id,),
        ).fetchone()
        if row is not None:
            return _normalized_ability_modifiers(row["ability_modifiers_json"]).get(normalized_symbol, 0)
    return 0


def _add_combatant_condition(connection: Connection, *, combatant_id: int, condition: str) -> bool:
    row = connection.execute(
        """
        SELECT source_character_id, conditions_json
        FROM combatants
        WHERE id = ?
        """,
        (combatant_id,),
    ).fetchone()
    if row is None:
        return False
    current_conditions = json_loads(row["conditions_json"], [])
    if not isinstance(current_conditions, list):
        current_conditions = []
    normalized = condition.strip().lower()
    if normalized in current_conditions:
        return False
    current_conditions.append(normalized)
    connection.execute(
        """
        UPDATE combatants
        SET conditions_json = ?
        WHERE id = ?
        """,
        (json_dumps(current_conditions), combatant_id),
    )
    source_character_id = _coerce_text(row["source_character_id"])
    if source_character_id:
        _update_character_conditions(connection, source_character_id, current_conditions)
    return True


def _is_valid_cleave_target(*, actor_combatant, first_target_combatant, second_target_combatant, weapon_profile: dict) -> bool:
    actor_position = _extract_combatant_position(actor_combatant)
    first_target_position = _extract_combatant_position(first_target_combatant)
    second_target_position = _extract_combatant_position(second_target_combatant)
    if actor_position is None or first_target_position is None or second_target_position is None:
        return False
    if int(round(math.dist(first_target_position, second_target_position))) > 5:
        return False
    return int(round(math.dist(actor_position, second_target_position))) <= _resolve_melee_reach_feet(weapon_profile, None)


def _uses_versatile_damage(profile: dict, action: ProposedAction | None) -> bool:
    if action is None:
        return False
    if bool(profile.get("ranged")):
        return False
    return _coerce_bool(action.parameters.get("use_two_hands")) or _coerce_bool(action.parameters.get("two_handed"))


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"1", "true", "yes", "y", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _normalized_ability_modifiers(raw_json: str) -> dict[str, int]:
    loaded = json_loads(raw_json, {})
    result: dict[str, int] = {}
    if not isinstance(loaded, dict):
        return result
    for key, value in loaded.items():
        int_value = _coerce_integer(value)
        if int_value is None:
            continue
        result[str(key).upper()] = int_value
    return result


def _resolve_attack_ability_symbol(profile: dict, ability_modifiers: dict[str, int]) -> str:
    explicit = _coerce_text(profile.get("attack_ability"))
    if explicit:
        normalized = explicit.upper()
        if normalized in ability_modifiers:
            return normalized
    if bool(profile.get("finesse")):
        str_mod = ability_modifiers.get("STR", 0)
        dex_mod = ability_modifiers.get("DEX", 0)
        return "DEX" if dex_mod > str_mod else "STR"
    if bool(profile.get("ranged")):
        return "DEX"
    return "STR"


def _lookup_srd_weapon_profile(weapon: str) -> dict | None:
    normalized = weapon.strip().lower()
    profile = SRD_WEAPON_FALLBACK_PROFILES.get(normalized)
    if profile is None:
        return None
    enriched = dict(profile)
    mastery_property = SRD_WEAPON_MASTERY_PROPERTIES.get(normalized)
    if mastery_property and "mastery_property" not in enriched:
        enriched["mastery_property"] = mastery_property
    return enriched


def _merge_weapon_profile_with_srd_fallback(profile: dict) -> dict:
    merged = dict(profile)
    weapon_name = _coerce_text(profile.get("name"))
    if not weapon_name:
        return merged
    fallback = _lookup_srd_weapon_profile(weapon_name)
    if fallback is None:
        return merged
    enriched = dict(fallback)
    for key, value in merged.items():
        if value is None:
            continue
        if isinstance(value, bool) and value is False and isinstance(enriched.get(key), bool):
            continue
        enriched[key] = value
    return enriched


def _resolve_target_distance_feet(*, action: ProposedAction, actor_combatant, target_combatant) -> tuple[int | None, str | None]:
    explicit_distance = _coerce_integer(
        action.parameters.get("target_distance_feet")
        if action.parameters.get("target_distance_feet") is not None
        else action.parameters.get("distance_feet")
    )
    if explicit_distance is not None and explicit_distance >= 0:
        return explicit_distance, "explicit"
    actor_position = _extract_combatant_position(actor_combatant)
    target_position = _extract_combatant_position(target_combatant)
    if actor_position is None or target_position is None:
        return None, None
    return int(round(math.dist(actor_position, target_position))), "position"


def _extract_combatant_position(combatant: dict | None) -> tuple[int, int] | None:
    if not isinstance(combatant, dict):
        return None
    position_x = _coerce_integer(combatant.get("position_x"))
    position_y = _coerce_integer(combatant.get("position_y"))
    if position_x is None or position_y is None:
        return None
    return position_x, position_y


def _normalize_combatant_size(value: object) -> str:
    raw = _coerce_text(value)
    if raw is None:
        return "Medium"
    normalized = raw.strip().capitalize()
    return normalized if normalized in {"Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan"} else "Medium"


def _is_push_target_size_eligible(size: str) -> bool:
    return size in {"Tiny", "Small", "Medium", "Large"}


def _record_event(
    connection: Connection,
    *,
    campaign_id: int,
    session_id: int,
    turn_id: int,
    event_index: int,
    event_type: str,
    actor_id: str | None,
    target_id: str | None,
    details: dict,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO game_events (
          campaign_id, session_id, turn_id, event_index, event_type,
          actor_id, target_id, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            session_id,
            turn_id,
            event_index,
            event_type,
            actor_id,
            target_id,
            json_dumps(details),
            utc_now(),
        ),
    )
    return int(cursor.lastrowid)


def _coerce_combatants(value: object) -> list[CombatantInput]:
    if not isinstance(value, list):
        return []
    combatants: list[CombatantInput] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            combatants.append(CombatantInput.model_validate(item))
        except Exception:
            continue
    return combatants


def _reject(action: ProposedAction, reason: str) -> RejectedAction:
    return RejectedAction(
        type=action.type,
        actor_id=action.actor_id,
        target_ids=list(action.target_ids),
        parameters=dict(action.parameters),
        reason=reason,
    )
