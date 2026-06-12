from pathlib import Path

from backend.app.db.session import get_connection, initialize_database
from backend.app.schemas.campaigns import CampaignCreateRequest
from backend.app.schemas.characters import CharacterCreateRequest
from backend.app.schemas.chat import ProposedAction
from backend.app.schemas.combat import CombatOperationRequest, CombatantInput
from backend.app.services.action_service import apply_actions
from backend.app.services.campaign_service import create_campaign
from backend.app.services.character_service import create_character
from backend.app.services.combat_service import apply_combat_operation, get_active_combat
from backend.app.services.session_service import create_session
from backend.app.schemas.sessions import SessionCreateRequest
from backend.app.services.utils import utc_now


def test_apply_actions_supports_inventory_quests_spell_slots_and_location(tmp_path: Path):
    database_path = tmp_path / "actions.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_lyra",
                name="Lyra",
                class_name="Wizard",
                level=3,
                current_hp=14,
                max_hp=14,
                spell_slots={"1": 4, "2": 2},
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
                "pc_lyra",
                None,
                "Test turn",
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
                    type="spend_spell_slot",
                    actor_id="pc_lyra",
                    target_ids=["pc_lyra"],
                    parameters={"level": 1},
                ),
                ProposedAction(
                    type="add_inventory_item",
                    actor_id="pc_lyra",
                    target_ids=["pc_lyra"],
                    parameters={"item_name": "Health Potion", "quantity": 2},
                ),
                ProposedAction(
                    type="create_quest",
                    actor_id="pc_lyra",
                    parameters={"title": "Find the Sunstone", "summary": "Recover the relic."},
                ),
                ProposedAction(
                    type="set_location",
                    actor_id="pc_lyra",
                    parameters={"location": "Blackstone Keep"},
                ),
            ],
        )

        assert len(result.applied_actions) == 4
        assert "pc_lyra" in result.changed_entities

        character = connection.execute(
            """
            SELECT spell_slots_json, inventory_highlights_json
            FROM characters
            WHERE id = 'pc_lyra'
            """
        ).fetchone()
        assert character["spell_slots_json"] == '{"1":3,"2":2}'
        assert character["inventory_highlights_json"] == '["Health Potion x2"]'

        quest = connection.execute(
            "SELECT title, status FROM quests WHERE campaign_id = ?",
            (campaign.id,),
        ).fetchone()
        assert quest["title"] == "Find the Sunstone"
        assert quest["status"] == "active"

        campaign_row = connection.execute(
            "SELECT current_location_text FROM campaigns WHERE id = ?",
            (campaign.id,),
        ).fetchone()
        assert campaign_row["current_location_text"] == "Blackstone Keep"


def test_apply_actions_supports_combat_turn_advance_and_weapon_slot_switch(tmp_path: Path):
    database_path = tmp_path / "combat-utils.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
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
                ability_modifiers={"STR": 4, "DEX": 2},
                weapon_loadout={
                    "primary": {"name": "Longsword", "damage_dice": "1d8", "attack_ability": "STR"},
                    "ranged": {"name": "Longbow", "damage_dice": "1d8", "attack_ability": "DEX", "ranged": True},
                    "active_slot": "primary",
                    "shield_bonus": 2,
                },
            ),
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
                        armor_class=18,
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
        assert started.combatants[0].armor_class == 18
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
                "Combat utility turn",
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
                    type="set_active_weapon_slot",
                    actor_id="pc_aric",
                    parameters={"active_slot": "ranged"},
                ),
                ProposedAction(type="advance_turn", actor_id="pc_aric", parameters={}),
            ],
        )

        assert len(result.applied_actions) == 2
        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        assert state.turn_index == 1
        assert state.combatants[0].armor_class == 16
        character = connection.execute(
            "SELECT equipped_weapon_json, weapon_loadout_json FROM characters WHERE id = 'pc_aric'"
        ).fetchone()
        assert '"Longbow"' in character["equipped_weapon_json"]
        assert '"active_slot":"ranged"' in character["weapon_loadout_json"]


