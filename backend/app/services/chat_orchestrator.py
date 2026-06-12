from __future__ import annotations

from sqlite3 import Connection

from backend.app.services.action_service import apply_actions
from backend.app.services.combat_service import get_active_encounter_id
from backend.app.schemas.chat import ChatRequest, ChatResponseData, Citation, ProposedAction, StateSummary
from backend.app.services.llm_client import LLMClient
from backend.app.services.memory_service import get_memory_debug
from backend.app.services.party_service import get_party
from backend.app.services.prompt_assembler import build_chat_prompt
from backend.app.services.rules_service import search_rules
from backend.app.services.utils import json_dumps, row_to_dict, utc_now


def _get_campaign_and_session(connection: Connection, campaign_id: int, session_id: int) -> tuple[dict, dict]:
    campaign = connection.execute(
        "SELECT id, name FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()
    session = connection.execute(
        "SELECT id, name FROM sessions WHERE id = ? AND campaign_id = ?",
        (session_id, campaign_id),
    ).fetchone()
    if campaign is None or session is None:
        raise ValueError("Campaign or session not found.")
    return row_to_dict(campaign), row_to_dict(session)


def _next_turn_index(connection: Connection, session_id: int) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(turn_index), 0) AS max_turn_index FROM turns WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["max_turn_index"]) + 1


async def run_chat_turn(
    connection: Connection,
    request: ChatRequest,
    llm_client: LLMClient,
    include_debug: bool,
) -> ChatResponseData:
    campaign, session = _get_campaign_and_session(connection, request.campaign_id, request.session_id)
    party = get_party(connection, request.campaign_id)
    memory = get_memory_debug(
        connection=connection,
        campaign_id=request.campaign_id,
        session_id=request.session_id,
        include_recent_turns=True,
        include_scene_summaries=False,
        include_facts=False,
    )
    rules = search_rules(connection, request.message, limit=4)
    prompt = build_chat_prompt(
        campaign_name=campaign["name"],
        session_name=session["name"],
        party=party,
        recent_turns=[turn.model_dump() for turn in memory.recent_turns],
        rules=rules,
        player_message=request.message,
    )
    llm_payload = await llm_client.complete_json(prompt)
    narration = str(llm_payload.get("narration", "")).strip()
    actions = [
        ProposedAction.model_validate(action)
        for action in llm_payload.get("proposed_actions", [])
        if isinstance(action, dict)
    ]

    player_turn_index = _next_turn_index(connection, request.session_id)
    timestamp = utc_now()
    connection.execute(
        """
        INSERT INTO turns (
          campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
          user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request.campaign_id,
            request.session_id,
            player_turn_index,
            "player",
            request.speaker_entity_id,
            request.message,
            None,
            "[]",
            None,
            timestamp,
        ),
    )
    assistant_turn_index = player_turn_index + 1
    assistant_cursor = connection.execute(
        """
        INSERT INTO turns (
          campaign_id, session_id, turn_index, speaker_role, speaker_entity_id,
          user_text, assistant_text, proposed_actions_json, retrieval_debug_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request.campaign_id,
            request.session_id,
            assistant_turn_index,
            "assistant",
            None,
            None,
            narration,
            json_dumps([action.model_dump() for action in actions]),
            json_dumps({"rules": [rule.document_id for rule in rules]}) if include_debug else None,
            timestamp,
        ),
    )
    applied = apply_actions(
        connection,
        campaign_id=request.campaign_id,
        session_id=request.session_id,
        turn_id=int(assistant_cursor.lastrowid),
        actions=actions if request.options.apply_deterministic_actions else [],
    )

    return ChatResponseData(
        turn_id=int(assistant_cursor.lastrowid),
        session_id=request.session_id,
        campaign_id=request.campaign_id,
        narration=narration,
        proposed_actions=actions,
        applied_actions=applied.applied_actions,
        rejected_actions=applied.rejected_actions,
        citations=[
            Citation(
                source_type="rules",
                document_id=rule.document_id,
                heading_path=rule.heading_path,
            )
            for rule in rules
        ],
        state_summary=StateSummary(
            active_combat_encounter_id=get_active_encounter_id(connection, request.campaign_id, request.session_id),
            changed_entities=applied.changed_entities,
        ),
        debug={"retrieved_rule_ids": [rule.document_id for rule in rules]} if include_debug else None,
    )
