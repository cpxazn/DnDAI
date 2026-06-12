from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.db.session import get_connection, initialize_database
from backend.app.schemas.campaigns import CampaignCreateRequest
from backend.app.schemas.characters import CharacterCreateRequest, PartyAssignRequest, WeaponLoadout, WeaponProfile
from backend.app.schemas.chat import ProposedAction
from backend.app.schemas.combat import CombatOperationRequest, CombatantInput
from backend.app.schemas.sessions import SessionCreateRequest
from backend.app.services.action_service import apply_actions
from backend.app.services.campaign_service import create_campaign
from backend.app.services.character_service import create_character
from backend.app.services.combat_service import apply_combat_operation, get_active_combat
from backend.app.services.inventory_service import add_item
from backend.app.services.party_service import assign_party_member
from backend.app.services.session_service import create_session
from backend.app.services.utils import utc_now


def test_attack_roll_hits_and_applies_damage_to_active_combatant(tmp_path: Path):
    database_path = tmp_path / "attack-roll.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                level=5,
                current_hp=12,
                max_hp=12,
                armor_class=16,
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=7,
                        max_hp=7,
                        armor_class=15,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[15, 8]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longsword"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        assert str(goblin.id) in result.changed_entities
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["target_name"] == "Goblin"
        assert result.applied_actions[0].outcome["hit"] is True
        assert result.applied_actions[0].outcome["damage_amount"] == 11
        assert result.applied_actions[0].outcome["encounter_status"] == "ended"
        assert result.applied_actions[0].outcome["winning_side"] == "players"

        updated = connection.execute(
            "SELECT current_hp FROM combatants WHERE id = ?",
            (goblin.id,),
        ).fetchone()
        assert updated["current_hp"] == 0
        assert get_active_combat(connection, campaign.id, session.id) is None


