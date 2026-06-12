from backend.app.services.dice_service import DiceFormulaError, roll


def test_roll_basic_formula():
    result = roll("1d6+2")
    assert result.formula == "1d6+2"
    assert len(result.dice) == 1
    assert 3 <= result.total <= 8


def test_roll_advantage_requires_d20():
    try:
        roll("2d6", advantage_state="advantage")
    except DiceFormulaError:
        return
    raise AssertionError("Expected DiceFormulaError for non-d20 advantage roll.")
