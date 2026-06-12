from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.api.deps import ensure_exists, get_db
from backend.app.schemas.common import Envelope
from backend.app.schemas.combat import CombatOperationRequest, CombatStateResponse
from backend.app.services.combat_service import apply_combat_operation, get_active_combat


router = APIRouter(prefix="/combat", tags=["combat"])


@router.get("", response_model=Envelope[CombatStateResponse])
def get_combat(
    campaign_id: int = Query(...),
    session_id: int = Query(...),
    connection: Connection = Depends(get_db),
) -> Envelope[CombatStateResponse]:
    ensure_exists(connection, "campaigns", campaign_id)
    ensure_exists(connection, "sessions", session_id)
    state = get_active_combat(connection, campaign_id, session_id)
    if state is None:
        return Envelope(data=None)
    return Envelope(data=state)


@router.post("", response_model=Envelope[CombatStateResponse])
def operate_combat(
    payload: CombatOperationRequest,
    connection: Connection = Depends(get_db),
) -> Envelope[CombatStateResponse]:
    ensure_exists(connection, "campaigns", payload.campaign_id)
    ensure_exists(connection, "sessions", payload.session_id)
    try:
        state = apply_combat_operation(connection, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Envelope(data=state)
