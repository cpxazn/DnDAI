from pathlib import Path

from backend.app.db.session import get_connection, initialize_database
from backend.app.schemas.campaigns import CampaignCreateRequest
from backend.app.schemas.characters import CharacterCreateRequest, PartyAssignRequest
from backend.app.schemas.combat import CombatOperationRequest, CombatantInput
from backend.app.schemas.sessions import SessionCreateRequest
from backend.app.services.campaign_service import create_campaign
from backend.app.services.character_service import create_character
from backend.app.services.combat_service import apply_combat_operation, get_active_combat
from backend.app.services.party_service import assign_party_member
from backend.app.services.session_service import create_session


def test_combat_start_advance_end_cycle(tmp_path: Path):
    database_path = tmp_path / "combat.sqlite3"
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
        assert started.name == "Goblin Ambush"
        assert len(started.combatants) == 2
        assert started.active_combatant_id == started.combatants[0].id

        advanced = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=started.encounter_id,
            ),
        )
        assert advanced is not None
        assert advanced.turn_index == 1
        assert advanced.active_combatant_id == advanced.combatants[1].id

        current = get_active_combat(connection, campaign.id, session.id)
        assert current is not None

        ended = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="end",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=started.encounter_id,
            ),
        )
        assert ended is not None
        assert ended.encounter_id == started.encounter_id
        assert get_active_combat(connection, campaign.id, session.id) is None


def test_advance_turn_skips_unconscious_combatants(tmp_path: Path):
    database_path = tmp_path / "combat-skip.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))

        started = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Goblin Ambush",
                combatants=[
                    CombatantInput(
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        is_player=True,
                        party_order=1,
                    ),
                    CombatantInput(
                        name="Goblin Scout",
                        initiative=12,
                        current_hp=0,
                        max_hp=7,
                        armor_class=15,
                    ),
                    CombatantInput(
                        name="Goblin Boss",
                        initiative=10,
                        current_hp=9,
                        max_hp=9,
                        armor_class=15,
                    ),
                ],
            ),
        )
        assert started is not None

        advanced = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="advance_turn",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=started.encounter_id,
            ),
        )
        assert advanced is not None
        assert advanced.status == "active"
        assert advanced.turn_index == 2
        assert advanced.active_combatant_id == advanced.combatants[2].id


def test_update_position_moves_combatant_in_active_encounter(tmp_path: Path):
    database_path = tmp_path / "combat-position.sqlite3"
    initialize_database(database_path)

    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Ashes"))
        session = create_session(connection, SessionCreateRequest(campaign_id=campaign.id, name="Session 1"))

        started = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Moving Fight",
                combatants=[
                    CombatantInput(
                        name="Aric",
                        initiative=15,
                        current_hp=12,
                        max_hp=12,
                        armor_class=16,
                        position_x=0,
                        position_y=0,
                        is_player=True,
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
        goblin = next(item for item in started.combatants if item.name == "Goblin")
        assert goblin.position_x is None
        assert goblin.position_y is None

        updated = apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="update_position",
                campaign_id=campaign.id,
                session_id=session.id,
                encounter_id=started.encounter_id,
                combatant_ref="Goblin",
                position_x=30,
                position_y=-5,
            ),
        )

        assert updated is not None
        moved = next(item for item in updated.combatants if item.name == "Goblin")
        assert moved.position_x == 30
        assert moved.position_y == -5


def test_start_combat_uses_effective_party_armor_class_from_shield_loadout(tmp_path: Path):
    database_path = tmp_path / "combat-shield.sqlite3"
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
                weapon_loadout={
                    "primary": {"name": "Longsword", "damage_dice": "1d8", "attack_ability": "STR"},
                    "active_slot": "primary",
                    "shield_bonus": 2,
                },
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
                name="Roadside Ambush",
                combatants=[],
            ),
        )
        assert started is not None
        assert len(started.combatants) == 1
        assert started.combatants[0].armor_class == 18
