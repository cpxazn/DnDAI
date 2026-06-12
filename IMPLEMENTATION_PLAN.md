# DnD LLM App Implementation Plan

## Goals

Build a beginner-friendly Dungeons and Dragons web application with:

- A Python backend that orchestrates gameplay and calls a locally hosted LLM via `llama.cpp`.
- A web frontend for chat, character sheets, and dice rolling.
- Persistent local data without requiring a managed database service.
- A memory architecture that supports long-running campaigns.
- Support for up to 4 player characters in a single active party.
- A clean foundation for future expansion, especially battle maps, voice features, and richer game systems.

## Product Scope

### v1

Deliver a playable text-first DnD experience with:

- Chat-based DM narration
- Character sheet viewing for up to 4 players
- Dice rolling
- Persistent campaign state
- Simple multi-tier memory
- Rules and lore retrieval

### v1.5 / v2

Extend the system with:

- Better retrieval and memory
- Voice input/output
- Structured combat tools
- Optional battle map support
- Multiplayer and richer campaign tooling

## Design Principles

### 1. App state is authoritative

The application owns all canonical game state:

- character stats
- HP
- spell slots
- inventory
- quests
- combat order
- NPC state

The LLM should narrate, suggest actions, and explain outcomes, but it should not be treated as the source of truth for state mutations.

### 2. Text-first, tools-second, visuals later

v1 should work fully without battle maps, voice, or fancy UI. This keeps scope manageable and gives a stable base for later upgrades.

### 3. Retrieval should be modular

Rules lookup, lore lookup, transcript search, and memory retrieval should be isolated behind service interfaces so they can evolve independently.

### 4. Battle map support must be additive

Combat and movement logic should not depend on a battle map existing. A future map system should plug into combat state, not replace it.

### 5. Prefer boring persistence

Use `SQLite` as the main store. It is simple, local, durable, and easy to back up. Add vector storage only when there is a clear need.

## Recommended Tech Stack

### Backend

- Python 3.12+
- FastAPI
- Pydantic
- `httpx` for LLM calls
- `sqlite3` or `SQLModel`/`SQLAlchemy` if desired later

### LLM

- `llama.cpp` `llama-server`
- OpenAI-compatible API mode

### Frontend

- React
- TypeScript
- Vite

### Persistence

- SQLite for canonical data
- SQLite FTS5 for keyword search over transcripts, lore, and rules
- Optional ChromaDB for scoped semantic retrieval

## Proposed Repository Layout

```text
myDnD/
  backend/
    app/
      api/
      core/
      db/
      models/
      schemas/
      services/
      prompts/
      tools/
      main.py
    tests/
  frontend/
    src/
      app/
      components/
      features/
        chat/
        characters/
        dice/
        session/
      lib/
      types/
    public/
  data/
    campaigns/
    lore/
    rules/
    imports/
  docs/
```

### Recommended implementation scaffold

To reduce ambiguity for implementation agents, v1 should target a concrete starter scaffold like:

```text
myDnD/
  backend/
    app/
      api/
        chat.py
        campaigns.py
        sessions.py
        characters.py
        party.py
        dice.py
        combat.py
        memory.py
      core/
        config.py
        logging.py
      db/
        schema.sql
        migrations/
        session.py
      models/
      schemas/
        chat.py
        campaigns.py
        dice.py
        combat.py
      services/
        chat_orchestrator.py
        llm_client.py
        rules_service.py
        lore_service.py
        memory_service.py
        character_service.py
        inventory_service.py
        quest_service.py
        combat_service.py
      prompts/
        system_prompt.md
        chat_response_contract.md
      tools/
      main.py
    tests/
      unit/
      integration/
  frontend/
  data/
  docs/
```

## High-Level Architecture

### Backend services

- `game_state_service`
  - Reads and writes canonical campaign state.
- `chat_orchestrator`
  - Builds prompt context and calls the LLM.
- `dice_service`
  - Resolves rolls and modifiers deterministically.
- `memory_service`
  - Manages recent turns, summaries, extracted facts, and retrieval.
- `rules_service`
  - Retrieves rules snippets from local sources.
- `lore_service`
  - Retrieves campaign lore, NPC notes, and prior events.
- `session_service`
  - Creates campaigns, sessions, and logs.

### Recommended service responsibilities

To avoid logic drifting across modules, use the following boundaries:

- `chat_orchestrator`
  - loads turn context, assembles the prompt, calls the LLM, parses `proposed_actions`, coordinates validation/application, and returns the final `/chat` response
- `llm_client`
  - handles model transport, request formatting, retries, and streaming token delivery
- `rules_service`
  - performs rules retrieval, ranking, deduplication, and citation packaging
- `lore_service`
  - performs lore retrieval for campaign-specific and shared lore
- `memory_service`
  - loads recent turns, scene summaries, extracted facts, and optional memory debug views
- `character_service`
  - reads and mutates character canonical state such as HP, conditions, and spell slots
- `inventory_service`
  - applies inventory additions, removals, and equipment changes
- `quest_service`
  - applies quest creation and progression updates
- `combat_service`
  - starts and ends encounters, applies combat damage/healing, and manages initiative/combatants
- `session_service`
  - handles campaign/session lifecycle and active-session selection

Business logic should live in these services, not in API handlers or prompt templates.

### Frontend feature areas

- `chat`
  - message stream, streaming narration, action entry
- `characters`
  - up to 4 viewable character sheets
- `dice`
  - roll controls and result history
- `session`
  - campaign selection, notes, memory/debug views

## Core Data Model

The exact schema can evolve, but v1 should support these entities:

- `campaigns`
- `sessions`
- `turns`
- `characters`
- `party_members`
- `character_stats`
- `inventory_items`
- `quests`
- `locations`
- `npcs`
- `combat_encounters`
- `combatants`
- `scene_summaries`
- `memory_facts`
- `rules_documents`
- `lore_documents`

### Important separation

- Canonical state tables store truth.
- Transcript and summary tables store conversation history.
- Retrieval tables store searchable text and memory artifacts.

### Party model

v1 should explicitly support:

- 1 active campaign
- 1 active session at a time
- up to 4 player characters in the active party

Recommended modeling:

- store each player character as a normal `character`
- use `party_members` to associate a character with a campaign/session party
- keep party order explicit for UI display
- allow NPC companions later without redesigning the schema

## Memory Strategy

