from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends, Query

from backend.app.api.deps import ensure_exists, get_db
from backend.app.schemas.common import Envelope
from backend.app.schemas.sessions import SessionCreateRequest, SessionSummary
from backend.app.services import session_service


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=Envelope[list[SessionSummary]])
def list_sessions(
    campaign_id: int = Query(...),
    connection: Connection = Depends(get_db),
) -> Envelope[list[SessionSummary]]:
    ensure_exists(connection, "campaigns", campaign_id)
    return Envelope(data=session_service.list_sessions(connection, campaign_id))


@router.post("", response_model=Envelope[SessionSummary])
def create_session(
    payload: SessionCreateRequest,
    connection: Connection = Depends(get_db),
) -> Envelope[SessionSummary]:
    ensure_exists(connection, "campaigns", payload.campaign_id)
    return Envelope(data=session_service.create_session(connection, payload))
