from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends, Query

from backend.app.api.deps import ensure_exists, get_db
from backend.app.schemas.common import Envelope
from backend.app.schemas.memory import MemoryDebugResponse
from backend.app.services.memory_service import get_memory_debug


router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("", response_model=Envelope[MemoryDebugResponse])
def memory_debug(
    campaign_id: int = Query(...),
    session_id: int = Query(...),
    include_recent_turns: bool = Query(default=True),
    include_scene_summaries: bool = Query(default=True),
    include_facts: bool = Query(default=True),
    connection: Connection = Depends(get_db),
) -> Envelope[MemoryDebugResponse]:
    ensure_exists(connection, "campaigns", campaign_id)
    ensure_exists(connection, "sessions", session_id)
    data = get_memory_debug(
        connection=connection,
        campaign_id=campaign_id,
        session_id=session_id,
        include_recent_turns=include_recent_turns,
        include_scene_summaries=include_scene_summaries,
        include_facts=include_facts,
    )
    return Envelope(data=data)
