from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.schemas.common import Envelope
from backend.app.schemas.dice import DiceRollRequest, DiceRollResponse
from backend.app.services.dice_service import DiceFormulaError, roll


router = APIRouter(prefix="/dice", tags=["dice"])


@router.post("/roll", response_model=Envelope[DiceRollResponse])
def roll_dice(payload: DiceRollRequest) -> Envelope[DiceRollResponse]:
    try:
        result = roll(
            formula=payload.formula,
            advantage_state=payload.advantage_state,
            roll_type=payload.roll_type,
        )
    except DiceFormulaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Envelope(data=result)
