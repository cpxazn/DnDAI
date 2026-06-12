# AI Agent Handoff

## Current state

- Backend combat is functional and heavily expanded beyond the original slice.
- Deterministic combat now covers:
  - turn order and active-combatant gating
  - attack-roll resolution
  - ranged long-range disadvantage and long-range rejection when distance is known
  - reach, versatile, loading, ammunition use/recovery, and thrown handling
  - incapacitating-condition action locks
  - generic timed combat bonuses for AC, attack, damage, and speed
  - named Shield, Shield of Faith, and Barkskin support as SRD-backed combat effects
  - weapon mastery support for `cleave`, `graze`, `nick`, `push`, `sap`, `slow`, `topple`, and `vex`
  - partial Attack-action slot enforcement for supported single-class Extra Attack progression

- Combat state is richer now:
  - combatants carry `position_x`, `position_y`, and `size`
  - active combatant positions can be updated explicitly after combat starts
  - canonical character combatants derive better save bonuses at combat start
  - stat-light NPC combatants now get deterministic +0 save fallbacks
  - `attack_roll` outcomes now expose turn-local attack state and mastery details


## Latest verified baseline

- Focused action-service verification last passed at:
  - `11 passed`

- Targeted backend verification last passed at:
  - `64 passed`

- Full backend verification last passed at:
  - `74 passed`

- Commands used:
  - `.\.venv\Scripts\python -m compileall backend\app`
  - `.\.venv\Scripts\python -m json.tool data\rules\traceability\rule_traceability_registry.json`
  - `.\.venv\Scripts\python -m pytest backend\tests\integration\test_action_service.py --basetemp C:\tmp\mydnd-pytest-action`
  - `.\.venv\Scripts\python -m pytest backend/tests/integration/test_attack_roll_action.py backend/tests/integration/test_action_service.py backend/tests/integration/test_action_validation.py backend/tests/integration/test_character_update.py --basetemp C:\tmp\mydnd-pytest-targeted`
  - `.\.venv\Scripts\python -m pytest backend\tests --basetemp C:\tmp\mydnd-pytest-full`


## Completed

### 1. Improve NPC / stat-light save modeling

Status: done

Implemented:
- Free-standing stat-light combatants now receive deterministic `+0` saving throw fallbacks.
- `topple` now rolls against NPC targets without explicit `saving_throw_bonuses`.
- The registry remains honest: weapon mastery support is still `partial` because monster stat blocks, monster save proficiencies, and size/immune edge cases are not modeled.

Touched files:
- `backend/app/services/combat_service.py`
- `backend/app/services/action_service.py`
- `backend/tests/integration/test_attack_roll_action.py`
- `data/rules/traceability/rule_traceability_registry.json`


## Immediate next task

### 2. Make position and range flows first-class

Status: done

Implemented:
- Added `update_position` combat operation support.
- Combatant positions can now be changed during an active encounter by combatant reference.
- Updated positions are consumed by deterministic range and reach checks.
- The registry includes `combat.position.update_combatant_position` as an `implemented` app-policy entry.

### 3. Tighten remaining combat partials

Status: in progress

Progress:
- Push mastery now reports a deterministic blocked reason when a valid-size target cannot be moved because actor/target positions are missing or unusable.
- `combat.weapon_mastery.push_size_restriction` remains `partial` because map occupancy, collision, path blocking, and broader size sourcing are not modeled.
- Attack timing now enforces one Bonus Action attack per turn for represented `attack_roll` actions.
- `combat.turn_economy.attack_timing_tracking` remains `partial` because timing is still reconstructed from same-turn attack events rather than a full action-resource engine.
- Extra Attack slot coverage now explicitly verifies supported single-class Fighter 11/20 and Barbarian, Monk, Paladin, and Ranger level-5 progressions.
- Attack-action over-limit rejections now report used and available Attack-action slots.
- `combat.turn_economy.attack_action_extra_attack_slots` remains `partial` because multiclass non-stacking, warlock invocation variants, non-class extra attack sources, and full action-resource modeling are not implemented.

Important registry entries still not fully complete:
- `combat.weapon_mastery.supported_properties`
- `combat.weapon_mastery.push_size_restriction`
- `combat.turn_economy.attack_timing_tracking`
- `combat.turn_economy.attack_action_extra_attack_slots`
- `combat.effects.generic_bonus_effects`

### 4. Replace generic effect abstractions with SRD-backed named effects

Status: in progress

Why:
- Generic combat effects are useful substrate but still `provisional`.
- Concentration cleanup exists, but richer concentration rules and named SRD-backed effects are still incomplete.

