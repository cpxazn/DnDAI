from __future__ import annotations

import random
import re

from backend.app.schemas.dice import DiceRollResponse, DieResult


FORMULA_RE = re.compile(r"^\s*(\d*)d(\d+)([+-]\d+)?\s*$", re.IGNORECASE)


class DiceFormulaError(ValueError):
    """Raised when a dice formula is invalid."""


def roll(formula: str, advantage_state: str = "normal", roll_type: str | None = None) -> DiceRollResponse:
    match = FORMULA_RE.match(formula)
    if not match:
        raise DiceFormulaError("Formula must look like NdM+K, for example 1d20+5.")

    count = int(match.group(1) or "1")
    sides = int(match.group(2))
    modifier = int(match.group(3) or "0")

    if count <= 0 or sides <= 0:
        raise DiceFormulaError("Dice count and sides must be positive integers.")

    if advantage_state != "normal":
        if count != 1 or sides != 20:
            raise DiceFormulaError("Advantage/disadvantage is only supported for 1d20 rolls in v1.")
        first = random.randint(1, sides)
        second = random.randint(1, sides)
        kept = max(first, second) if advantage_state == "advantage" else min(first, second)
        dropped = min(first, second) if advantage_state == "advantage" else max(first, second)
        total = kept + modifier
        return DiceRollResponse(
            formula=formula,
            roll_type=roll_type,
            advantage_state=advantage_state,
            dice=[DieResult(sides=sides, result=first), DieResult(sides=sides, result=second)],
            modifier_total=modifier,
            total=total,
            kept_total=kept,
            dropped_total=dropped,
        )

    dice = [DieResult(sides=sides, result=random.randint(1, sides)) for _ in range(count)]
    total = sum(die.result for die in dice) + modifier
    return DiceRollResponse(
        formula=formula,
        roll_type=roll_type,
        advantage_state=advantage_state,
        dice=dice,
        modifier_total=modifier,
        total=total,
    )
