from __future__ import annotations

from sqlite3 import Connection

from backend.app.schemas.characters import PartyAssignRequest, PartyMemberSummary
from backend.app.services.character_service import _hydrate_character
from backend.app.services.utils import row_to_dict, utc_now


def get_party(connection: Connection, campaign_id: int) -> list[PartyMemberSummary]:
    rows = connection.execute(
        """
        SELECT
          pm.campaign_id,
          pm.party_order,
          c.id,
          c.campaign_id AS character_campaign_id,
          c.name,
          c.class_name,
          c.level,
          c.ancestry,
          c.background,
          c.current_hp,
          c.max_hp,
          c.armor_class,
          c.speed,
          c.proficiency_bonus,
          c.ability_modifiers_json,
          c.equipped_weapon_json,
          c.weapon_loadout_json,
          c.conditions_json,
          c.spell_slots_json,
          c.inventory_highlights_json,
          c.notes
        FROM party_members pm
        JOIN characters c ON c.id = pm.character_id
        WHERE pm.campaign_id = ? AND pm.is_active = 1
        ORDER BY pm.party_order
        """,
        (campaign_id,),
    ).fetchall()

    party: list[PartyMemberSummary] = []
    for row in rows:
        item = row_to_dict(row)
        character = _hydrate_character(
            {
                "id": item["id"],
                "campaign_id": item["character_campaign_id"],
                "name": item["name"],
                "class_name": item["class_name"],
                "level": item["level"],
                "ancestry": item["ancestry"],
                "background": item["background"],
                "current_hp": item["current_hp"],
                "max_hp": item["max_hp"],
                "armor_class": item["armor_class"],
                "speed": item["speed"],
                "proficiency_bonus": item["proficiency_bonus"],
                "ability_modifiers_json": item["ability_modifiers_json"],
                "equipped_weapon_json": item["equipped_weapon_json"],
                "weapon_loadout_json": item["weapon_loadout_json"],
                "conditions_json": item["conditions_json"],
                "spell_slots_json": item["spell_slots_json"],
                "inventory_highlights_json": item["inventory_highlights_json"],
                "notes": item["notes"],
            }
        )
        party.append(
            PartyMemberSummary(
                campaign_id=item["campaign_id"],
                party_order=item["party_order"],
                character=character,
            )
        )
    return party


def assign_party_member(connection: Connection, payload: PartyAssignRequest) -> PartyMemberSummary:
    existing = connection.execute(
        """
        SELECT id FROM party_members
        WHERE campaign_id = ? AND party_order = ?
        """,
        (payload.campaign_id, payload.party_order),
    ).fetchone()
    if existing:
        connection.execute(
            """
            DELETE FROM party_members
            WHERE campaign_id = ? AND party_order = ?
            """,
            (payload.campaign_id, payload.party_order),
        )

    connection.execute(
        """
        INSERT INTO party_members (campaign_id, character_id, party_order, is_active, added_at)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(campaign_id, character_id)
        DO UPDATE SET
          party_order = excluded.party_order,
          is_active = 1
        """,
        (payload.campaign_id, payload.character_id, payload.party_order, utc_now()),
    )
    party = get_party(connection, payload.campaign_id)
    for member in party:
        if member.character.id == payload.character_id:
            return member
    raise ValueError("Assigned character was not found in the party.")