def test_apply_actions_supports_temporary_combat_effects_and_expiry(tmp_path: Path):
    database_path = tmp_path / "combat-effects.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_cleric",
                name="Cleric",
                class_name="Cleric",
                current_hp=10,
                max_hp=10,
                armor_class=16,
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_fighter",
                name="Fighter",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=15,
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Bridge Fight",
                combatants=[
                    CombatantInput(
                        name="Cleric",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
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
                "cleric",
                None,
                "Combat effect turn",
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
                    type="add_combat_effect",
                    actor_id="cleric",
                    target_ids=["cleric"],
                    parameters={
                        "effect_name": "Shield of Faith",
                        "effect_type": "ac_bonus",
                        "modifier": 2,
                        "duration_rounds": 1,
                    },
                ),
            ],
        )

        assert len(result.applied_actions) == 1
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["armor_class"] == 18

        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        assert state.combatants[0].armor_class == 18
        assert state.combatants[0].effects[0]["name"] == "Shield of Faith"

        advanced = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=state.encounter_id,
            ),
        )
        assert advanced is not None
        post_tick = next(item for item in advanced.combatants if item.name == "Cleric")
        assert post_tick.armor_class == 16
        assert post_tick.effects == []


def test_apply_actions_casts_shield_of_faith_as_named_ac_concentration_effect(tmp_path: Path):
    database_path = tmp_path / "shield-of-faith.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_cleric",
                name="Cleric",
                class_name="Cleric",
                current_hp=10,
                max_hp=10,
                armor_class=16,
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_fighter",
                name="Fighter",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=15,
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Bridge Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_cleric",
                        name="Cleric",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
                        armor_class=16,
                        position_x=0,
                        position_y=0,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        source_character_id="pc_fighter",
                        name="Fighter",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=15,
                        position_x=30,
                        position_y=40,
                        is_player=True,
                        party_order=2,
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
                "pc_cleric",
                None,
                "Shield of Faith turn",
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
                    type="cast_shield_of_faith",
                    actor_id="pc_cleric",
                    target_ids=["pc_fighter"],
                    parameters={},
                ),
            ],
        )

        assert result.rejected_actions == []
        assert len(result.applied_actions) == 1
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["effect_name"] == "Shield of Faith"
        assert outcome["effect_type"] == "ac_bonus"
        assert outcome["armor_class"] == 17
        assert outcome["requires_concentration"] is True
        assert outcome["range_feet"] == 60
        assert outcome["target_distance_feet"] == 50
        assert outcome["distance_source"] == "position"

        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        fighter = next(item for item in state.combatants if item.name == "Fighter")
        assert fighter.armor_class == 17
        assert fighter.effects == [
            {
                "name": "Shield of Faith",
                "type": "ac_bonus",
                "modifier": 2,
                "duration_rounds": None,
                "source_combatant_id": state.combatants[0].id,
                "requires_concentration": True,
            }
        ]