### Tier 0: Canonical state

Always include:

- active party
- active speaker or acting character if relevant
- current HP and conditions
- inventory highlights
- current location
- active quests
- combat state if relevant

### Tier 1: Working context

Include:

- current scene summary
- last 6 to 10 turns

### Tier 2: Episodic memory

Store short summaries for:

- scenes
- combats
- rests
- major discoveries

### Tier 3: Semantic memory

Store extracted facts such as:

- relationships
- secrets discovered
- promises made
- item significance
- world state changes

### Tier 4: Archive

Store full transcripts and source documents for search and future reprocessing.

## Semantic Retrieval Recommendation

Semantic retrieval is recommended as a narrow v1 enhancement, not as the center of the architecture.

### Recommendation

If implemented in v1, semantic retrieval should only cover:

- scene summaries
- extracted memory facts

It should not initially cover:

- every raw transcript turn
- full rules corpus embeddings
- full lore corpus embeddings unless clearly needed

### Why this scope is recommended

- It gives most of the value for long-term memory recall.
- It keeps indexing cost and complexity low.
- It avoids turning v1 into a retrieval tuning project.
- It allows SQLite to remain the canonical source of truth.

### Suggested hybrid retrieval strategy

Use a layered retrieval flow:

1. Filter by campaign/session/entity tags where possible.
2. Query SQLite FTS for exact or near-exact matches.
3. Query semantic memory store for related summaries/facts.
4. Merge and rank a small set of results.
5. Send only the best items into the prompt.

### Storage recommendation

- Keep canonical records, transcripts, summaries, and facts in SQLite.
- If semantic retrieval is enabled, store embeddings for summaries/facts in ChromaDB.
- Keep stable record IDs so semantic results can always map back to SQLite records.

### Effort guidance

Scoped semantic retrieval is considered feasible in v1 if limited to summaries and facts. It should be treated as an optional memory enhancement layer that can be disabled without affecting the rest of gameplay systems.

## Rules Corpus Ingestion and Retrieval Plan

The rules corpus should be treated as a preprocessed retrieval asset, not as raw prompt context.

### Rule traceability decision

Deterministic gameplay rules should not be allowed to drift away from the imported rules corpus without being tracked explicitly.

Recommended v1 rule:

- keep imported SRD chunks as the retrieval-time reference source
- maintain a machine-readable rule registry that maps implemented rule behavior to:
  - supporting chunk ids
  - implementation files
  - relevant tests
  - implementation status such as `implemented`, `partial`, `provisional`, or `not_started`

Recommended artifacts:

- `data/rules/traceability/rule_traceability_registry.json`
- `docs/RULE_TRACEABILITY.md`
- repo-level `AGENTS.md` instructions that require registry and test updates when gameplay rules change

### Important distinction

The app has two rule paths that must stay visible to implementers:

- retrieval-backed rule context used by the LLM through `rules_service`
- deterministic Python logic that actually enforces canonical gameplay behavior

The traceability registry exists to make it obvious which deterministic rules are:

- directly grounded in chunked SRD rules
- only partially grounded
- still provisional app policy
- not implemented yet

### Source format decision

For the SRD, prefer markdown source files over direct PDF extraction.

Recommended source flow:

1. Keep a pinned local copy of the markdown SRD source.
2. Run an ingestion script that converts markdown into normalized JSONL chunks.
3. Import the JSONL into SQLite tables used by `rules_service`.
4. Query SQLite/FTS first, then send only a small set of top-ranked chunks into the prompt.

### Why this approach is preferred

- Markdown preserves heading structure better than PDF extraction.
- JSONL is a good intermediate format for import, validation, and debugging.
- Chunking at ingest time avoids doing parsing work at request time.
- The LLM never needs the full rules corpus in its context window.

### Recommended artifact flow

- source markdown files
- processed section/chunk records in JSONL
- imported SQLite `rules_documents` rows
- optional FTS tables or views for retrieval

### Recommended rules document shape

Each imported rules chunk should carry at least:

- `id`
- `doc_type`
- `ruleset`
- `source_file`
- `chapter`
- `section`
- `subsection`
- `part`
- `heading_path`
- `tags`
- `word_count`
- `text`

### Chunking guidance

- Split primarily on markdown heading boundaries.
- Keep one logical rule section, glossary entry, spell subsection, or monster subsection per chunk when possible.
- If a section is too large, split it secondarily into bounded chunks while preserving heading metadata.
- Preserve heading ancestry so retrieved chunks can be displayed and ranked with context.

### v1 retrieval unit decision

Use a parent-or-leaf retrieval strategy.

- For exact lookups, prefer the most specific matching chunk.
- For broader questions, prefer the parent section chunk.
- Do not automatically include both parent and child chunks if they are near-duplicates.

### Retrieval behavior

The LLM should not search the JSONL or the full rules corpus directly in prompt context.

Recommended request-time flow:

1. Receive player input or tool request.
2. Let `rules_service` perform retrieval outside the LLM.
3. Query SQLite FTS over rules text and metadata.
4. Rank and deduplicate the results.
5. Inject only the top few chunks into the prompt.

### v1 retrieval execution rules

To reduce implementation ambiguity, use the following default retrieval flow:

1. Normalize the user query into a retrieval query string.
2. Search `section`, `subsection`, and `text` through SQLite FTS.
3. Compute a final score from:
   - FTS rank
   - exact heading match boost
   - exact subsection match boost
   - tag match boost
   - source-priority boost for glossary/definition-like chunks
4. Collapse near-duplicate parent/child results after ranking.
5. Return at most:
   - 4 rules chunks
   - 3 lore chunks
   - 4 memory snippets
6. Apply lane-specific prompt budgets before prompt assembly.

Default dedupe rule:

- if a parent and child chunk are both selected and their texts substantially overlap, keep only the more specific chunk unless the parent is needed for context

### v1 retrieval ranking decision

Use hybrid ranking built on SQLite FTS plus metadata boosts.

Recommended behavior:

- use FTS rank as the base score
- boost exact heading, section, and subsection matches
- boost glossary-style or definition-style chunks for direct rules questions
- penalize near-duplicate parent/child matches
- cap the final prompt set after deduplication

### Prompt budget guidance

To avoid context bloat:

- prefer a small retrieved set such as 3 to 8 chunks
- favor exact or glossary-like matches first
- avoid sending both a parent chunk and many near-duplicate child chunks unless necessary
- keep retrieval modular so the budget can be tuned without changing the rest of the app

