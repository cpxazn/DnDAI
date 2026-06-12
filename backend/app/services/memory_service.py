from __future__ import annotations

from sqlite3 import Connection

from backend.app.schemas.memory import MemoryDebugResponse, MemoryFact, MemoryTurn, SceneSummary
from backend.app.services.utils import json_loads, row_to_dict


def get_memory_debug(
    connection: Connection,
    campaign_id: int,
    session_id: int,
    include_recent_turns: bool,
    include_scene_summaries: bool,
    include_facts: bool,
) -> MemoryDebugResponse:
    response = MemoryDebugResponse()

    if include_recent_turns:
        rows = connection.execute(
            """
            SELECT id, turn_index, speaker_role, speaker_entity_id, user_text, assistant_text, created_at
            FROM turns
            WHERE campaign_id = ? AND session_id = ?
            ORDER BY turn_index DESC
            LIMIT 10
            """,
            (campaign_id, session_id),
        ).fetchall()
        response.recent_turns = [MemoryTurn.model_validate(row_to_dict(row)) for row in reversed(rows)]

    if include_scene_summaries:
        rows = connection.execute(
            """
            SELECT id, summary_kind, summary_text, created_at
            FROM scene_summaries
            WHERE campaign_id = ? AND (session_id = ? OR session_id IS NULL)
            ORDER BY id DESC
            LIMIT 10
            """,
            (campaign_id, session_id),
        ).fetchall()
        response.scene_summaries = [SceneSummary.model_validate(row_to_dict(row)) for row in rows]

    if include_facts:
        rows = connection.execute(
            """
            SELECT id, fact_type, fact_text, tags_json, created_at
            FROM memory_facts
            WHERE campaign_id = ? AND (session_id = ? OR session_id IS NULL)
            ORDER BY id DESC
            LIMIT 20
            """,
            (campaign_id, session_id),
        ).fetchall()
        response.facts = [
            MemoryFact.model_validate(
                {
                    **row_to_dict(row),
                    "tags": json_loads(row["tags_json"], []),
                }
            )
            for row in rows
        ]

    return response
