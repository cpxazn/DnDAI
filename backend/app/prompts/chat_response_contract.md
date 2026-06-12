Return JSON only with this shape:

{
  "narration": "string",
  "proposed_actions": [
    {
      "type": "string",
      "actor_id": "string or null",
      "target_ids": ["string"],
      "parameters": {},
      "reason": "string or null",
      "confidence": 0.0
    }
  ]
}

Do not include markdown fences or extra keys.

Prefer these action types when relevant:
- `start_combat`
- `end_combat`
- `attack_roll`
- `apply_damage`
- `apply_healing`
- `add_condition`
- `remove_condition`
- `spend_spell_slot`
- `restore_spell_slot`
- `add_inventory_item`
- `remove_inventory_item`
- `create_quest`
- `advance_quest`
- `complete_quest`
- `set_location`

For `attack_roll`, include at least:
- `target_ids`
- either `attack_bonus` or `weapon`
- one of `damage_amount`, `damage_formula`, or `weapon`