### v1 prompt budget decision

Use explicit per-lane context budgets rather than only a fixed chunk count.

Recommended lanes:

- recent transcript
- retrieved memory
- retrieved rules
- retrieved lore

Each lane should have its own configurable budget so retrieval improvements do not silently consume the whole prompt window.

### Import/versioning recommendation

Rules imports should be versioned and reproducible.

Recommended metadata to track per import:

- source corpus name
- source version or commit hash
- import timestamp
- chunker version
- ruleset label

### v1 import metadata decision

Store import metadata in a dedicated `corpus_imports` table and link imported rules/lore chunks to `import_id`.

Recommended `corpus_imports` fields:

- `id`
- `corpus_type`
- `source_name`
- `source_version`
- `source_commit_hash`
- `ruleset`
- `chunker_version`
- `imported_at`
- `notes`

This makes it easy to rebuild the corpus, compare retrieval quality across imports, and invalidate stale indexes safely.

### Minimal SQLite schema sketch

The following schema is a good minimal starting point for imported rules corpora in v1.

```sql
CREATE TABLE corpus_imports (
  id INTEGER PRIMARY KEY,
  corpus_type TEXT NOT NULL,            -- "rules" or "lore"
  source_name TEXT NOT NULL,            -- e.g. "dnd-5e-srd-markdown"
  source_version TEXT,                  -- e.g. "SRD 5.2.1"
  source_commit_hash TEXT,
  ruleset TEXT,
  chunker_version TEXT NOT NULL,
  imported_at TEXT NOT NULL,            -- ISO-8601 timestamp
  notes TEXT
);

CREATE TABLE rules_documents (
  id TEXT PRIMARY KEY,                  -- stable chunk id
  import_id INTEGER NOT NULL REFERENCES corpus_imports(id),
  doc_type TEXT NOT NULL,               -- e.g. "rules_reference"
  ruleset TEXT NOT NULL,
  source_file TEXT NOT NULL,
  chapter TEXT,
  section TEXT NOT NULL,
  subsection TEXT,
  part TEXT,
  heading_path_json TEXT NOT NULL,      -- JSON array of strings
  tags_json TEXT NOT NULL,              -- JSON array of strings
  word_count INTEGER NOT NULL,
  text TEXT NOT NULL
);
```

### Minimal indexing recommendation

For v1, add simple relational indexes plus an FTS table.

Recommended indexes:

```sql
CREATE INDEX idx_rules_documents_import_id
  ON rules_documents(import_id);

CREATE INDEX idx_rules_documents_section
  ON rules_documents(section);

CREATE INDEX idx_rules_documents_subsection
  ON rules_documents(subsection);

CREATE VIRTUAL TABLE rules_documents_fts USING fts5(
  id UNINDEXED,
  section,
  subsection,
  text,
  content='rules_documents',
  content_rowid='rowid'
);
```

### Practical relationship

- one row in `corpus_imports` represents one import run
- many rows in `rules_documents` belong to that import via `import_id`
- reimporting the SRD later creates a new `corpus_imports` row and a new associated set of chunks

This keeps import history explicit without complicating runtime retrieval.

### Matching lore schema sketch

Use the same import pattern for lore so rules and lore stay operationally consistent.

```sql
CREATE TABLE lore_documents (
  id TEXT PRIMARY KEY,                  -- stable chunk id
  import_id INTEGER NOT NULL REFERENCES corpus_imports(id),
  doc_type TEXT NOT NULL,               -- e.g. "lore_reference"
  campaign_id INTEGER,                  -- null for shared/global lore
  source_file TEXT NOT NULL,
  chapter TEXT,
  section TEXT NOT NULL,
  subsection TEXT,
  part TEXT,
  heading_path_json TEXT NOT NULL,      -- JSON array of strings
  tags_json TEXT NOT NULL,              -- JSON array of strings
  word_count INTEGER NOT NULL,
  text TEXT NOT NULL
);
```

Recommended v1 indexes:

```sql
CREATE INDEX idx_lore_documents_import_id
  ON lore_documents(import_id);

CREATE INDEX idx_lore_documents_campaign_id
  ON lore_documents(campaign_id);

CREATE VIRTUAL TABLE lore_documents_fts USING fts5(
  id UNINDEXED,
  section,
  subsection,
  text,
  content='lore_documents',
  content_rowid='rowid'
);
```

### Minimal turn and event schema sketch

The app should persist turns and state-change events separately.

`turns` stores the conversational unit. `game_events` stores the structured consequences.

```sql
CREATE TABLE turns (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  turn_index INTEGER NOT NULL,          -- monotonically increasing within session
  speaker_role TEXT NOT NULL,           -- "player", "assistant", "system", "tool"
  speaker_entity_id TEXT,               -- character/NPC id when relevant
  user_text TEXT,                       -- raw player input when this is a player turn
  assistant_text TEXT,                  -- final DM narration when this is an assistant turn
  proposed_actions_json TEXT,           -- JSON array of typed action proposals
  retrieval_debug_json TEXT,            -- optional retrieved chunk ids/metadata
  created_at TEXT NOT NULL              -- ISO-8601 timestamp
);

CREATE UNIQUE INDEX idx_turns_session_turn_index
  ON turns(session_id, turn_index);

CREATE TABLE game_events (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  turn_id INTEGER NOT NULL REFERENCES turns(id),
  event_index INTEGER NOT NULL,         -- ordering within a turn
  event_type TEXT NOT NULL,             -- e.g. "damage_applied"
  actor_id TEXT,
  target_id TEXT,
  details_json TEXT NOT NULL,           -- event-specific payload
  created_at TEXT NOT NULL              -- ISO-8601 timestamp
);

CREATE UNIQUE INDEX idx_game_events_turn_event_index
  ON game_events(turn_id, event_index);

CREATE INDEX idx_game_events_event_type
  ON game_events(event_type);

CREATE INDEX idx_game_events_target_id
  ON game_events(target_id);
```

### Practical turn persistence relationship

- one `turns` row represents one persisted conversational turn
- one turn may produce zero or many `game_events`
- `assistant_text` stores the DM narration
- `proposed_actions_json` stores the model's structured proposals for that turn
- `game_events` stores only the validated changes the app actually committed

This separation makes it possible to compare what the model suggested against what the app accepted.

