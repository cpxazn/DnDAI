# Rule Traceability

This project uses a rule traceability registry to answer four questions for every implemented gameplay rule:

1. What is the rule behavior?
2. Which imported SRD chunk or chunks support it?
3. Where is it implemented in code?
4. Which tests verify it?

The machine-readable registry lives at:

- `data/rules/traceability/rule_traceability_registry.json`

## Why this exists

The backend currently has two different rule paths:

- retrieval-time rules context from the project's chunked SRD corpus
- deterministic gameplay logic implemented in Python

The registry makes it obvious which deterministic rules are:

- grounded in the chunked SRD
- only partially grounded
- still provisional app policy
- not implemented yet

## Registry fields

Each `rules[]` entry should include:

- `rule_id`
  - stable identifier such as `combat.condition.prone.attack_interaction`
- `title`
  - plain-language description of the behavior
- `domain`
  - broad area such as `combat`, `combat.conditions`, or `inventory`
- `status`
  - `implemented`, `partial`, `provisional`, or `not_started`
- `implementation_kind`
  - `deterministic_rule` when enforcing gameplay logic
  - `app_policy` for orchestration rules or temporary abstractions
- `source_chunk_ids`
  - zero or more chunk ids from `data/rules/processed/srd_5_2_1_chunks.jsonl`
- `implementation_refs`
  - local files that implement the behavior
- `test_refs`
  - local tests that verify the behavior
- `gaps`
  - optional list of known missing details
- `notes`
  - optional short context

## Workflow

When implementing or changing a gameplay rule:

1. Identify the relevant SRD chunk ids first, if the behavior is SRD-backed.
2. Add or update the registry entry before or alongside the code change.
3. Implement the deterministic behavior.
4. Add or update at least one relevant test per rule entry.
5. If the behavior is an app abstraction rather than a direct SRD rule, mark it as `app_policy`.
6. If implementation is incomplete, mark the entry `partial` or `provisional` and list the gaps.

## Test expectations

This registry is not meant to force one test per chunk.

Instead, the expectation is:

- at least one relevant test per implemented rule entry
- integration tests for cross-rule flows
- explicit gaps for anything still assumption-based

## Current use

The initial registry is seeded with:

- core attack roll resolution
- canonical ability/proficiency handling
- current prone, blinded, and poisoned condition semantics
- current combat effects and turn-order policies
- known gaps such as long-range disadvantage and hardcoded weapon fallbacks
