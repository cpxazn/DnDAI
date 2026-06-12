from __future__ import annotations

from sqlite3 import Connection

from backend.app.schemas.sessions import SessionCreateRequest, SessionSummary
from backend.app.services.utils import row_to_dict, utc_now


def list_sessions(connection: Connection, campaign_id: int) -> list[SessionSummary]:
    rows = connection.execute(
        """
        SELECT id, campaign_id, name, status, started_at, ended_at
        FROM sessions
        WHERE campaign_id = ?
        ORDER BY id
        """,
        (campaign_id,),
    ).fetchall()
    return [SessionSummary.model_validate(row_to_dict(row)) for row in rows]


def create_session(connection: Connection, payload: SessionCreateRequest) -> SessionSummary:
    timestamp = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO sessions (campaign_id, name, status, started_at)
        VALUES (?, ?, 'active', ?)
        """,
        (payload.campaign_id, payload.name.strip(), timestamp),
    )
    row = connection.execute(
        """
        SELECT id, campaign_id, name, status, started_at, ended_at
        FROM sessions
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return SessionSummary.model_validate(row_to_dict(row))
