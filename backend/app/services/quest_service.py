from __future__ import annotations

from sqlite3 import Connection

from backend.app.services.utils import utc_now


def create_quest(
    connection: Connection,
    *,
    campaign_id: int,
    title: str,
    summary: str | None = None,
    notes: str | None = None,
) -> int | None:
    normalized_title = title.strip()
    if not normalized_title:
        return None
    cursor = connection.execute(
        """
        INSERT INTO quests (campaign_id, title, status, summary, notes, created_at, updated_at)
        VALUES (?, ?, 'active', ?, ?, ?, ?)
        """,
        (campaign_id, normalized_title, summary, notes, utc_now(), utc_now()),
    )
    return int(cursor.lastrowid)


def update_quest_status(
    connection: Connection,
    *,
    campaign_id: int,
    quest_id: int,
    status: str,
    notes: str | None = None,
    summary: str | None = None,
) -> bool:
    row = connection.execute(
        """
        SELECT id, notes, summary
        FROM quests
        WHERE id = ? AND campaign_id = ?
        """,
        (quest_id, campaign_id),
    ).fetchone()
    if row is None:
        return False

    normalized_status = status.strip().lower()
    completed_at = utc_now() if normalized_status == "completed" else None
    connection.execute(
        """
        UPDATE quests
        SET status = ?, notes = ?, summary = ?, updated_at = ?, completed_at = ?
        WHERE id = ?
        """,
        (
            normalized_status,
            notes if notes is not None else row["notes"],
            summary if summary is not None else row["summary"],
            utc_now(),
            completed_at,
            quest_id,
        ),
    )
    return True