def test_apply_actions_casts_barkskin_as_named_ac_floor_effect(tmp_path: Path):
    database_path = tmp_path / "barkskin.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_druid",
                name="Druid",
                class_name="Druid",
                current_hp=10,
                max_hp=10,
                armor_class=14,
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_scout",
                name="Scout",
                class_name="Ranger",
                current_hp=12,
                max_hp=12,
                armor_class=14,
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_guard",
                name="Guard",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=18,
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Grove Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_druid",
                        name="Druid",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
                        armor_class=14,
                        position_x=0,
                        position_y=0,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        source_character_id="pc_scout",
                        name="Scout",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=14,
                        position_x=3,
                        position_y=4,
                        is_player=True,
                        party_order=2,
                    ),
                    CombatantInput(
                        source_character_id="pc_guard",
                        name="Guard",
                        initiative=10,
                        current_hp=12,
                        max_hp=12,
                        armor_class=18,
                        position_x=0,
                        position_y=5,
                        is_player=True,
                        party_order=3,
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
                "pc_druid",
                None,
                "Barkskin turn",
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
                    type="cast_barkskin",
                    actor_id="pc_druid",
                    target_ids=["pc_scout"],
                    parameters={},
                ),
                ProposedAction(
                    type="cast_barkskin",
                    actor_id="pc_druid",
                    target_ids=["pc_guard"],
                    parameters={},
                ),
            ],
        )

        assert result.rejected_actions == []
        assert len(result.applied_actions) == 2
        scout_outcome = result.applied_actions[0].outcome
        guard_outcome = result.applied_actions[1].outcome
        assert scout_outcome is not None
        assert scout_outcome["effect_name"] == "Barkskin"
        assert scout_outcome["effect_type"] == "ac_floor"
        assert scout_outcome["armor_class"] == 17
        assert scout_outcome["requires_concentration"] is False
        assert scout_outcome["touch_range_feet"] == 5
        assert scout_outcome["target_distance_feet"] == 5
        assert scout_outcome["distance_source"] == "position"
        assert guard_outcome is not None
        assert guard_outcome["armor_class"] == 18

        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        scout = next(item for item in state.combatants if item.name == "Scout")
        guard = next(item for item in state.combatants if item.name == "Guard")
        assert scout.armor_class == 17
        assert scout.effects[0]["name"] == "Barkskin"
        assert scout.effects[0]["type"] == "ac_floor"
        assert scout.effects[0]["modifier"] == 17
        assert scout.effects[0]["requires_concentration"] is False
        assert guard.armor_class == 18
        assert guard.effects[0]["name"] == "Barkskin"
        assert guard.effects[0]["type"] == "ac_floor"


def test_apply_actions_casts_shield_as_named_self_ac_bonus_effect(tmp_path: Path):
    database_path = tmp_path / "shield.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_wizard",
                name="Wizard",
                class_name="Wizard",
                current_hp=10,
                max_hp=10,
                armor_class=12,
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Tower Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_wizard",
                        name="Wizard",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
                        armor_class=12,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Skeleton",
                        initiative=12,
                        current_hp=7,
                        max_hp=7,
                        armor_class=13,
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
                "pc_wizard",
                None,
                "Shield turn",
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
                    type="cast_shield",
                    actor_id="pc_wizard",
                    parameters={},
                ),
            ],
        )

        assert result.rejected_actions == []
        assert len(result.applied_actions) == 1
        outcome = result.applied_actions[0].outcome
        assert outcome is not None
        assert outcome["effect_name"] == "Shield"
        assert outcome["effect_type"] == "ac_bonus"
        assert outcome["armor_class"] == 17
        assert outcome["duration_rounds"] == 1
        assert outcome["requires_concentration"] is False
        assert outcome["range"] == "Self"
        assert outcome["magic_missile_protection"] is True

        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        wizard = next(item for item in state.combatants if item.name == "Wizard")
        assert wizard.armor_class == 17
        assert wizard.effects == [
            {
                "name": "Shield",
                "type": "ac_bonus",
                "modifier": 5,
                "duration_rounds": 1,
                "source_combatant_id": wizard.id,
                "requires_concentration": False,
            }
        ]

        advanced = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=state.encounter_id,
            ),
        )
        assert advanced is not None
        wizard_after_tick = next(item for item in advanced.combatants if item.name == "Wizard")
        assert wizard_after_tick.armor_class == 12
        assert wizard_after_tick.effects == []


