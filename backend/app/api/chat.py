from __future__ import annotations

from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.deps import get_app_settings, get_db
from backend.app.core.config import Settings
from backend.app.schemas.chat import ChatRequest, ChatResponseData
from backend.app.schemas.common import Envelope
from backend.app.services.chat_orchestrator import run_chat_turn
from backend.app.services.llm_client import LLMClient, LLMUnavailableError


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=Envelope[ChatResponseData])
async def chat_turn(
    payload: ChatRequest,
    connection: Connection = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> Envelope[ChatResponseData]:
    if payload.options.stream:
        raise HTTPException(status_code=501, detail="Streaming chat is not implemented in this first slice yet.")

    client = LLMClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    try:
        result = await run_chat_turn(
            connection=connection,
            request=payload,
            llm_client=client,
            include_debug=payload.options.include_debug or settings.enable_chat_debug,
        )
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Envelope(data=result)