### Minimal canonical state schema sketch

The following tables are the minimal v1 starting point for canonical campaign truth.

```sql
CREATE TABLE campaigns (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  current_location_id INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE sessions (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  started_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE TABLE characters (
  id TEXT PRIMARY KEY,                  -- stable app-generated entity id
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
  name TEXT NOT NULL,
  character_type TEXT NOT NULL,         -- "player", "npc", "monster", "companion"
  ancestry TEXT,
  class_summary TEXT,
  level INTEGER,
  armor_class INTEGER,
  max_hp INTEGER NOT NULL,
  current_hp INTEGER NOT NULL,
  temp_hp INTEGER NOT NULL DEFAULT 0,
  speed_json TEXT,                      -- JSON object for walk/fly/swim/etc.
  ability_scores_json TEXT NOT NULL,    -- JSON object for STR/DEX/CON/INT/WIS/CHA
  conditions_json TEXT NOT NULL,        -- JSON array of active conditions
  spell_slots_json TEXT,                -- nullable JSON object
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_characters_campaign_id
  ON characters(campaign_id);

CREATE TABLE party_members (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
  session_id INTEGER REFERENCES sessions(id),
  character_id TEXT NOT NULL REFERENCES characters(id),
  party_order INTEGER NOT NULL,
  role_label TEXT,                      -- e.g. "frontline", "support"
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX idx_party_members_campaign_character
  ON party_members(campaign_id, character_id);

CREATE UNIQUE INDEX idx_party_members_campaign_order
  ON party_members(campaign_id, party_order);

CREATE TABLE inventory_items (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
  owner_character_id TEXT REFERENCES characters(id),
  name TEXT NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 1,
  item_type TEXT,
  is_equipped INTEGER NOT NULL DEFAULT 0,
  notes TEXT
);

CREATE INDEX idx_inventory_items_owner_character_id
  ON inventory_items(owner_character_id);

CREATE TABLE quests (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
  title TEXT NOT NULL,
  status TEXT NOT NULL,                 -- "active", "completed", "failed"
  summary TEXT,
  giver_name TEXT,
  current_objective TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_quests_campaign_status
  ON quests(campaign_id, status);
```

### Minimal combat schema sketch

Combat state should be structured even before map support exists.

```sql
CREATE TABLE combat_encounters (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  status TEXT NOT NULL,                 -- "active", "completed", "fled"
  round_number INTEGER NOT NULL DEFAULT 1,
  turn_index INTEGER NOT NULL DEFAULT 0,
  location_name TEXT,
  notes TEXT,
  started_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE TABLE combatants (
  id INTEGER PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES combat_encounters(id),
  character_id TEXT REFERENCES characters(id),   -- nullable for transient combatants if needed
  display_name TEXT NOT NULL,
  side TEXT NOT NULL,                   -- "party", "ally", "enemy", "neutral"
  initiative_score INTEGER,
  initiative_order INTEGER,
  current_hp INTEGER NOT NULL,
  max_hp INTEGER NOT NULL,
  temp_hp INTEGER NOT NULL DEFAULT 0,
  conditions_json TEXT NOT NULL,
  x INTEGER,                            -- nullable until map support is used
  y INTEGER,
  speed_json TEXT,
  notes TEXT
);

CREATE INDEX idx_combatants_encounter_order
  ON combatants(encounter_id, initiative_order);
```

### Canonical state boundary

For v1, these tables should be treated as canonical truth:

- `campaigns`
- `sessions`
- `characters`
- `party_members`
- `inventory_items`
- `quests`
- `combat_encounters`
- `combatants`

By contrast:

- `turns` and `game_events` are history and audit records
- `rules_documents` and `lore_documents` are imported retrieval corpora
- summaries and memory facts are derived support data, not authoritative state

This boundary is important because all validated game mutations should ultimately resolve into updates on these canonical tables.

## Turn Orchestration and State Mutation Plan

The app should define an explicit turn pipeline early so orchestration, persistence, and narration stay aligned.

### Recommended turn flow

1. Accept user input and identify the active campaign/session.
2. Load canonical state and recent transcript context.
3. Retrieve relevant rules, lore, and memory snippets.
4. Call the LLM to produce narration and any structured action proposals.
5. Validate and apply deterministic state changes in application services.
6. Persist transcript, events, and state updates.
7. Optionally generate summaries or extracted facts asynchronously after the turn completes.

### State mutation rule

The LLM may propose actions or outcomes, but only application code should commit state changes.

Recommended v1 pattern:

- LLM output may include a structured action proposal
- backend services validate that proposal
- services apply approved mutations to canonical tables
- persisted events record what changed and why

### v1 action proposal decision

Use a typed action envelope rather than an unstructured JSON blob.

Recommended top-level response shape:

- `narration`
- `proposed_actions`

Each proposed action should include at least:

- `type`
- `actor_id`
- `target_ids`
- `parameters`
- `reason`
- `confidence`

Example action types:

- `apply_damage`
- `heal`
- `add_item`
- `remove_item`
- `advance_quest`
- `consume_spell_slot`
- `start_combat`

### Minimal `proposed_actions` JSON contract

Recommended top-level assistant turn payload shape:

```json
{
  "narration": "The goblin slashes at Aric for 5 damage.",
  "proposed_actions": [
    {
      "type": "apply_damage",
      "actor_id": "npc_goblin_01",
      "target_ids": ["pc_aric"],
      "parameters": {
        "amount": 5,
        "damage_type": "slashing",
        "combatant_id": "combatant_pc_aric"
      },
      "reason": "Goblin shortsword attack hit.",
      "confidence": 0.93
    }
  ]
}
```

Recommended action object fields:

- `type`
- `actor_id`
- `target_ids`
- `parameters`
- `reason`
- `confidence`

Field expectations:

- `type`: required string from a small allowed set
- `actor_id`: optional stable entity id for the acting character/NPC/system source
- `target_ids`: required array, possibly empty for some actions like `start_combat`
- `parameters`: required object with action-specific payload
- `reason`: short natural-language explanation for logs/debugging
- `confidence`: float from `0.0` to `1.0`

### Recommended v1 action type set

Keep the allowed set intentionally small in v1:

- `apply_damage`
- `heal`
- `add_condition`
- `remove_condition`
- `add_item`
- `remove_item`
- `advance_quest`
- `set_location`
- `consume_spell_slot`
- `restore_spell_slots`
- `start_combat`
- `end_combat`