def test_apply_actions_rejects_shield_target_other_than_self(tmp_path: Path):
    database_path = tmp_path / "shield-target.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_wizard",
                name="Wizard",
                class_name="Wizard",
                current_hp=10,
                max_hp=10,
                armor_class=12,
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_fighter",
                name="Fighter",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=16,
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Tower Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_wizard",
                        name="Wizard",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
                        armor_class=12,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        source_character_id="pc_fighter",
                        name="Fighter",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=2,
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
                "pc_wizard",
                None,
                "Shield target turn",
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
                    type="cast_shield",
                    actor_id="pc_wizard",
                    target_ids=["pc_fighter"],
                    parameters={},
                ),
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 1
        assert result.rejected_actions[0].reason == "Shield has range Self and can target only the caster."

        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        wizard = next(item for item in state.combatants if item.name == "Wizard")
        fighter = next(item for item in state.combatants if item.name == "Fighter")
        assert wizard.armor_class == 12
        assert wizard.effects == []
        assert fighter.armor_class == 16
        assert fighter.effects == []


def test_apply_actions_rejects_barkskin_beyond_touch_range(tmp_path: Path):
    database_path = tmp_path / "barkskin-range.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_druid",
                name="Druid",
                class_name="Druid",
                current_hp=10,
                max_hp=10,
                armor_class=14,
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_scout",
                name="Scout",
                class_name="Ranger",
                current_hp=12,
                max_hp=12,
                armor_class=14,
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Grove Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_druid",
                        name="Druid",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
                        armor_class=14,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        source_character_id="pc_scout",
                        name="Scout",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=14,
                        is_player=True,
                        party_order=2,
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
                "pc_druid",
                None,
                "Barkskin range turn",
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
                    type="cast_barkskin",
                    actor_id="pc_druid",
                    target_ids=["pc_scout"],
                    parameters={"target_distance_feet": 10},
                ),
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 1
        assert result.rejected_actions[0].reason == "Barkskin requires a target within touch range."

        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        scout = next(item for item in state.combatants if item.name == "Scout")
        assert scout.armor_class == 14
        assert scout.effects == []


def test_apply_actions_rejects_shield_of_faith_beyond_known_range(tmp_path: Path):
    database_path = tmp_path / "shield-of-faith-range.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_cleric",
                name="Cleric",
                class_name="Cleric",
                current_hp=10,
                max_hp=10,
                armor_class=16,
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_fighter",
                name="Fighter",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=15,
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Bridge Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_cleric",
                        name="Cleric",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        source_character_id="pc_fighter",
                        name="Fighter",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=15,
                        is_player=True,
                        party_order=2,
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
                "pc_cleric",
                None,
                "Shield of Faith range turn",
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
                    type="cast_shield_of_faith",
                    actor_id="pc_cleric",
                    target_ids=["pc_fighter"],
                    parameters={"target_distance_feet": 65},
                ),
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 1
        assert result.rejected_actions[0].reason == "Shield of Faith requires a target within 60 feet."

        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        fighter = next(item for item in state.combatants if item.name == "Fighter")
        assert fighter.armor_class == 15
        assert fighter.effects == []


def test_apply_actions_supports_temporary_speed_effects_and_expiry(tmp_path: Path):
    database_path = tmp_path / "combat-speed-effects.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Bridge Fight",
                combatants=[
                    CombatantInput(
                        name="Scout",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
                        armor_class=14,
                        speed=30,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=12,
                        current_hp=7,
                        max_hp=7,
                        armor_class=15,
                        speed=30,
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
                "scout",
                None,
                "Combat speed effect turn",
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
                    type="add_combat_effect",
                    actor_id="scout",
                    target_ids=["scout"],
                    parameters={
                        "effect_name": "Haste",
                        "effect_type": "speed_bonus",
                        "modifier": 10,
                        "duration_rounds": 1,
                    },
                ),
            ],
        )

        assert len(result.applied_actions) == 1
        assert result.applied_actions[0].outcome is not None
        assert result.applied_actions[0].outcome["speed"] == 40

        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        assert state.combatants[0].speed == 40
        assert state.combatants[0].effects[0]["name"] == "Haste"

        advanced = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=state.encounter_id,
            ),
        )
        assert advanced is not None
        post_tick = next(item for item in advanced.combatants if item.name == "Scout")
        assert post_tick.speed == 30
        assert post_tick.effects == []


