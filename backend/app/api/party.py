from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends, Query

from backend.app.api.deps import ensure_exists, get_db
from backend.app.schemas.characters import PartyAssignRequest, PartyMemberSummary
from backend.app.schemas.common import Envelope
from backend.app.services import party_service


router = APIRouter(prefix="/party", tags=["party"])


@router.get("", response_model=Envelope[list[PartyMemberSummary]])
def get_party(
    campaign_id: int = Query(...),
    connection: Connection = Depends(get_db),
) -> Envelope[list[PartyMemberSummary]]:
    ensure_exists(connection, "campaigns", campaign_id)
    return Envelope(data=party_service.get_party(connection, campaign_id))


@router.post("", response_model=Envelope[PartyMemberSummary])
def assign_party_member(
    payload: PartyAssignRequest,
    connection: Connection = Depends(get_db),
) -> Envelope[PartyMemberSummary]:
    ensure_exists(connection, "campaigns", payload.campaign_id)
    return Envelope(data=party_service.assign_party_member(connection, payload))
