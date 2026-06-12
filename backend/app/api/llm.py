from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.deps import get_app_settings
from backend.app.core.config import Settings
from backend.app.schemas.common import Envelope
from backend.app.services.llm_client import LLMClient, LLMUnavailableError


router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/health", response_model=Envelope[dict])
async def llm_health(settings: Settings = Depends(get_app_settings)) -> Envelope[dict]:
    client = LLMClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    try:
        models = await client.list_models()
    except LLMUnavailableError as exc:
        return Envelope(
            data={
                "status": "unavailable",
                "base_url": settings.llm_base_url,
                "configured_model": settings.llm_model,
            },
            error={
                "code": "LLM_UNAVAILABLE",
                "message": str(exc),
                "details": None,
            },
        )

    return Envelope(
        data={
            "status": "ok",
            "base_url": settings.llm_base_url,
            "configured_model": settings.llm_model,
            "available_models": models,
            "configured_model_available": settings.llm_model in models if models else False,
        }
    )
