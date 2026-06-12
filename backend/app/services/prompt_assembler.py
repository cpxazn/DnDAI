from __future__ import annotations

from pathlib import Path

from backend.app.schemas.characters import PartyMemberSummary
from backend.app.services.rules_service import RetrievedRule


PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def build_chat_prompt(
    *,
    campaign_name: str,
    session_name: str,
    party: list[PartyMemberSummary],
    recent_turns: list[dict],
    rules: list[RetrievedRule],
    player_message: str,
) -> str:
    system_prompt = _read_prompt("system_prompt.md")
    contract = _read_prompt("chat_response_contract.md")

    party_lines = []
    for member in party:
        character = member.character
        party_lines.append(
            f"- {character.name} ({character.id}): HP {character.current_hp}/{character.max_hp}, "
            f"level {character.level} {character.class_name or 'adventurer'}, "
            f"conditions={', '.join(character.conditions) or 'none'}"
        )

    turn_lines = []
    for turn in recent_turns[-6:]:
        label = "Player" if turn["speaker_role"] == "player" else "DM"
        text = turn["user_text"] or turn["assistant_text"] or ""
        turn_lines.append(f"{label}: {text}")

    rule_lines = []
    for rule in rules:
        heading = " > ".join(rule.heading_path)
        rule_lines.append(f"- {heading}: {rule.text}")

    sections = [
        "SYSTEM INSTRUCTIONS",
        system_prompt,
        "",
        "RESPONSE CONTRACT",
        contract,
        "",
        "CANONICAL STATE",
        f"Campaign: {campaign_name}",
        f"Session: {session_name}",
        "Party:",
        *(party_lines or ["- No active party members"]),
        "",
        "RECENT TRANSCRIPT",
        *(turn_lines or ["No prior turns in this session."]),
        "",
        "RETRIEVED RULES",
        *(rule_lines or ["No rules retrieved."]),
        "",
        "PLAYER MESSAGE",
        player_message,
    ]
    return "\n".join(sections)