def test_attack_roll_supports_npc_actor_and_applies_damage_to_party_character(tmp_path: Path):
    database_path = tmp_path / "attack-roll-npc.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        started = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=7,
                        max_hp=7,
                        armor_class=15,
                    ),
                ],
            ),
        )
        assert started is not None
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=started.encounter_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "npc_goblin_1",
                None,
                "Goblin attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[15, 4]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="npc_goblin_1",
                        target_ids=["pc_aric"],
                        parameters={"attack_bonus": 4, "damage_formula": "1d6+2"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        assert "pc_aric" in result.changed_entities
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["target_name"] == "Aric"
        assert result.applied_actions[0].outcome["hit"] is True
        assert result.applied_actions[0].outcome["damage_amount"] == 6
        assert result.applied_actions[0].outcome["encounter_status"] == "active"

        character = connection.execute(
            "SELECT current_hp FROM characters WHERE id = 'pc_aric'",
        ).fetchone()
        assert character["current_hp"] == 6


def test_attack_roll_rejects_when_actor_is_not_active_combatant(tmp_path: Path):
    database_path = tmp_path / "attack-roll-turn-order.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=7,
                        max_hp=7,
                        armor_class=15,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "npc_goblin_1",
                None,
                "Out of turn attack",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        result = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=turn_id,
            actions=[
                ProposedAction(
                    type="attack_roll",
                    actor_id="npc_goblin_1",
                    target_ids=["pc_aric"],
                    parameters={"attack_bonus": 4, "damage_formula": "1d6+2"},
                )
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 1
        assert "active combatant" in result.rejected_actions[0].reason


def test_attack_roll_uses_combat_effect_attack_and_damage_bonuses(tmp_path: Path):
    database_path = tmp_path / "attack-roll-effects.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        name="Champion",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            UPDATE combatants
            SET effects_json = ?
            WHERE name = 'Champion'
            """,
            ('[{"name":"Battle Focus","type":"attack_bonus","modifier":2},{"name":"Divine Favor","type":"damage_bonus","modifier":3}]',),
        )
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "Champion",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[10, 4]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="Champion",
                        target_ids=[str(goblin.id)],
                        parameters={"attack_bonus": 3, "damage_formula": "1d6+1"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["attack_bonus"] == 5
        assert outcome["attack_total"] == 15
        assert outcome["damage_amount"] == 8


def test_attack_roll_applies_disadvantage_from_poisoned_actor(tmp_path: Path):
    database_path = tmp_path / "attack-roll-poisoned.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        name="Champion",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        conditions=["poisoned"],
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "Champion",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[18, 4]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="Champion",
                        target_ids=[str(goblin.id)],
                        parameters={"attack_bonus": 5, "damage_formula": "1d6+1"},
                    )
                ],
            )

        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["advantage_state"] == "disadvantage"
        assert outcome["roll_values"] == [18, 4]
        assert "actor_poisoned" in outcome["condition_sources"]
        assert outcome["attack_roll"] == 4
        assert outcome["hit"] is False
        assert outcome["damage_amount"] == 0


def test_attack_roll_applies_graze_mastery_damage_on_miss(tmp_path: Path):
    database_path = tmp_path / "attack-roll-graze.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Greatsword",
                    "damage_dice": "2d6",
                    "attack_ability": "STR",
                    "proficient": True,
                    "mastery_property": "graze",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=25,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[10]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "greatsword"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["hit"] is False
        assert outcome["damage_amount"] == 4
        assert "graze_damage" in outcome["mastery_effects_applied"]


def test_attack_roll_applies_sap_mastery_to_targets_next_attack(tmp_path: Path):
    database_path = tmp_path / "attack-roll-sap.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Longsword",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                    "mastery_property": "sap",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=12,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Aric attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        first_turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 5]):
            first_result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=first_turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longsword"},
                    )
                ],
            )

        assert len(first_result.applied_actions) == 1
        assert "sap_disadvantage" in first_result.applied_actions[0].outcome["mastery_effects_applied"]

        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=combat.encounter_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                2,
                "assistant",
                "npc_goblin_1",
                None,
                "Goblin attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        second_turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[17, 6, 4]):
            second_result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=second_turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="npc_goblin_1",
                        target_ids=["pc_aric"],
                        parameters={"attack_bonus": 4, "damage_formula": "1d4"},
                    )
                ],
            )

        assert len(second_result.applied_actions) == 1
        assert second_result.rejected_actions == []
        outcome = second_result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["advantage_state"] == "disadvantage"
        assert "mastery_sap" in outcome["condition_sources"]
        assert outcome["roll_values"] == [17, 6]
        assert outcome["attack_roll"] == 6


def test_attack_roll_applies_vex_mastery_to_next_attack_against_same_target(tmp_path: Path):
    database_path = tmp_path / "attack-roll-vex.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Rogue",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 4},
                equipped_weapon={
                    "name": "Shortbow",
                    "damage_dice": "1d6",
                    "attack_ability": "DEX",
                    "proficient": True,
                    "ranged": True,
                    "mastery_property": "vex",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=12,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Aric first attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        first_turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 4]):
            first_result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=first_turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "shortbow"},
                    )
                ],
            )

        assert len(first_result.applied_actions) == 1
        assert "vex_advantage" in first_result.applied_actions[0].outcome["mastery_effects_applied"]

        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=combat.encounter_id,
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=combat.encounter_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                2,
                "assistant",
                "pc_aric",
                None,
                "Aric second attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        second_turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[7, 16, 3]):
            second_result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=second_turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "shortbow"},
                    )
                ],
            )

        assert len(second_result.applied_actions) == 1
        assert second_result.rejected_actions == []
        outcome = second_result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["advantage_state"] == "advantage"
        assert "mastery_vex" in outcome["condition_sources"]
        assert outcome["roll_values"] == [7, 16]
        assert outcome["attack_roll"] == 16


def test_attack_roll_applies_push_mastery_and_moves_target_away(tmp_path: Path):
    database_path = tmp_path / "attack-roll-push.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_brom",
                name="Brom",
                class_name="Fighter",
                level=5,
                current_hp=16,
                max_hp=16,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Warhammer",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                    "mastery_property": "push",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_brom", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Hallway Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_brom",
                        name="Brom",
                        initiative=15,
                        current_hp=16,
                        max_hp=16,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                        position_x=0,
                        position_y=0,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=12,
                        position_x=5,
                        position_y=0,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_brom",
                None,
                "Brom drives the goblin back",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "warhammer"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["hit"] is True
        assert outcome["mastery_target_size"] == "Medium"
        assert "push_10_feet" in outcome["mastery_effects_applied"]
        assert outcome["mastery_push_distance_feet"] == 10
        assert outcome["mastery_target_position_before"] == {"x": 5, "y": 0}
        assert outcome["mastery_target_position_after"] == {"x": 15, "y": 0}

        updated = connection.execute(
            """
            SELECT position_x, position_y
            FROM combatants
            WHERE id = ?
            """,
            (goblin.id,),
        ).fetchone()
        assert updated is not None
        assert updated["position_x"] == 15
        assert updated["position_y"] == 0


def test_attack_roll_does_not_apply_push_mastery_to_huge_target(tmp_path: Path):
    database_path = tmp_path / "attack-roll-push-huge.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_brom",
                name="Brom",
                class_name="Fighter",
                level=5,
                current_hp=16,
                max_hp=16,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Warhammer",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                    "mastery_property": "push",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_brom", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Bridge Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_brom",
                        name="Brom",
                        initiative=15,
                        current_hp=16,
                        max_hp=16,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                        position_x=0,
                        position_y=0,
                    ),
                    CombatantInput(
                        name="Hill Giant",
                        initiative=12,
                        current_hp=30,
                        max_hp=30,
                        armor_class=12,
                        size="Huge",
                        position_x=5,
                        position_y=0,
                    ),
                ],
            ),
        )
        assert combat is not None
        giant = next(item for item in combat.combatants if item.name == "Hill Giant")
        assert giant.size == "Huge"
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_brom",
                None,
                "Brom tries to drive the giant back",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(giant.id)],
                        parameters={"weapon": "warhammer"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["hit"] is True
        assert outcome["mastery_target_size"] == "Huge"
        assert outcome["mastery_push_blocked_reason"] == "Push affects only Large or smaller targets."
        assert "push_10_feet" not in outcome["mastery_effects_applied"]
        assert outcome["mastery_push_distance_feet"] is None

        updated = connection.execute(
            """
            SELECT position_x, position_y, size
            FROM combatants
            WHERE id = ?
            """,
            (giant.id,),
        ).fetchone()
        assert updated is not None
        assert updated["position_x"] == 5
        assert updated["position_y"] == 0
        assert updated["size"] == "Huge"


def test_attack_roll_reports_push_mastery_blocked_without_positions(tmp_path: Path):
    database_path = tmp_path / "attack-roll-push-missing-positions.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_brom",
                name="Brom",
                class_name="Fighter",
                level=5,
                current_hp=16,
                max_hp=16,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Warhammer",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                    "mastery_property": "push",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_brom", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Unmapped Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_brom",
                        name="Brom",
                        initiative=15,
                        current_hp=16,
                        max_hp=16,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=12,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_brom",
                None,
                "Brom tries to shove the goblin back",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "warhammer"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["hit"] is True
        assert outcome["mastery_target_size"] == "Medium"
        assert outcome["mastery_push_blocked_reason"] == "Push requires known actor and target positions."
        assert "push_10_feet" not in outcome["mastery_effects_applied"]
        assert outcome["mastery_push_distance_feet"] is None


def test_attack_roll_applies_slow_mastery_without_stacking_speed_penalty(tmp_path: Path):
    database_path = tmp_path / "attack-roll-slow.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_lyra",
                name="Lyra",
                class_name="Ranger",
                level=5,
                current_hp=12,
                max_hp=12,
                armor_class=14,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 4},
                equipped_weapon={
                    "name": "Longbow",
                    "damage_dice": "1d8",
                    "attack_ability": "DEX",
                    "proficient": True,
                    "ranged": True,
                    "mastery_property": "slow",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_lyra", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Forest Skirmish",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_lyra",
                        name="Lyra",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=14,
                        speed=30,
                        is_player=True,
                        party_order=1,
                        position_x=0,
                        position_y=0,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=12,
                        speed=30,
                        position_x=60,
                        position_y=0,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_lyra",
                None,
                "Lyra slows the goblin",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5, 13, 4]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_lyra",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longbow"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_lyra",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longbow"},
                    ),
                ],
            )

        assert len(result.applied_actions) == 2
        first_outcome = result.applied_actions[0].outcome
        second_outcome = result.applied_actions[1].outcome
        assert first_outcome is not None
        assert second_outcome is not None
        assert "slow_speed_minus_10" in first_outcome["mastery_effects_applied"]
        assert first_outcome["mastery_target_speed_before"] == 30
        assert first_outcome["mastery_target_speed_after"] == 20
        assert "slow_speed_minus_10" in second_outcome["mastery_effects_applied"]
        assert second_outcome["mastery_target_speed_before"] == 20
        assert second_outcome["mastery_target_speed_after"] == 20

        updated = connection.execute(
            """
            SELECT speed, effects_json
            FROM combatants
            WHERE id = ?
            """,
            (goblin.id,),
        ).fetchone()
        assert updated is not None
        assert updated["speed"] == 20
        assert updated["effects_json"].count("mastery_slow_speed_penalty") == 1


def test_attack_roll_applies_topple_mastery_and_prones_target_on_failed_save(tmp_path: Path):
    database_path = tmp_path / "attack-roll-topple.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_brom",
                name="Brom",
                class_name="Fighter",
                level=5,
                current_hp=16,
                max_hp=16,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Battleaxe",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                    "mastery_property": "topple",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_brom", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Topple Test",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_brom",
                        name="Brom",
                        initiative=15,
                        current_hp=16,
                        max_hp=16,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=12,
                        saving_throw_bonuses={"CON": 1},
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_brom",
                None,
                "Brom topples the goblin",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5, 8]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "battleaxe"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert "topple_prone" in outcome["mastery_effects_applied"]
        assert outcome["topple_save_dc"] == 14
        assert outcome["topple_save_roll"] == 8
        assert outcome["topple_save_bonus"] == 1
        assert outcome["topple_save_total"] == 9
        assert outcome["topple_save_succeeded"] is False

        updated = connection.execute(
            """
            SELECT conditions_json
            FROM combatants
            WHERE id = ?
            """,
            (goblin.id,),
        ).fetchone()
        assert updated is not None
        assert "prone" in updated["conditions_json"]


def test_attack_roll_topple_uses_zero_save_fallback_for_stat_light_npc(tmp_path: Path):
    database_path = tmp_path / "attack-roll-topple-stat-light-npc.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_brom",
                name="Brom",
                class_name="Fighter",
                level=5,
                current_hp=16,
                max_hp=16,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Battleaxe",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                    "mastery_property": "topple",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_brom", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Topple Stat-Light NPC Test",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_brom",
                        name="Brom",
                        initiative=15,
                        current_hp=16,
                        max_hp=16,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Skeleton",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=13,
                    ),
                ],
            ),
        )
        assert combat is not None
        skeleton = next(item for item in combat.combatants if item.name == "Skeleton")
        assert skeleton.saving_throw_bonuses["CON"] == 0
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_brom",
                None,
                "Brom topples the skeleton",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5, 13]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(skeleton.id)],
                        parameters={"weapon": "battleaxe"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert "topple_prone" in outcome["mastery_effects_applied"]
        assert outcome["topple_save_dc"] == 14
        assert outcome["topple_save_roll"] == 13
        assert outcome["topple_save_bonus"] == 0
        assert outcome["topple_save_total"] == 13
        assert outcome["topple_save_succeeded"] is False

        updated = connection.execute(
            """
            SELECT conditions_json
            FROM combatants
            WHERE id = ?
            """,
            (skeleton.id,),
        ).fetchone()
        assert updated is not None
        assert "prone" in updated["conditions_json"]


def test_attack_roll_topple_uses_proficiency_aware_save_bonus_for_canonical_character_target(tmp_path: Path):
    database_path = tmp_path / "attack-roll-topple-proficient-save.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_brom",
                name="Brom",
                class_name="Fighter",
                level=5,
                current_hp=16,
                max_hp=16,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Battleaxe",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                    "mastery_property": "topple",
                    "mastery_enabled": True,
                },
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_dorn",
                name="Dorn",
                class_name="Fighter",
                level=5,
                current_hp=16,
                max_hp=16,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"CON": 1, "STR": 3},
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_brom", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Topple Save Test",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_brom",
                        name="Brom",
                        initiative=15,
                        current_hp=16,
                        max_hp=16,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        source_character_id="pc_dorn",
                        name="Dorn",
                        initiative=12,
                        current_hp=16,
                        max_hp=16,
                        armor_class=16,
                        is_player=True,
                        party_order=2,
                    ),
                ],
            ),
        )
        assert combat is not None
        dorn = next(item for item in combat.combatants if item.name == "Dorn")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_brom",
                None,
                "Brom tries to topple Dorn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5, 12]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(dorn.id)],
                        parameters={"weapon": "battleaxe"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert "topple_prone" not in outcome["mastery_effects_applied"]
        assert outcome["topple_save_dc"] == 14
        assert outcome["topple_save_roll"] == 12
        assert outcome["topple_save_bonus"] == 3
        assert outcome["topple_save_total"] == 15
        assert outcome["topple_save_succeeded"] is True

        updated = connection.execute(
            """
            SELECT conditions_json
            FROM combatants
            WHERE id = ?
            """,
            (dorn.id,),
        ).fetchone()
        assert updated is not None
        assert "prone" not in updated["conditions_json"]


def test_attack_roll_applies_cleave_mastery_to_second_target_once_per_turn(tmp_path: Path):
    database_path = tmp_path / "attack-roll-cleave.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_brom",
                name="Brom",
                class_name="Fighter",
                level=5,
                current_hp=16,
                max_hp=16,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Halberd",
                    "damage_dice": "1d10",
                    "attack_ability": "STR",
                    "proficient": True,
                    "reach": 10,
                    "mastery_property": "cleave",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_brom", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Cleave Test",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_brom",
                        name="Brom",
                        initiative=15,
                        current_hp=16,
                        max_hp=16,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                        position_x=0,
                        position_y=0,
                    ),
                    CombatantInput(
                        name="Goblin One",
                        initiative=12,
                        current_hp=16,
                        max_hp=16,
                        armor_class=12,
                        position_x=5,
                        position_y=0,
                    ),
                    CombatantInput(
                        name="Goblin Two",
                        initiative=10,
                        current_hp=16,
                        max_hp=16,
                        armor_class=12,
                        position_x=10,
                        position_y=0,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin_one = next(item for item in combat.combatants if item.name == "Goblin One")
        goblin_two = next(item for item in combat.combatants if item.name == "Goblin Two")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_brom",
                None,
                "Brom cleaves through both goblins",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 6, 13, 5, 12, 4]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(goblin_one.id)],
                        parameters={"weapon": "halberd", "cleave_target_id": str(goblin_two.id)},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(goblin_one.id)],
                        parameters={"weapon": "halberd", "cleave_target_id": str(goblin_two.id)},
                    ),
                ],
            )

        assert len(result.applied_actions) == 2
        first_outcome = result.applied_actions[0].outcome
        second_outcome = result.applied_actions[1].outcome
        assert first_outcome is not None
        assert second_outcome is not None
        assert "cleave_extra_attack" in first_outcome["mastery_effects_applied"]
        assert first_outcome["cleave_target_id"] == str(goblin_two.id)
        assert first_outcome["cleave_hit"] is True
        assert first_outcome["cleave_damage_amount"] == 5
        assert "cleave_extra_attack" not in second_outcome["mastery_effects_applied"]

        first_hp = connection.execute("SELECT current_hp FROM combatants WHERE id = ?", (goblin_one.id,)).fetchone()
        second_hp = connection.execute("SELECT current_hp FROM combatants WHERE id = ?", (goblin_two.id,)).fetchone()
        assert first_hp is not None and second_hp is not None
        assert first_hp["current_hp"] == 0
        assert second_hp["current_hp"] == 16 - 5


def test_attack_roll_allows_nick_light_extra_attack_as_part_of_attack_action(tmp_path: Path):
    database_path = tmp_path / "attack-roll-nick.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_lyra",
                name="Lyra",
                class_name="Rogue",
                current_hp=12,
                max_hp=12,
                armor_class=14,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 4},
                equipped_weapon={
                    "name": "Dagger",
                    "damage_dice": "1d4",
                    "attack_ability": "DEX",
                    "finesse": True,
                    "light": True,
                    "thrown": True,
                    "normal_range": 20,
                    "long_range": 60,
                    "proficient": True,
                    "mastery_property": "nick",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_lyra", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Nick Test",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_lyra",
                        name="Lyra",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=14,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=12,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_lyra",
                None,
                "Lyra uses Nick for a second strike",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5, 13, 4]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_lyra",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "scimitar"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_lyra",
                        target_ids=[str(goblin.id)],
                        parameters={
                            "weapon": "dagger",
                        },
                    ),
                ],
            )

        assert len(result.applied_actions) == 2
        first_outcome = result.applied_actions[0].outcome
        second_outcome = result.applied_actions[1].outcome
        assert first_outcome is not None
        assert second_outcome is not None
        assert second_outcome["light_extra_attack"] is True
        assert second_outcome["attack_timing"] == "action"
        assert "nick_light_extra_attack" in second_outcome["mastery_effects_applied"]
        assert first_outcome["turn_attack_state_before"]["attack_count"] == 0
        assert first_outcome["turn_attack_state_after"]["attack_timing_counts"]["action"] == 1
        assert second_outcome["turn_attack_state_before"]["attack_count"] == 1
        assert second_outcome["turn_attack_state_before"]["light_primary_attack_used"] is True
        assert second_outcome["turn_attack_state_after"]["light_extra_attack_used"] is True
        assert second_outcome["turn_attack_state_after"]["bonus_action_attack_used"] is False
        assert second_outcome["turn_attack_state_after"]["remaining_bonus_action_attacks"] == 1

        updated = connection.execute("SELECT current_hp FROM combatants WHERE id = ?", (goblin.id,)).fetchone()
        assert updated is not None
        assert updated["current_hp"] == 20 - 9 - 4


def test_attack_roll_infers_light_extra_attack_with_bonus_action_timing(tmp_path: Path):
    database_path = tmp_path / "attack-roll-light-extra.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_lyra",
                name="Lyra",
                class_name="Rogue",
                current_hp=12,
                max_hp=12,
                armor_class=14,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 4},
                equipped_weapon={
                    "name": "Shortsword",
                    "damage_dice": "1d6",
                    "attack_ability": "DEX",
                    "finesse": True,
                    "light": True,
                    "proficient": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_lyra", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Light Extra Test",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_lyra",
                        name="Lyra",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=14,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=12,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_lyra",
                None,
                "Lyra follows up with a Light-weapon extra attack",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5, 13, 4]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_lyra",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "shortsword"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_lyra",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "dagger"},
                    ),
                ],
            )

        assert len(result.applied_actions) == 2
        second_outcome = result.applied_actions[1].outcome
        assert second_outcome is not None
        assert second_outcome["light_extra_attack"] is True
        assert second_outcome["attack_timing"] == "bonus_action"
        assert second_outcome["damage_amount"] == 4
        assert second_outcome["turn_attack_state_before"]["attack_timing_counts"]["action"] == 1
        assert second_outcome["turn_attack_state_before"]["remaining_bonus_action_attacks"] == 1
        assert second_outcome["turn_attack_state_after"]["attack_timing_counts"]["bonus_action"] == 1
        assert second_outcome["turn_attack_state_after"]["bonus_action_attack_used"] is True
        assert second_outcome["turn_attack_state_after"]["remaining_bonus_action_attacks"] == 0

        updated = connection.execute("SELECT current_hp FROM combatants WHERE id = ?", (goblin.id,)).fetchone()
        assert updated is not None
        assert updated["current_hp"] == 20 - 9 - 4


def test_attack_roll_rejects_second_bonus_action_attack_in_same_turn(tmp_path: Path):
    database_path = tmp_path / "attack-roll-bonus-action-limit.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_brom",
                name="Brom",
                class_name="Fighter",
                level=5,
                current_hp=18,
                max_hp=18,
                armor_class=17,
                proficiency_bonus=3,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Longsword",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_brom", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Bonus Action Limit",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_brom",
                        name="Brom",
                        initiative=15,
                        current_hp=18,
                        max_hp=18,
                        armor_class=17,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Ogre",
                        initiative=12,
                        current_hp=30,
                        max_hp=30,
                        armor_class=12,
                    ),
                ],
            ),
        )
        assert combat is not None
        ogre = next(item for item in combat.combatants if item.name == "Ogre")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_brom",
                None,
                "Brom tries two Bonus Action attacks",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(ogre.id)],
                        parameters={"weapon": "longsword", "attack_timing": "bonus_action"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(ogre.id)],
                        parameters={"weapon": "longsword", "attack_timing": "bonus_action"},
                    ),
                ],
            )

        assert len(result.applied_actions) == 1
        assert len(result.rejected_actions) == 1
        assert result.rejected_actions[0].reason == "This combatant has already made a Bonus Action attack this turn."
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["attack_timing"] == "bonus_action"
        assert outcome["turn_attack_state_after"]["bonus_action_attack_used"] is True
        assert outcome["turn_attack_state_after"]["remaining_bonus_action_attacks"] == 0


def test_attack_roll_enforces_fighter_extra_attack_action_slots(tmp_path: Path):
    database_path = tmp_path / "attack-roll-extra-attack.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_brom",
                name="Brom",
                class_name="Fighter",
                level=5,
                current_hp=18,
                max_hp=18,
                armor_class=17,
                proficiency_bonus=3,
                ability_modifiers={"STR": 4},
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_brom", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Training Yard",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_brom",
                        name="Brom",
                        initiative=15,
                        current_hp=18,
                        max_hp=18,
                        armor_class=17,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Target Dummy",
                        initiative=10,
                        current_hp=40,
                        max_hp=40,
                        armor_class=12,
                    ),
                ],
            ),
        )
        dummy = next(item for item in combat.combatants if item.name == "Target Dummy")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_brom",
                None,
                "Brom uses Extra Attack",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 5, 11, 4]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(dummy.id)],
                        parameters={"weapon": "longsword"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(dummy.id)],
                        parameters={"weapon": "longsword"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_brom",
                        target_ids=[str(dummy.id)],
                        parameters={"weapon": "longsword"},
                    ),
                ],
            )

        assert len(result.applied_actions) == 2
        assert len(result.rejected_actions) == 1
        assert "only 2 attack(s) as part of the Attack action" in result.rejected_actions[0].reason
        assert "Attack action slots used: 2/2." in result.rejected_actions[0].reason
        second_outcome = result.applied_actions[1].outcome
        assert second_outcome is not None
        assert second_outcome["turn_attack_state_after"]["action_attack_limit"] == 2
        assert second_outcome["turn_attack_state_after"]["action_primary_attacks_used"] == 2
        assert second_outcome["turn_attack_state_after"]["remaining_action_primary_attacks"] == 0


@pytest.mark.parametrize(
    ("class_name", "level", "expected_limit"),
    [
        ("Fighter", 11, 3),
        ("Fighter", 20, 4),
        ("Barbarian", 5, 2),
        ("Monk", 5, 2),
        ("Paladin", 5, 2),
        ("Ranger", 5, 2),
    ],
)
def test_attack_roll_enforces_supported_extra_attack_progressions(
    tmp_path: Path,
    class_name: str,
    level: int,
    expected_limit: int,
):
    database_path = tmp_path / f"attack-roll-extra-attack-{class_name.lower()}-{level}.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_extra",
                name="Extra",
                class_name=class_name,
                level=level,
                current_hp=30,
                max_hp=30,
                armor_class=17,
                proficiency_bonus=4,
                ability_modifiers={"STR": 4, "DEX": 4},
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_extra", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Extra Attack Progression",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_extra",
                        name="Extra",
                        initiative=15,
                        current_hp=30,
                        max_hp=30,
                        armor_class=17,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Training Dummy",
                        initiative=10,
                        current_hp=200,
                        max_hp=200,
                        armor_class=12,
                    ),
                ],
            ),
        )
        assert combat is not None
        dummy = next(item for item in combat.combatants if item.name == "Training Dummy")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_extra",
                None,
                "Extra uses every Attack-action slot",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        actions = [
            ProposedAction(
                type="attack_roll",
                actor_id="pc_extra",
                target_ids=[str(dummy.id)],
                parameters={"weapon": "longsword"},
            )
            for _ in range(expected_limit + 1)
        ]
        dice_results = []
        for index in range(expected_limit):
            dice_results.extend([12 + index, 4])

        with patch("backend.app.services.action_service._roll_die", side_effect=dice_results):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=actions,
            )

        assert len(result.applied_actions) == expected_limit
        assert len(result.rejected_actions) == 1
        assert f"only {expected_limit} attack(s) as part of the Attack action" in result.rejected_actions[0].reason
        assert f"Attack action slots used: {expected_limit}/{expected_limit}." in result.rejected_actions[0].reason
        final_outcome = result.applied_actions[-1].outcome
        assert final_outcome is not None
        assert final_outcome["turn_attack_state_after"]["action_attack_limit"] == expected_limit
        assert final_outcome["turn_attack_state_after"]["action_primary_attacks_used"] == expected_limit
        assert final_outcome["turn_attack_state_after"]["remaining_action_primary_attacks"] == 0


def test_attack_roll_allows_nick_extra_attack_without_consuming_extra_attack_slot(tmp_path: Path):
    database_path = tmp_path / "attack-roll-nick-extra-attack.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_sera",
                name="Sera",
                class_name="Fighter",
                level=5,
                current_hp=18,
                max_hp=18,
                armor_class=16,
                proficiency_bonus=3,
                ability_modifiers={"STR": 4, "DEX": 4},
                equipped_weapon={
                    "name": "Dagger",
                    "damage_dice": "1d4",
                    "attack_ability": "DEX",
                    "finesse": True,
                    "light": True,
                    "thrown": True,
                    "normal_range": 20,
                    "long_range": 60,
                    "proficient": True,
                    "mastery_property": "nick",
                    "mastery_enabled": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_sera", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Sparring Ring",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_sera",
                        name="Sera",
                        initiative=15,
                        current_hp=18,
                        max_hp=18,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Training Ogre",
                        initiative=10,
                        current_hp=40,
                        max_hp=40,
                        armor_class=12,
                    ),
                ],
            ),
        )
        ogre = next(item for item in combat.combatants if item.name == "Training Ogre")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_sera",
                None,
                "Sera chains Nick into Extra Attack",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 4, 11, 3, 10, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_sera",
                        target_ids=[str(ogre.id)],
                        parameters={"weapon": "scimitar"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_sera",
                        target_ids=[str(ogre.id)],
                        parameters={"weapon": "dagger"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_sera",
                        target_ids=[str(ogre.id)],
                        parameters={"weapon": "longsword"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_sera",
                        target_ids=[str(ogre.id)],
                        parameters={"weapon": "longsword"},
                    ),
                ],
            )

        assert len(result.applied_actions) == 3
        assert len(result.rejected_actions) == 1
        assert "only 2 attack(s) as part of the Attack action" in result.rejected_actions[0].reason
        second_outcome = result.applied_actions[1].outcome
        third_outcome = result.applied_actions[2].outcome
        assert second_outcome is not None
        assert third_outcome is not None
        assert second_outcome["light_extra_attack"] is True
        assert second_outcome["attack_timing"] == "action"
        assert second_outcome["turn_attack_state_after"]["action_primary_attacks_used"] == 1
        assert third_outcome["turn_attack_state_before"]["action_primary_attacks_used"] == 1
        assert third_outcome["turn_attack_state_after"]["action_primary_attacks_used"] == 2
        assert third_outcome["turn_attack_state_after"]["remaining_action_primary_attacks"] == 0


def test_attack_roll_rejects_when_actor_is_incapacitated(tmp_path: Path):
    database_path = tmp_path / "attack-roll-incapacitated.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                level=5,
                current_hp=12,
                max_hp=12,
                armor_class=16,
                conditions=["stunned"],
                equipped_weapon={"name": "Longsword", "damage_dice": "1d8", "attack_ability": "STR"},
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        conditions=["stunned"],
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=7,
                        max_hp=7,
                        armor_class=15,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        result = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=turn_id,
            actions=[
                ProposedAction(
                    type="attack_roll",
                    actor_id="pc_aric",
                    target_ids=[str(goblin.id)],
                    parameters={"weapon": "longsword"},
                )
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 1
        assert "incapacitated" in result.rejected_actions[0].reason


def test_attack_roll_applies_advantage_against_prone_target_in_melee(tmp_path: Path):
    database_path = tmp_path / "attack-roll-prone-melee.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        name="Champion",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                        conditions=["prone"],
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "Champion",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[3, 14, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="Champion",
                        target_ids=[str(goblin.id)],
                        parameters={"attack_bonus": 3, "damage_formula": "1d6+1"},
                    )
                ],
            )

        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["advantage_state"] == "advantage"
        assert outcome["roll_values"] == [3, 14]
        assert "target_prone_vs_melee" in outcome["condition_sources"]
        assert outcome["attack_roll"] == 14
        assert outcome["hit"] is True


def test_attack_roll_applies_disadvantage_against_prone_target_with_ranged_attack(tmp_path: Path):
    database_path = tmp_path / "attack-roll-prone-ranged.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                level=5,
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 2},
                weapon_loadout=WeaponLoadout(
                    ranged=WeaponProfile(
                        name="Longbow",
                        damage_dice="1d8",
                        attack_ability="DEX",
                        proficient=True,
                        ranged=True,
                    ),
                    active_slot="ranged",
                ),
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                        conditions=["prone"],
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[17, 6]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longbow"},
                    )
                ],
            )

        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["advantage_state"] == "disadvantage"
        assert outcome["roll_values"] == [17, 6]
        assert "target_prone_vs_ranged" in outcome["condition_sources"]
        assert outcome["attack_roll"] == 6
        assert outcome["hit"] is False


def test_attack_roll_rejects_when_target_not_in_active_combat(tmp_path: Path):
    database_path = tmp_path / "attack-roll-reject.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                None,
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        result = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=turn_id,
            actions=[
                ProposedAction(
                    type="attack_roll",
                    actor_id="pc_aric",
                    target_ids=["goblin_1"],
                    parameters={"weapon": "longsword"},
                )
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 1
        assert "Target combatant was not found" in result.rejected_actions[0].reason


def test_attack_roll_resolves_fuzzy_target_name_like_goblin_1(tmp_path: Path):
    database_path = tmp_path / "attack-roll-fuzzy.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                level=5,
                current_hp=12,
                max_hp=12,
                armor_class=16,
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=7,
                        max_hp=7,
                        armor_class=15,
                    ),
                ],
            ),
        )
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[15, 8]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=["goblin_1"],
                        parameters={"weapon": "longsword"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []


def test_attack_roll_accepts_symbolic_damage_formula_and_npc_prefix_target(tmp_path: Path):
    database_path = tmp_path / "attack-roll-symbolic.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=7,
                        max_hp=7,
                        armor_class=15,
                    ),
                ],
            ),
        )
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[15, 8]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=["npc_goblin_1"],
                        parameters={"weapon": "longsword", "damage_formula": "1d8 + STR"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["damage_amount"] == 8


def test_attack_roll_uses_canonical_character_weapon_profile(tmp_path: Path):
    database_path = tmp_path / "attack-roll-canonical.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4, "DEX": 1},
                equipped_weapon={
                    "name": "Longsword",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longsword"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["attack_bonus"] == 6
        assert result.applied_actions[0].outcome["attack_total"] == 18
        assert result.applied_actions[0].outcome["damage_amount"] == 9


def test_attack_roll_uses_versatile_damage_when_two_handed(tmp_path: Path):
    database_path = tmp_path / "attack-roll-versatile-two-handed.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Longsword",
                    "damage_dice": "1d8",
                    "versatile_damage_dice": "1d10",
                    "attack_ability": "STR",
                    "proficient": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 8]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longsword", "use_two_hands": True},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["damage_amount"] == 12


def test_attack_roll_keeps_one_handed_damage_without_versatile_flag(tmp_path: Path):
    database_path = tmp_path / "attack-roll-versatile-one-handed.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Longsword",
                    "damage_dice": "1d8",
                    "versatile_damage_dice": "1d10",
                    "attack_ability": "STR",
                    "proficient": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 6]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longsword"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["damage_amount"] == 10


def test_attack_roll_consumes_ammunition_from_inventory(tmp_path: Path):
    database_path = tmp_path / "attack-roll-ammunition-consume.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                level=11,
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 4},
                equipped_weapon={
                    "name": "Shortbow",
                    "damage_dice": "1d6",
                    "attack_ability": "DEX",
                    "proficient": True,
                    "ranged": True,
                    "ammunition_item": "Arrow",
                    "track_ammunition": True,
                },
            ),
        )
        add_item(connection, campaign_id=campaign.id, character_id="pc_aric", item_name="Arrow", quantity=2)
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=12,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 4]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "shortbow"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["ammunition_item"] == "Arrow"
        assert result.applied_actions[0].outcome["ammunition_expended"] is True
        row = connection.execute(
            "SELECT quantity FROM inventory_items WHERE character_id = ? AND name = ?",
            ("pc_aric", "Arrow"),
        ).fetchone()
        assert row is not None
        assert int(row["quantity"]) == 1


def test_attack_roll_rejects_ammunition_weapon_without_required_ammo(tmp_path: Path):
    database_path = tmp_path / "attack-roll-ammunition-missing.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                level=11,
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 4},
                equipped_weapon={
                    "name": "Longbow",
                    "damage_dice": "1d8",
                    "attack_ability": "DEX",
                    "proficient": True,
                    "ranged": True,
                    "ammunition_item": "Arrow",
                    "track_ammunition": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=12,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        result = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=turn_id,
            actions=[
                ProposedAction(
                    type="attack_roll",
                    actor_id="pc_aric",
                    target_ids=[str(goblin.id)],
                    parameters={"weapon": "longbow"},
                )
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 1
        assert "requires at least 1 Arrow" in result.rejected_actions[0].reason


def test_attack_roll_rejects_second_loading_attack_in_same_action_timing(tmp_path: Path):
    database_path = tmp_path / "attack-roll-loading-same-action.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                level=5,
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 4},
                equipped_weapon={
                    "name": "Light Crossbow",
                    "damage_dice": "1d8",
                    "attack_ability": "DEX",
                    "proficient": True,
                    "ranged": True,
                    "loading": True,
                    "track_ammunition": True,
                },
            ),
        )
        add_item(connection, campaign_id=campaign.id, character_id="pc_aric", item_name="Bolt", quantity=1)
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=12,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "light crossbow"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "light crossbow"},
                    ),
                ],
            )

        assert len(result.applied_actions) == 1
        assert len(result.rejected_actions) == 1
        assert "Loading weapons can be fired only once per action" in result.rejected_actions[0].reason


def test_attack_roll_allows_loading_weapon_across_different_attack_timings(tmp_path: Path):
    database_path = tmp_path / "attack-roll-loading-different-timings.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 4},
                equipped_weapon={
                    "name": "Hand Crossbow",
                    "damage_dice": "1d6",
                    "attack_ability": "DEX",
                    "proficient": True,
                    "ranged": True,
                    "loading": True,
                    "track_ammunition": True,
                },
            ),
        )
        add_item(connection, campaign_id=campaign.id, character_id="pc_aric", item_name="Bolt", quantity=2)
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=12,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 4, 11, 3]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "hand crossbow", "attack_timing": "action"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "hand crossbow", "attack_timing": "bonus_action"},
                    ),
                ],
            )

        assert len(result.applied_actions) == 2
        assert result.rejected_actions == []
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[1].outcome is not None
        assert result.applied_actions[0].outcome["attack_timing"] == "action"
        assert result.applied_actions[1].outcome["attack_timing"] == "bonus_action"


def test_recover_ammunition_restores_half_expended_ammo_after_encounter(tmp_path: Path):
    database_path = tmp_path / "recover-ammunition.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                level=11,
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 4},
                equipped_weapon={
                    "name": "Shortbow",
                    "damage_dice": "1d6",
                    "attack_ability": "DEX",
                    "proficient": True,
                    "ranged": True,
                    "ammunition_item": "Arrow",
                    "track_ammunition": True,
                },
            ),
        )
        add_item(connection, campaign_id=campaign.id, character_id="pc_aric", item_name="Arrow", quantity=4)
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=30,
                        max_hp=30,
                        armor_class=10,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        attack_turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 4, 11, 3, 10, 2]):
            attack_result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=attack_turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "shortbow"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "shortbow"},
                    ),
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "shortbow"},
                    ),
                ],
            )

        assert len(attack_result.applied_actions) == 3
        ended = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="end",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=combat.encounter_id,
            ),
        )
        assert ended is not None
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                2,
                "assistant",
                "pc_aric",
                None,
                "Recover ammunition",
                "[]",
                None,
                utc_now(),
            ),
        )
        recover_turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        recover_result = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=recover_turn_id,
            actions=[
                ProposedAction(
                    type="recover_ammunition",
                    actor_id="pc_aric",
                    target_ids=["pc_aric"],
                    parameters={"encounter_id": combat.encounter_id},
                )
            ],
        )

        assert len(recover_result.applied_actions) == 1
        assert recover_result.rejected_actions == []
        assert recover_result.applied_actions[0].outcome is not None
        assert recover_result.applied_actions[0].outcome["recovered_items"] == [{"item_name": "Arrow", "quantity": 1}]
        inventory_row = connection.execute(
            "SELECT quantity FROM inventory_items WHERE character_id = ? AND name = ?",
            ("pc_aric", "Arrow"),
        ).fetchone()
        assert inventory_row is not None
        assert int(inventory_row["quantity"]) == 2


def test_attack_roll_auto_uses_thrown_mode_beyond_melee_reach(tmp_path: Path):
    database_path = tmp_path / "attack-roll-thrown-auto.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4, "DEX": 1},
                equipped_weapon={
                    "name": "Spear",
                    "damage_dice": "1d6",
                    "attack_ability": "STR",
                    "proficient": True,
                    "thrown": True,
                    "normal_range": 20,
                    "long_range": 60,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        position_x=0,
                        position_y=0,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                        position_x=10,
                        position_y=0,
                        conditions=["prone"],
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[17, 6]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "spear"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["advantage_state"] == "disadvantage"
        assert "target_prone_vs_ranged" in outcome["condition_sources"]
        assert outcome["target_distance_feet"] == 10


def test_attack_roll_keeps_thrown_weapon_as_melee_within_reach(tmp_path: Path):
    database_path = tmp_path / "attack-roll-thrown-melee.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4, "DEX": 1},
                equipped_weapon={
                    "name": "Spear",
                    "damage_dice": "1d6",
                    "attack_ability": "STR",
                    "proficient": True,
                    "thrown": True,
                    "normal_range": 20,
                    "long_range": 60,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        position_x=0,
                        position_y=0,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                        position_x=5,
                        position_y=0,
                        conditions=["prone"],
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[14, 5, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "spear"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["advantage_state"] == "advantage"
        assert "target_prone_vs_melee" in outcome["condition_sources"]
        assert outcome["attack_bonus"] == 6
        assert outcome["damage_amount"] == 9


def test_attack_roll_rejects_melee_attack_beyond_default_reach(tmp_path: Path):
    database_path = tmp_path / "attack-roll-default-reach.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Longsword",
                    "damage_dice": "1d8",
                    "attack_ability": "STR",
                    "proficient": True,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        position_x=0,
                        position_y=0,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                        position_x=10,
                        position_y=0,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        result = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=turn_id,
            actions=[
                ProposedAction(
                    type="attack_roll",
                    actor_id="pc_aric",
                    target_ids=[str(goblin.id)],
                    parameters={"weapon": "longsword"},
                )
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 1
        assert "beyond the attack's reach of 5 feet" in result.rejected_actions[0].reason


def test_attack_roll_allows_reach_weapon_at_ten_feet(tmp_path: Path):
    database_path = tmp_path / "attack-roll-reach-weapon.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4},
                equipped_weapon={
                    "name": "Glaive",
                    "damage_dice": "1d10",
                    "attack_ability": "STR",
                    "proficient": True,
                    "reach": 10,
                },
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        position_x=0,
                        position_y=0,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                        position_x=10,
                        position_y=0,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "glaive"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["attack_total"] == 18
        assert result.applied_actions[0].outcome["damage_amount"] == 9


def test_attack_roll_prefers_active_weapon_loadout_slot(tmp_path: Path):
    database_path = tmp_path / "attack-roll-loadout.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"STR": 4, "DEX": 2},
                weapon_loadout=WeaponLoadout(
                    primary=WeaponProfile(
                        name="Longsword",
                        damage_dice="1d8",
                        attack_ability="STR",
                        proficient=True,
                    ),
                    ranged=WeaponProfile(
                        name="Longbow",
                        damage_dice="1d8",
                        attack_ability="DEX",
                        proficient=True,
                        ranged=True,
                    ),
                    active_slot="ranged",
                ),
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                    ),
                ],
            ),
        )
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[12, 5]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longbow"},
                    )
                ],
            )

        assert len(result.applied_actions) == 1
        assert result.rejected_actions == []
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["attack_bonus"] == 4
        assert result.applied_actions[0].outcome["attack_total"] == 16
        assert result.applied_actions[0].outcome["damage_amount"] == 7


def test_attack_roll_applies_disadvantage_beyond_normal_range_using_positions(tmp_path: Path):
    database_path = tmp_path / "attack-roll-long-range.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 2},
                weapon_loadout=WeaponLoadout(
                    ranged=WeaponProfile(
                        name="Longbow",
                        damage_dice="1d8",
                        attack_ability="DEX",
                        proficient=True,
                        ranged=True,
                    ),
                    active_slot="ranged",
                ),
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        position_x=0,
                        position_y=0,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                        position_x=200,
                        position_y=0,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[17, 6]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longbow"},
                    )
                ],
            )

        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["advantage_state"] == "disadvantage"
        assert outcome["roll_values"] == [17, 6]
        assert "target_beyond_normal_range" in outcome["condition_sources"]
        assert outcome["target_distance_feet"] == 200
        assert outcome["distance_source"] == "position"
        assert outcome["attack_roll"] == 6


def test_attack_roll_rejects_target_beyond_long_range(tmp_path: Path):
    database_path = tmp_path / "attack-roll-beyond-long-range.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 2},
                weapon_loadout=WeaponLoadout(
                    ranged=WeaponProfile(
                        name="Longbow",
                        damage_dice="1d8",
                        attack_ability="DEX",
                        proficient=True,
                        ranged=True,
                    ),
                    active_slot="ranged",
                ),
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        position_x=0,
                        position_y=0,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                        position_x=700,
                        position_y=0,
                    ),
                ],
            ),
        )
        assert combat is not None
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        result = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=turn_id,
            actions=[
                ProposedAction(
                    type="attack_roll",
                    actor_id="pc_aric",
                    target_ids=[str(goblin.id)],
                    parameters={"weapon": "longbow"},
                )
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 1
        assert "beyond the weapon's long range of 600 feet" in result.rejected_actions[0].reason


def test_attack_roll_uses_positions_updated_after_combat_start_for_range(tmp_path: Path):
    database_path = tmp_path / "attack-roll-updated-position-range.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_aric",
                name="Aric",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
                proficiency_bonus=2,
                ability_modifiers={"DEX": 2},
                weapon_loadout=WeaponLoadout(
                    ranged=WeaponProfile(
                        name="Longbow",
                        damage_dice="1d8",
                        attack_ability="DEX",
                        proficient=True,
                        ranged=True,
                    ),
                    active_slot="ranged",
                ),
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        combat = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_aric",
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=20,
                        max_hp=20,
                        armor_class=15,
                    ),
                ],
            ),
        )
        assert combat is not None
        aric = next(item for item in combat.combatants if item.name == "Aric")
        goblin = next(item for item in combat.combatants if item.name == "Goblin")
        assert aric.position_x is None
        assert goblin.position_x is None

        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="update_position",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=combat.encounter_id,
                combatant_ref="Aric",
                position_x=0,
                position_y=0,
            ),
        )
        moved = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="update_position",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=combat.encounter_id,
                combatant_ref="Goblin",
                position_x=200,
                position_y=0,
            ),
        )
        assert moved is not None
        moved_goblin = next(item for item in moved.combatants if item.name == "Goblin")
        assert moved_goblin.position_x == 200
        assert moved_goblin.position_y == 0

        connection.execute(
            """
            INSERT INTO turns (
              campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
              user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign.id,
                session.id,
                1,
                "assistant",
                "pc_aric",
                None,
                "Attack turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        with patch("backend.app.services.action_service._roll_die", side_effect=[17, 6]):
            result = apply_actions(
                connection,
                campaign_id=campaign.id,
                session_id=session.id,
                turn_id=turn_id,
                actions=[
                    ProposedAction(
                        type="attack_roll",
                        actor_id="pc_aric",
                        target_ids=[str(goblin.id)],
                        parameters={"weapon": "longbow"},
                    )
                ],
            )

        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["advantage_state"] == "disadvantage"
        assert "target_beyond_normal_range" in outcome["condition_sources"]
        assert outcome["target_distance_feet"] == 200
        assert outcome["distance_source"] == "position"