The backend should reject unknown action types rather than trying to infer intent from them.

### Example action payloads

`apply_damage`

```json
{
  "type": "apply_damage",
  "actor_id": "npc_goblin_01",
  "target_ids": ["pc_aric"],
  "parameters": {
    "amount": 5,
    "damage_type": "slashing",
    "combatant_id": "combatant_pc_aric"
  },
  "reason": "Goblin attack hit.",
  "confidence": 0.93
}
```

`add_item`

```json
{
  "type": "add_item",
  "actor_id": "system",
  "target_ids": ["pc_lyra"],
  "parameters": {
    "name": "Silver Key",
    "quantity": 1,
    "item_type": "quest_item"
  },
  "reason": "Lyra picked up the key from the altar.",
  "confidence": 0.97
}
```

`advance_quest`

```json
{
  "type": "advance_quest",
  "actor_id": "system",
  "target_ids": ["quest_missing_caravan"],
  "parameters": {
    "status": "active",
    "current_objective": "Travel to the ruined watchtower.",
    "summary_append": "The party found a map pointing to the watchtower."
  },
  "reason": "New lead discovered during investigation.",
  "confidence": 0.88
}
```

`start_combat`

```json
{
  "type": "start_combat",
  "actor_id": "system",
  "target_ids": [],
  "parameters": {
    "location_name": "Old Bridge",
    "participant_ids": ["pc_aric", "pc_lyra", "npc_goblin_01", "npc_goblin_02"]
  },
  "reason": "Hostile action began and initiative is needed.",
  "confidence": 0.91
}
```

### Validation expectations

Before applying any action, backend code should validate:

1. the action `type` is allowed
2. referenced entity IDs exist when required
3. required parameter keys are present for that action type
4. parameter values are sane for the current state
5. the proposed mutation is compatible with campaign/session/combat context

Examples:

- do not apply damage to a missing target
- do not consume a spell slot level the character does not have
- do not add an item with a negative quantity
- do not start combat if an active encounter already exists unless escalation rules explicitly allow it

### Minimal action validation matrix

`apply_damage`

- requires exactly one target
- requires `amount >= 0`
- target must resolve to a valid character or combatant

`heal`

- requires exactly one target
- requires `amount >= 0`
- target must resolve to a valid character or combatant

`add_item`

- requires exactly one target owner
- requires non-empty `name`
- requires `quantity > 0`

`remove_item`

- requires exactly one target owner
- requires non-empty `name`
- requires `quantity > 0`
- owner must have enough quantity to remove

`advance_quest`

- requires exactly one quest target
- quest must exist
- status, if provided, must be allowed

`consume_spell_slot`

- requires exactly one caster target
- slot level must exist
- remaining slot count must be greater than zero

`start_combat`

- requires no active encounter for the session
- participant ids, if provided, must resolve to known entities

`end_combat`

- requires an active encounter

### Mapping to canonical state

Each accepted action type should map to a narrow service-level handler.

Examples:

- `apply_damage` -> `combat_service.apply_damage(...)` or `character_service.apply_damage(...)`
- `add_item` -> `inventory_service.add_item(...)`
- `advance_quest` -> `quest_service.advance_quest(...)`
- `start_combat` -> `combat_service.start_encounter(...)`

This keeps validation and mutation logic out of the prompt layer and in normal application code.

This keeps narration flexible while preventing accidental drift between prose and game state.

### v1 mutation safety decision

Auto-apply only deterministic, low-risk, schema-valid actions in v1.

Examples:

- HP changes
- inventory changes
- quest state changes
- spell slot consumption

Higher-risk or ambiguous actions can remain narration-only for v1 and move to explicit approval tooling later if needed.

### v1 entity identification decision

Use stable internal entity IDs for characters, NPCs, items, quests, and combatants.

- names may appear in prompts and UI
- IDs should be used for state mutation, event logging, and retrieval linking

This avoids ambiguity when different entities share similar names.

### Transaction boundary recommendation

Each turn should have a clear persistence boundary.

Recommended v1 rule:

- write transcript, state mutations, and game events atomically when possible
- do not partially apply HP/inventory/quest changes without also recording the corresponding turn or event
- run slower summary/fact extraction after the core turn commit if needed

This improves crash safety, auditing, and replayability.

### v1 summary pipeline decision

Run scene-summary generation and fact extraction after the core turn commit.

- the core turn should finish quickly and safely
- summaries and extracted facts can run synchronously after commit or in a lightweight async job
- these secondary steps should never block persistence of the canonical turn result

## Additional Architectural Decisions To Lock Early

The following decisions are worth making now to avoid rework later.

### 1. Event log is a first-class model

In addition to current-state tables, keep an append-oriented game event log for important state changes.

Useful event types include:

- damage taken
- healing received
- item gained or lost
- quest advanced
- spell slot spent
- location changed

Recommended v1 shape:

- a typed event table with core indexed columns
- flexible JSON details for event-specific payloads

Suggested core columns:

- `id`
- `event_type`
- `campaign_id`
- `session_id`
- `turn_id`
- `actor_id`
- `target_id`
- `created_at`
- `details_json`

This supports auditability, memory rebuilding, summaries, and future timeline/debug tools.

### 2. Retrieval budget should be explicit

Prompt assembly should have configurable limits for:

- recent turns
- memory snippets
- rules chunks
- lore chunks

Without explicit caps, retrieval quality improvements can silently become prompt-size regressions.

### 3. Imported corpora should stay separate from canonical game state

Rules and lore imports should remain replaceable reference data sets, not mixed into campaign truth tables.

Recommended separation:

- `rules_documents` and `lore_documents` for imported reference text
- canonical campaign tables for mutable game state
- linking by stable IDs or tags rather than embedding reference text into state rows

### 4. One active write session should be assumed in v1

Because v1 is local-first and single-user oriented, design for one active writer per campaign/session.

This simplifies:

- SQLite transaction handling
- turn ordering
- conflict avoidance
- session state assumptions in the UI

Multiplayer and concurrent writes can be added later as an explicit v2 expansion.

### 5. Rule citations should be lightweight and visible

Retrieved rules context should preserve enough source metadata to explain where an answer came from.

Recommended v1 behavior:

- keep `heading_path` and source metadata on every rules chunk
- allow the backend or UI to show lightweight references such as `Spells > Casting Spells > Spell Level`
- do not require long verbatim citations in every response

