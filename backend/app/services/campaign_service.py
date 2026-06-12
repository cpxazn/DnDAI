from __future__ import annotations

from sqlite3 import Connection

from backend.app.schemas.campaigns import CampaignCreateRequest, CampaignSummary
from backend.app.services.utils import row_to_dict, utc_now


def list_campaigns(connection: Connection) -> list[CampaignSummary]:
    rows = connection.execute(
        """
        SELECT id, name, status, current_location_text
        FROM campaigns
        ORDER BY id
        """
    ).fetchall()
    return [CampaignSummary.model_validate(row_to_dict(row)) for row in rows]


def create_campaign(connection: Connection, payload: CampaignCreateRequest) -> CampaignSummary:
    timestamp = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO campaigns (name, status, created_at, updated_at)
        VALUES (?, 'active', ?, ?)
        """,
        (payload.name.strip(), timestamp, timestamp),
    )
    row = connection.execute(
        """
        SELECT id, name, status, current_location_text
        FROM campaigns
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return CampaignSummary.model_validate(row_to_dict(row))
