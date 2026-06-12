from pathlib import Path

from backend.app.db.session import get_connection, initialize_database
from backend.app.schemas.campaigns import CampaignCreateRequest
from backend.app.schemas.characters import CharacterCreateRequest
from backend.app.schemas.chat import ProposedAction
from backend.app.schemas.combat import CombatOperationRequest, CombatantInput
from backend.app.schemas.sessions import SessionCreateRequest
from backend.app.services.action_service import apply_actions
from backend.app.services.campaign_service import create_campaign
from backend.app.services.character_service import create_character
from backend.app.services.combat_service import apply_combat_operation
from backend.app.services.session_service import create_session
from backend.app.services.utils import utc_now


def test_apply_actions_returns_rejected_actions_for_invalid_proposals(tmp_path: Path):
    database_path = tmp_path / "validation.sqlite3"
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
                class_name="Wizard",
                current_hp=10,
                max_hp=10,
                spell_slots={"1": 1},
            ),
        )
        apply_combat_operation(
            connection,
            CombatOperationRequest(
                operation="start",
                campaign_id=campaign.id,
                session_id=session.id,
                name="Validation Fight",
                combatants=[
                    CombatantInput(
                        source_character_id="pc_lyra",
                        name="Lyra",
                        initiative=15,
                        current_hp=10,
                        max_hp=10,
                        armor_class=12,
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
                ProposedAction(type="unknown_action", actor_id="pc_lyra", parameters={}),
                ProposedAction(type="apply_damage", actor_id="pc_lyra", target_ids=["pc_missing"], parameters={"amount": 3}),
                ProposedAction(type="spend_spell_slot", actor_id="pc_lyra", target_ids=["pc_lyra"], parameters={"level": 2}),
                ProposedAction(type="set_location", actor_id="pc_lyra", parameters={}),
                ProposedAction(
                    type="add_combat_effect",
                    actor_id="pc_lyra",
                    target_ids=["pc_lyra"],
                    parameters={"effect_name": "Haste", "effect_type": "morale_bonus", "modifier": 1},
                ),
            ],
        )

        assert result.applied_actions == []
        assert len(result.rejected_actions) == 5
        reasons = [item.reason for item in result.rejected_actions]
        assert any("Unsupported action type" in reason for reason in reasons)
        assert any("No valid target characters" in reason for reason in reasons)
        assert any("Spell slot level 2 is not tracked" in reason for reason in reasons)
        assert any("set_location requires" in reason for reason in reasons)
        assert any("Supported effect types are ac_bonus, attack_bonus, damage_bonus, speed_bonus, and speed_penalty" in reason for reason in reasons)
