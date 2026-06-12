from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends, Query

from backend.app.api.deps import ensure_exists, get_db
from fastapi import HTTPException

from backend.app.schemas.characters import CharacterCreateRequest, CharacterSummary, CharacterUpdateRequest
from backend.app.schemas.common import Envelope
from backend.app.services import character_service


router = APIRouter(prefix="/characters", tags=["characters"])


@router.get("", response_model=Envelope[list[CharacterSummary]])
def list_characters(
    campaign_id: int = Query(...),
    connection: Connection = Depends(get_db),
) -> Envelope[list[CharacterSummary]]:
    ensure_exists(connection, "campaigns", campaign_id)
    return Envelope(data=character_service.list_characters(connection, campaign_id))


@router.post("", response_model=Envelope[CharacterSummary])
def create_character(
    payload: CharacterCreateRequest,
    connection: Connection = Depends(get_db),
) -> Envelope[CharacterSummary]:
    ensure_exists(connection, "campaigns", payload.campaign_id)
    return Envelope(data=character_service.create_character(connection, payload))


@router.patch("/{character_id}", response_model=Envelope[CharacterSummary])
def update_character(
    character_id: str,
    payload: CharacterUpdateRequest,
    campaign_id: int = Query(...),
    connection: Connection = Depends(get_db),
) -> Envelope[CharacterSummary]:
    ensure_exists(connection, "campaigns", campaign_id)
    updated = character_service.update_character(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        payload=payload,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Character not found.")
    return Envelope(data=updated)