Progress:
- Added `cast_shield_of_faith` as the first named SRD-backed combat effect action.
- Shield of Faith now applies a deterministic `+2` AC bonus, marks the effect as concentration, and rejects known targets beyond 60 feet.
- Added `cast_barkskin` as a named SRD-backed combat effect action.
- Barkskin now applies an AC floor of 17, preserves already-higher AC values, and rejects known targets beyond touch range.
- Added `cast_shield` as a named SRD-backed combat effect action.
- Shield now applies a self-only `+5` AC bonus as a 1-round timed effect and reports Magic Missile protection in the action outcome.
- The generic effect substrate remains `provisional`.
- New registry entry `combat.effects.shield_of_faith_ac_bonus` is `partial`, because spell slot spending, components, preparation, Bonus Action spell timing, willing-target checks, exact 10-minute duration, and full concentration ending rules are not modeled yet.
- New registry entry `combat.effects.barkskin_ac_floor` is `partial`, because spell slot spending, components, preparation, Bonus Action spell timing, willing-target checks, exact 1-hour duration, and full touch-range semantics beyond represented distances are not modeled yet.
- New registry entry `combat.effects.shield_ac_bonus` is `partial`, because triggering-hit retroactive AC, Reaction resource consumption, off-turn reaction timing, spell slot spending, components, preparation, and deterministic Magic Missile damage prevention are not modeled yet.

Touched files:
- `backend/app/services/action_service.py`
- `backend/app/services/combat_service.py`
- `backend/tests/integration/test_action_service.py`
- `data/rules/traceability/rule_traceability_registry.json`


## Next implementation target

### 5. Continue replacing generic effects with named SRD-backed effects

Recommended next slice:
- Add another named effect that exercises a non-AC effect shape, such as:
  - `Guiding Bolt`: ranged spell attack plus next-attack Advantage before the end of the caster's next turn, or
  - `Haste`: speed/AC/Dex-save/action effects plus concentration and post-effect lethargy, likely as a larger partial slice.

Recommended first move:
- Search `data/rules/processed/srd_5_2_1_chunks.jsonl` for the chosen spell chunk.
- Add the named action and focused integration tests.
- Add or update a dedicated registry entry with honest `partial` gaps.


## Important implementation notes

- Follow repo `AGENTS.md` for gameplay-rule changes.
- For gameplay rules, always update:
  - code
  - tests
  - `data/rules/traceability/rule_traceability_registry.json`

- Do not silently treat app-policy behavior as fully rule-backed.
- Keep registry statuses honest:
  - `implemented`
  - `partial`
  - `provisional`
  - `not_started`


## Recent combat work already done

- Attack-action slot enforcement exists for supported single-class Extra Attack progression.
- Light/Nick extra attacks are inferred more cleanly and do not consume normal primary Attack-action slots.
- Push now enforces Large-or-smaller target restriction when combatant size is known.
- Push now reports missing-position blockers in attack outcomes.
- Turn-local attack timing now reports and enforces Bonus Action attack usage.
- Attack-action slot enforcement now has explicit coverage for supported Extra Attack progressions and clearer over-limit reasons.
- Topple now uses better combat-start save data for canonical character combatants.
- Topple now uses a deterministic `+0` fallback for stat-light NPC combatants without explicit saves.
- Position-aware combat rules can now use positions updated after combat start.
- Turn-local attack state is returned in `attack_roll` outcomes.
- Shield of Faith now has a named SRD-backed deterministic combat action with focused integration coverage.
- Barkskin now has a named SRD-backed deterministic combat action with focused integration coverage for AC-floor behavior and touch-range rejection.
- Shield now has a named SRD-backed deterministic combat action with focused integration coverage for self-only targeting, timed `+5` AC, and expiry.


## Known remaining gaps

- NPC save modeling now has a deterministic fallback, but monster stat blocks and save proficiencies are not modeled.
- Combatant size still defaults to explicit combat input or `Medium`; it is not broadly synced from species, monster data, or transformations.
- Position-aware combat rules still depend on positions being present, but positions can now be initialized or updated explicitly.
- Action economy is better, but still not a fully modeled turn-resource system.
- Generic combat effects still need broader SRD-backed named effect modeling.
- Shield of Faith does not yet spend spell slots, enforce spell preparation/components, consume a modeled Bonus Action resource, require willing targets, or model exact 10-minute duration/concentration damage saves.
- Barkskin does not yet spend spell slots, enforce spell preparation/components, consume a modeled Bonus Action resource, require willing targets, or model exact 1-hour duration.
- Shield does not yet spend spell slots, enforce spell preparation/components, consume a modeled Reaction resource, validate triggering hits, retroactively change a triggering attack result, or prevent modeled Magic Missile damage.
- Pytest may need an explicit writable `--basetemp C:\tmp\...` on this machine; the default pytest temp/cache paths can hit Windows permission errors in this agent sandbox.


## Good next response for the next agent

- Continue replacing generic combat effects with named SRD-backed effects.
- Verify the relevant registry entries before changing behavior.
- Add focused integration coverage for each named effect.
- Re-run the same targeted backend test suite unless the change clearly requires broader coverage.