def test_apply_actions_breaks_and_replaces_concentration_effects(tmp_path: Path):
    database_path = tmp_path / "combat-concentration.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(
            connection,
            SessionCreateRequest(campaign_id=campaign.id, name="Session 1"),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_cleric",
                name="Cleric",
                class_name="Cleric",
                current_hp=10,
                max_hp=10,
                armor_class=16,
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_fighter",
                name="Fighter",
                class_name="Fighter",
                current_hp=12,
                max_hp=12,
                armor_class=15,
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Bridge Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_cleric",
                        name="Cleric",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        source_character_id="pc_fighter",
                        name="Fighter",
                        initiative=12,
                        current_hp=12,
                        max_hp=12,
                        armor_class=15,
                        is_player=True,
                        party_order=2,
                    ),
                    CombatantInput(
                        name="Goblin",
                        initiative=10,
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
                "pc_cleric",
                None,
                "Combat concentration turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        initial = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=turn_id,
            actions=[
                ProposedAction(
                    type="add_combat_effect",
                    actor_id="pc_cleric",
                    target_ids=["pc_fighter"],
                    parameters={
                        "effect_name": "Bless",
                        "effect_type": "attack_bonus",
                        "modifier": 1,
                        "requires_concentration": True,
                    },
                ),
            ],
        )

        assert len(initial.applied_actions) == 1
        state = get_active_combat(connection, campaign.id, session.id)
        assert state is not None
        for _ in range(3):
            state = apply_combat_operation(
                connection,
                CombatOperationRequest(
                    operation="advance_turn",
                    campaign_id=campaign.id,
                    session_id=session.id,
                    encounter_id=state.encounter_id,
                ),
            )
            assert state is not None

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
                "pc_cleric",
                None,
                "Second concentration turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        second_turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        replacement = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=second_turn_id,
            actions=[
                ProposedAction(
                    type="add_combat_effect",
                    actor_id="pc_cleric",
                    target_ids=["pc_fighter"],
                    parameters={
                        "effect_name": "Shield of Faith",
                        "effect_type": "ac_bonus",
                        "modifier": 2,
                        "requires_concentration": True,
                    },
                ),
            ],
        )

        assert len(replacement.applied_actions) == 1
        outcome = replacement.applied_actions[0].outcome
        assert outcome is not None
        assert len(outcome["ended_concentration_effects"]) == 1
        ended_effect_names = [effect["name"] for effect in outcome["ended_concentration_effects"][0]["effects"]]
        assert ended_effect_names == ["Bless"]

        for _ in range(3):
            state = apply_combat_operation(
                connection,
                CombatOperationRequest(
                    operation="advance_turn",
                    campaign_id=campaign.id,
                    session_id=session.id,
                    encounter_id=state.encounter_id,
                ),
            )
            assert state is not None

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
                3,
                "assistant",
                "pc_cleric",
                None,
                "Condition turn",
                "[]",
                None,
                utc_now(),
            ),
        )
        condition_turn_id = int(connection.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
        condition_result = apply_actions(
            connection,
            campaign_id=campaign.id,
            session_id=session.id,
            turn_id=condition_turn_id,
            actions=[
                ProposedAction(
                    type="add_condition",
                    actor_id="pc_cleric",
                    target_ids=["pc_cleric"],
                    parameters={"condition": "stunned"},
                ),
            ],
        )

        assert len(condition_result.applied_actions) == 1
        current_state = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=state.encounter_id,
            ),
        )
        assert current_state is not None
        cleric = next(item for item in current_state.combatants if item.name == "Cleric")
        fighter = next(item for item in current_state.combatants if item.name == "Fighter")
        assert "stunned" in cleric.conditions
        assert fighter.effects == []