## Battle Map Expandability Plan

v1 should prepare for battle maps without implementing them.

### Decisions to make now

- Represent combat as structured data, not just prose.
- Store positions abstractly even if unused at first.
- Separate `combat rules` from `combat rendering`.

### Suggested future-friendly combat model

Each combatant can eventually support:

- `x`, `y` grid position
- facing or token metadata if needed later
- movement speed
- range metadata
- line-of-sight flags

v1 combat should already support:

- up to 4 player-controlled combatants
- any number of NPCs/monsters within practical local limits

### v1 approach

- Allow combat encounters without positions.
- Keep position fields nullable.
- Build frontend combat UI as a panel, not a hardcoded map canvas.

### v2 map approach

Add a `map_service` and frontend map module that read/write the same combat state. This makes battle maps a feature layer instead of an architectural rewrite.

## Minimal API Contract Plan

The API should expose a small, explicit surface in v1.

`/chat` should be the primary gameplay orchestration endpoint. Supporting endpoints should expose canonical state and deterministic tools without duplicating the orchestration logic.

### General API response shape

For v1, prefer predictable JSON envelopes:

```json
{
  "data": {},
  "error": null
}
```

On failure:

```json
{
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Character not found."
  }
}
```

### `POST /chat`

This is the main turn endpoint.

Recommended request:

```json
{
  "campaign_id": 1,
  "session_id": 12,
  "speaker_entity_id": "pc_aric",
  "message": "I attack the goblin with my longsword.",
  "client_context": {
    "active_character_id": "pc_aric",
    "ui_mode": "chat"
  },
  "options": {
    "apply_deterministic_actions": true,
    "include_debug": false,
    "stream": false
  }
}
```

Recommended response:

```json
{
  "data": {
    "turn_id": 103,
    "session_id": 12,
    "campaign_id": 1,
    "narration": "Aric lunges forward and strikes the goblin for 5 slashing damage.",
    "proposed_actions": [
      {
        "type": "apply_damage",
        "actor_id": "pc_aric",
        "target_ids": ["npc_goblin_01"],
        "parameters": {
          "amount": 5,
          "damage_type": "slashing",
          "combatant_id": "combatant_goblin_01"
        },
        "reason": "Longsword attack hit.",
        "confidence": 0.94
      }
    ],
    "applied_actions": [
      {
        "type": "apply_damage",
        "event_id": 501
      }
    ],
    "citations": [
      {
        "source_type": "rules",
        "document_id": "playing-the-game-playing-the-game-d20-tests-attack-rolls",
        "heading_path": ["Playing the Game", "D20 Tests", "Attack Rolls"]
      }
    ],
    "state_summary": {
      "active_combat_encounter_id": 9,
      "changed_entities": ["npc_goblin_01"]
    },
    "debug": null
  },
  "error": null
}
```

### `POST /chat` behavior notes

- `message` is the raw player utterance for the turn
- `speaker_entity_id` identifies the acting character when relevant
- `proposed_actions` reflects the model output
- `applied_actions` reflects only validated, committed mutations
- `citations` is optional but recommended for rules transparency
- `debug` should be omitted or null unless explicitly requested

### Streaming recommendation

For v1, support two modes:

- non-streaming JSON response for simple integration and testing
- WebSocket streaming mode for the frontend chat UI

### v1 streaming transport decision

Use WebSockets in v1 for chat streaming.

Reasons:

- it supports token streaming and final turn completion cleanly
- it reduces rework if richer multiplayer or bidirectional session features are added later
- it fits future live combat/session updates better than a narrower one-way transport

Recommended pattern:

- keep `POST /chat` for standard request/response turns
- add a WebSocket chat channel for streaming narration and final turn events
- ensure both paths resolve to the same logical turn result schema

### `GET /campaigns`

Return the list of campaigns.

Example response:

```json
{
  "data": [
    {
      "id": 1,
      "name": "Ashes of Blackstone",
      "status": "active"
    }
  ],
  "error": null
}
```

### `POST /campaigns`

Create a campaign.

Example request:

```json
{
  "name": "Ashes of Blackstone"
}
```

### `GET /sessions`

Return sessions for a campaign.

Recommended query parameters:

- `campaign_id`

### `POST /sessions`

Create or start a session for a campaign.

Example request:

```json
{
  "campaign_id": 1,
  "name": "Session 1"
}
```

### `GET /characters`

Return characters for a campaign and optionally the current party.

Recommended query parameters:

- `campaign_id`
- `include_party`

### `GET /party`

Return the ordered active party for a campaign/session.

Example response should include:

- character ids
- display names
- party order
- current HP
- active conditions

### `POST /dice/roll`

Expose deterministic dice rolling as a separate tool endpoint.

Example request:

```json
{
  "formula": "1d20+5",
  "roll_type": "attack",
  "advantage_state": "normal"
}
```

Example response:

```json
{
  "data": {
    "formula": "1d20+5",
    "dice": [
      {
        "sides": 20,
        "result": 14
      }
    ],
    "modifier_total": 5,
    "total": 19
  },
  "error": null
}
```

### `GET /combat`

Return the active encounter for a campaign/session if one exists.

Recommended response should include:

- encounter id
- round number
- turn index
- ordered combatants
- each combatant's HP, conditions, and initiative

### `POST /combat`

Use this endpoint for explicit deterministic combat operations that should not require a full chat turn.

Recommended v1 uses:

- manually start combat
- manually end combat
- reorder initiative if needed for GM correction

The endpoint should remain narrow and should not become a second orchestration path for normal gameplay narration.

### `GET /memory`

Return memory artifacts for debugging and inspection.

Recommended query parameters:

- `campaign_id`
- `session_id`
- `include_recent_turns`
- `include_scene_summaries`
- `include_facts`

This endpoint is primarily for internal tooling and debug UI in v1.

### v1 API design decisions

- use `/chat` as the main orchestration entry point
- keep deterministic utilities like dice as separate narrow endpoints
- keep canonical state readable through dedicated GET endpoints
- do not split normal gameplay across multiple competing write endpoints
- ensure endpoint outputs map cleanly onto the persistence and action schemas already defined

### Recommended schema names

To reduce implementation drift, define explicit backend schema names such as:

