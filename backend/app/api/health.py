from __future__ import annotations

from fastapi import APIRouter

from backend.app.schemas.common import Envelope


router = APIRouter(tags=["health"])


@router.get("/health", response_model=Envelope[dict])
def health() -> Envelope[dict]:
    return Envelope(data={"status": "ok"}, error=None)
