# AGENTS.md

## Purpose

All agents working in this repo must use the project's rule traceability workflow when implementing or changing gameplay rules.

The goal is to prevent deterministic backend logic from drifting away from the imported rules corpus or from being added without clear test coverage.

## Authority

For gameplay rules, treat these artifacts as the source of truth workflow:

1. imported rule chunks in `data/rules/processed/srd_5_2_1_chunks.jsonl`
2. the rule registry in `data/rules/traceability/rule_traceability_registry.json`
3. deterministic backend implementation and tests

The registry is the bridge between chunked rules and code.

## Required workflow for gameplay-rule changes

When a task adds or changes a gameplay rule:

1. Find the relevant chunk ids in `data/rules/processed/srd_5_2_1_chunks.jsonl` when the behavior is SRD-backed.
2. Add or update an entry in `data/rules/traceability/rule_traceability_registry.json`.
3. Implement the rule in code.
4. Add or update relevant tests.
5. Keep `implementation_refs` and `test_refs` current in the registry.

Do not treat a gameplay rule as complete unless the registry and tests are updated too.

## Status rules

Use these registry statuses consistently:

- `implemented`
  - rule behavior is implemented and tested
- `partial`
  - rule behavior exists but has known gaps or mixed rule-backed and assumed logic
- `provisional`
  - behavior is an app policy or simplifying abstraction not yet fully grounded in chunked rules
- `not_started`
  - rule is identified but not implemented

If you cannot map a behavior to chunked rules, do not pretend it is rule-backed.
Mark it as `implementation_kind: "app_policy"` and use `provisional` or `implemented` depending on whether the app policy itself is complete and tested.

## Test expectations per rule

Do not create one test per chunk by default.

Do create at least one relevant test per implemented rule entry:

- unit test when the logic is narrow and isolated
- integration test when the rule affects combat, chat orchestration, persistence, or multi-step state changes

When one test covers multiple traceability entries, reference that test from each relevant entry.

## Deterministic combat rules

When touching combat logic:

- prefer canonical state over inferred narration
- prefer chunk-backed rules over assumptions
- record known simplifications in the registry `gaps` field
- do not silently add new condition semantics, weapon behaviors, or effect stacking rules without updating traceability

## Retrieval-backed rules

If a change only affects retrieval or prompt assembly and does not change deterministic rule enforcement:

- update the registry only if it changes how a rule is grounded or cited
- otherwise keep the registry focused on deterministic or policy-level gameplay behavior

## Final response expectation

When you complete a gameplay-rule change, mention:

- whether the registry was updated
- whether the behavior is `implemented`, `partial`, or `provisional`
- which tests verify it