- `ChatRequest`
- `ChatResponse`
- `ChatStreamEvent`
- `CampaignSummary`
- `CampaignCreateRequest`
- `SessionCreateRequest`
- `CharacterSummary`
- `PartyMemberSummary`
- `DiceRollRequest`
- `DiceRollResponse`
- `CombatStateResponse`
- `MemoryDebugResponse`

## Prompt Assembly Contract

Prompt assembly should be specified explicitly so multiple agents build the same orchestrator behavior.

### Recommended prompt section order

1. system instructions
2. response contract for `narration` plus `proposed_actions`
3. canonical state summary
4. current combat summary if active
5. recent transcript
6. retrieved memory
7. retrieved rules
8. retrieved lore
9. current player message

### Recommended canonical state summary contents

Always include:

- campaign name
- active session id or name
- ordered party summary
- current location
- active quests
- active combat encounter id if present

Per party member include:

- id
- name
- current HP / max HP
- active conditions
- notable inventory highlights
- remaining spell slots if relevant

### Recent transcript policy

- include the last 6 turns by default
- allow fewer if prompt budgets require trimming
- preserve role labels so the model can distinguish player vs DM narration

### Prompt assembly budget defaults

- recent transcript: target 1,500 tokens max
- memory: target 800 tokens max
- rules: target 1,200 tokens max
- lore: target 800 tokens max
- canonical state summary: target 700 tokens max

These are defaults, not hard guarantees, but the orchestrator should trim in this priority order:

1. lore
2. memory
3. rules
4. recent transcript
5. canonical state summary last

### Output contract rule

The model should always be instructed to return only the structured assistant turn payload:

- `narration`
- `proposed_actions`

No extra commentary, markdown fences, or alternate response shapes should be accepted.

## Config and Environment Contract

Implementation agents should treat the following settings as the default v1 contract:

