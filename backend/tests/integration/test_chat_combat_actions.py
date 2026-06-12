from __future__ import annotations

import asyncio
from pathlib import Path

from backend.app.db.session import get_connection, initialize_database
from backend.app.schemas.campaigns import CampaignCreateRequest
from backend.app.schemas.characters import CharacterCreateRequest, PartyAssignRequest
from backend.app.schemas.chat import ChatRequest
from backend.app.schemas.sessions import SessionCreateRequest
from backend.app.services.campaign_service import create_campaign
from backend.app.services.character_service import create_character
from backend.app.services.chat_orchestrator import run_chat_turn
from backend.app.services.party_service import assign_party_member
from backend.app.services.session_service import create_session


class FakeCombatLLMClient:
    async def complete_json(self, prompt: str) -> dict:
        assert "PLAYER MESSAGE" in prompt
        return {
            "narration": "A goblin leaps from the brush and combat begins.",
            "proposed_actions": [
                {
                    "type": "start_combat",
                    "actor_id": "pc_aric",
                    "parameters": {
                        "name": "Goblin Ambush",
                        "combatants": [
                            {
                                "source_character_id": "pc_aric",
                                "name": "Aric",
                                "initiative": 15,
                                "current_hp": 12,
                                "max_hp": 12,
                                "armor_class": 16,
                                "is_player": True,
                                "party_order": 1,
                            },
                            {
                                "name": "Goblin",
                                "initiative": 13,
                                "current_hp": 7,
                                "max_hp": 7,
                                "armor_class": 15,
                                "is_player": False,
                            },
                        ],
                    },
                    "reason": "Ambush encounter begins",
                    "confidence": 0.9,
                }
            ],
        }


def test_run_chat_turn_sets_active_combat_summary(tmp_path: Path):
    database_path = tmp_path / "chat-combat.sqlite3"
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

        result = asyncio.run(
            run_chat_turn(
                connection,
                ChatRequest(
                    campaign_id=campaign.id,
                    session_id=session.id,
                    speaker_entity_id="pc_aric",
                    message="I draw my sword as the goblin jumps out.",
                ),
                llm_client=FakeCombatLLMClient(),
                include_debug=True,
            )
        )

        assert result.applied_actions
        assert result.state_summary.active_combat_encounter_id is not None
