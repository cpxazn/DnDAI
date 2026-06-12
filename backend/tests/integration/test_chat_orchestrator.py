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
from backend.app.services.rules_service import import_rules_jsonl
from backend.app.services.session_service import create_session


class FakeLLMClient:
    async def complete_json(self, prompt: str) -> dict:
        assert "PLAYER MESSAGE" in prompt
        return {
            "narration": "Aric slashes the goblin and shakes off the poison.",
            "proposed_actions": [
                {
                    "type": "apply_damage",
                    "actor_id": "pc_aric",
                    "target_ids": ["pc_borin"],
                    "parameters": {"amount": 3},
                    "reason": "Test damage",
                    "confidence": 0.8,
                },
                {
                    "type": "remove_condition",
                    "actor_id": "pc_borin",
                    "target_ids": ["pc_borin"],
                    "parameters": {"condition": "poisoned"},
                    "reason": "Test condition cleanup",
                    "confidence": 0.7,
                },
            ],
        }


def test_run_chat_turn_applies_supported_actions(tmp_path: Path):
    database_path = tmp_path / "test.sqlite3"
    initialize_database(database_path)

    jsonl_path = Path("data/rules/processed/srd_5_2_1_chunks.jsonl").resolve()
    with get_connection(database_path) as connection:
        campaign = create_campaign(connection, CampaignCreateRequest(name="Test Campaign"))
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
                level=1,
                current_hp=12,
                max_hp=12,
            ),
        )
        create_character(
            connection,
            CharacterCreateRequest(
                campaign_id=campaign.id,
                id="pc_borin",
                name="Borin",
                class_name="Cleric",
                level=1,
                current_hp=10,
                max_hp=10,
                conditions=["poisoned"],
            ),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_aric", party_order=1),
        )
        assign_party_member(
            connection,
            PartyAssignRequest(campaign_id=campaign.id, character_id="pc_borin", party_order=2),
        )
        import_rules_jsonl(
            connection,
            jsonl_path=str(jsonl_path),
            source_name="dnd-5e-srd-markdown",
            source_version="SRD 5.2.1",
            ruleset="SRD 5.2.1",
            chunker_version="test",
        )

        result = asyncio.run(
            run_chat_turn(
                connection,
                ChatRequest(
                    campaign_id=campaign.id,
                    session_id=session.id,
                    speaker_entity_id="pc_aric",
                    message="I attack.",
                ),
                llm_client=FakeLLMClient(),
                include_debug=True,
            )
        )

        assert result.narration
        assert len(result.applied_actions) == 2
        assert result.rejected_actions == []
        assert "pc_borin" in result.state_summary.changed_entities

        borin = connection.execute(
            "SELECT current_hp, conditions_json FROM characters WHERE id = 'pc_borin'"
        ).fetchone()
        assert borin["current_hp"] == 7
        assert borin["conditions_json"] == "[]"

        events = connection.execute("SELECT COUNT(*) AS count FROM game_events").fetchone()
        assert events["count"] == 2