- `APP_ENV`
- `DATABASE_PATH`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_TIMEOUT_SECONDS`
- `RULES_SOURCE_DIR`
- `RULES_JSONL_PATH`
- `LORE_SOURCE_DIR`
- `LORE_JSONL_PATH`
- `ENABLE_CHAT_DEBUG`
- `ENABLE_MEMORY_DEBUG`

Recommended defaults:

- SQLite path under the local project data directory
- rules and lore source paths under `data/`
- debug flags disabled by default

## Schema Authority Decision

For v1, use SQL-first schema authority.

Recommended rule:

- `backend/app/db/schema.sql` plus migrations is the authoritative schema definition
- ORM or model classes must reflect the SQL schema, not invent it independently

This reduces drift and makes hands-off implementation more deterministic for agents.

## Error Handling Contract

Use a single structured error shape across endpoints.

Recommended fields:

- `code`
- `message`
- `details`

Recommended common codes:

- `VALIDATION_ERROR`
- `NOT_FOUND`
- `CONFLICT`
- `LLM_UNAVAILABLE`
- `RETRIEVAL_ERROR`
- `INTERNAL_ERROR`

Recommended `/chat` fallback rule:

- if retrieval fails, continue with degraded context when safe and report a debug/error code internally
- if LLM generation fails, return an explicit error rather than partial fake success
- if narration is generated but action application fails, do not silently commit partial state; return a failure or degraded response with no applied mutations

## Seed and Bootstrap Flow

To avoid implementation ambiguity, v1 should define a clear bootstrap path:

1. initialize SQLite schema and migrations
2. import rules corpus from markdown to JSONL to `rules_documents`
3. optionally import lore corpus if present
4. create or load a sample campaign for manual QA
5. start backend and frontend

Recommended v1 rule:

- corpus imports run as explicit setup commands, not implicitly on every app startup
- the app may refuse retrieval features gracefully until required corpora are imported

## Test Matrix Contract

Implementation agents should treat the following as the minimum test target:

- dice unit tests
- action validation unit tests per allowed action type
- at least one relevant test per implemented rule-registry entry
- retrieval ranking and dedupe tests
- prompt assembly tests
- chat response parsing tests
- persistence transaction tests for turn plus event commits
- one `/chat` integration test with mocked LLM output
- one WebSocket chat streaming integration test
- rules import smoke test
- sample campaign bootstrap smoke test

## v1 Implementation Plan

## Phase 1: Project scaffolding

- [x] Create `backend/` FastAPI app structure
- [ ] Create `frontend/` React + TypeScript + Vite app structure
- [x] Create `data/` directories for campaigns, lore, and rules imports
- [x] Add environment/config handling
- [ ] Add local development scripts
- [x] Add basic logging
- [x] Add concrete backend module/file scaffold

## Phase 2: LLM integration

- [x] Create `llama.cpp` client service
- [x] Support configuration for model URL, model name, and timeout
- [x] Add health check endpoint for LLM availability
- [ ] Add streaming chat response support
- [x] Define prompt assembly pipeline
- [ ] Implement WebSocket chat streaming path
- [x] Enforce the structured assistant output contract

## Phase 3: Persistence layer

- [x] Create SQLite database initialization
- [x] Add schema for campaigns, sessions, turns, characters, party membership, inventory, quests, and summaries
- [x] Add migration strategy
- [x] Treat `schema.sql` plus migrations as schema authority
- [x] Add event log schema for important state changes
- [x] Add seed/import mechanism for starter rules and lore
- [x] Add import metadata/version tracking for rules and lore corpora
- [ ] Add backup/export strategy for campaign data

## Phase 4: Game systems

- [x] Implement dice rolling engine
- [x] Support basic roll types:
  - flat rolls
  - `d20`
  - advantage/disadvantage
  - modifiers
- [x] Implement canonical state updates for HP, inventory, quest state, and notes
- [x] Implement structured combat encounter state without map rendering

## Phase 5: Retrieval and memory

- [x] Implement turn transcript storage
- [ ] Implement scene summary generation
- [ ] Implement fact extraction pipeline
- [x] Implement memory retrieval interface
- [x] Add markdown-to-JSONL ingestion for rules corpus imports
- [x] Import processed rules chunks into `rules_documents`
- [x] Add SQLite FTS search for lore, rules, and transcripts
- [ ] Add retrieval ranking and prompt-budget caps for rules/lore/memory context
- [ ] Implement retrieval dedupe rules for parent/child chunks
- [ ] Optionally add semantic retrieval for scene summaries and memory facts only
- [ ] Inject memory context into prompts in a controlled way
- [x] Add rule traceability registry that maps deterministic rule behavior to chunk ids, code, and tests

## Phase 6: API surface

- [ ] Add endpoints for:
  - `/health`
  - `/chat`
  - `/campaigns`
  - `/sessions`
  - `/characters`
  - `/party`
  - `/dice/roll`
  - `/combat`
  - `/memory`
- [x] Add request/response schemas
- [ ] Add `/chat` streaming and non-streaming response modes
- [x] Add lightweight citations and optional debug metadata in `/chat` responses
- [x] Add error handling and validation
- [ ] Add WebSocket event schema for streamed chat turns

## Phase 7: Frontend v1

- [ ] Build chat interface
- [ ] Build streaming narration display
- [ ] Build party view for up to 4 players
- [ ] Build character sheet panel
- [ ] Build basic dice roller
- [ ] Build campaign/session selector
- [ ] Build simple debug views for memory and retrieved context
- [ ] Add responsive layout for desktop and tablet

## Phase 8: Testing and hardening

- [x] Unit test dice logic
- [x] Unit test state mutation rules
- [ ] Unit test retrieval ranking and prompt assembly
- [x] Integration test chat orchestration
- [ ] Integration test WebSocket chat streaming
- [x] Test persistence and reload behavior
- [ ] Test long-session memory behavior
- [ ] Add sample campaign for manual QA

## Current backend snapshot

The current implementation has completed a backend-first vertical slice for v1.

### Implemented now

- FastAPI backend scaffold with:
  - `/health`
  - `/chat`
  - `/campaigns`
  - `/sessions`
  - `/characters`
  - `/party`
  - `/dice/roll`
  - `/combat`
  - `/memory`
  - `/llm/health`
- SQLite canonical state with:
  - campaigns
  - sessions
  - turns
  - game events
  - characters
  - party members
  - inventory
  - quests
  - combat encounters
  - combatants
  - rules corpus imports and documents
- deterministic action application for:
  - damage and healing
  - conditions
  - spell slots
  - inventory
  - quests
  - location changes
  - combat start and end
  - combat turn advancement
  - weapon slot switching
  - attack roll resolution
  - temporary combat effects
- local `llama.cpp` integration with structured JSON completion
- retrieval of chunked SRD rules through `rules_service`
- explicit rejected-action reporting in `/chat`

### Combat implementation status

Current combat backend supports:

- active encounter tracking
- initiative order and turn advancement
- auto-ending encounters when one side remains conscious
- canonical weapon loadouts and shield-aware effective AC
- timed combat effects for:
  - `ac_bonus`
  - `attack_bonus`
  - `damage_bonus`
- current deterministic condition semantics for:
  - `poisoned`
  - `blinded`
  - `prone`

Known combat gaps still to implement or harden:

- long-range disadvantage based on actual distance/range bands
- stronger chunk-backed weapon/property enforcement instead of fallback assumptions
- concentration-style effect removal
- action-locking conditions such as `incapacitated`
- richer spell/item-specific combat effects
- battle map or positional range support

### Rule traceability status

The project now includes:

- `data/rules/traceability/rule_traceability_registry.json`
- `docs/RULE_TRACEABILITY.md`
- repo-level `AGENTS.md`

The registry already distinguishes:

- SRD-backed implemented rules
- partial rule implementations
- provisional app policies
- not-started rules

Next gameplay-rule work should update the registry alongside code and tests.

## v1 Definition of Done

v1 is done when:

- A user can create or load a campaign.
- A user can manage a party of up to 4 player characters.
- A user can chat with the DM-like LLM.
- The app persists characters, inventory, quests, and session history.
- The app can roll dice and display results.
- The app can show a character sheet.
- The app survives restart without losing campaign state.
- The memory system keeps the current session coherent over extended play.

## v1.5 TODO

- [ ] Add SQLite FTS tuning and better retrieval ranking
- [ ] Expand semantic retrieval beyond summaries/facts only if needed
- [ ] Add memory review tools for inspecting summaries and facts
- [ ] Add GM controls to approve or reject state changes
- [ ] Add richer character editing
- [ ] Add combat action shortcuts
- [ ] Add browser text-to-speech narration
- [ ] Add import pipeline for more structured lore/rules content
- [ ] Add campaign export/import package format

## v2 TODO

- [ ] Add optional speech-to-text input
- [ ] Add battle map module with token positions
- [ ] Add `map_service` backend module
- [ ] Add map-aware combat endpoints
- [ ] Add fog-of-war / visibility support if needed
- [ ] Add multiplayer session support
- [ ] Add initiative tracker UI
- [ ] Add NPC management tools
- [ ] Add save/load snapshots for encounters
- [ ] Add analytics/telemetry for prompt quality and retrieval quality
- [ ] Add pluggable model profiles for different local models

## Implementation Notes for Expandability

### Keep interfaces stable

Create backend service interfaces early, even if implementations are simple at first:

- `LLMClient`
- `MemoryStore`
- `RulesRepository`
- `GameStateRepository`
- `MapRepository` later

This avoids rewrites when adding ChromaDB, maps, or alternate frontends.

### Prefer event-style state updates

When possible, record meaningful game events in addition to current state:

- item gained
- damage taken
- quest advanced
- location changed

This helps with auditing, memory rebuilding, and future replay/history tools.

### Separate orchestration from rules

The LLM orchestration layer should not contain all business logic. Dice, combat, inventory, and memory rules should live in normal Python services.

### Keep prompt inputs structured

Pass prompt context as clearly separated sections:

- canonical state
- recent transcript
- retrieved memories
- relevant rules
- relevant lore

That structure will make later optimization much easier.

## Suggested First Build Order

1. Scaffold backend and frontend.
2. Build SQLite schema and repositories.
3. Implement dice engine and campaign/session CRUD.
4. Integrate `llama.cpp` chat calls.
5. Add transcript storage and scene summaries.
6. Build the frontend chat, dice, and character sheet UI.
7. Add structured combat state.
8. Add FTS-based retrieval.

## Risks to Watch

- Letting the LLM directly mutate game state
- Overbuilding retrieval before basic gameplay works
- Coupling combat logic to a future map UI
- Storing everything as unstructured JSON blobs
- Adding voice too early and slowing down core delivery

## Recommendation

Start with a text-first vertical slice:

- one campaign
- up to four player characters
- one rules corpus
- one session flow

Once that works end-to-end, expand the system feature-by-feature without changing the core architecture.
