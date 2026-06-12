PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  current_location_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  started_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_campaign_id
  ON sessions(campaign_id);

CREATE TABLE IF NOT EXISTS characters (
  id TEXT PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  class_name TEXT,
  level INTEGER NOT NULL DEFAULT 1,
  ancestry TEXT,
  background TEXT,
  current_hp INTEGER NOT NULL DEFAULT 1,
  max_hp INTEGER NOT NULL DEFAULT 1,
  armor_class INTEGER,
  speed INTEGER,
  proficiency_bonus INTEGER NOT NULL DEFAULT 2,
  ability_modifiers_json TEXT NOT NULL DEFAULT '{}',
  equipped_weapon_json TEXT NOT NULL DEFAULT '{}',
  weapon_loadout_json TEXT NOT NULL DEFAULT '{}',
  conditions_json TEXT NOT NULL DEFAULT '[]',
  spell_slots_json TEXT NOT NULL DEFAULT '{}',
  inventory_highlights_json TEXT NOT NULL DEFAULT '[]',
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_characters_campaign_id
  ON characters(campaign_id);

CREATE TABLE IF NOT EXISTS party_members (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  party_order INTEGER NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  added_at TEXT NOT NULL,
  UNIQUE(campaign_id, character_id),
  UNIQUE(campaign_id, party_order)
);

CREATE INDEX IF NOT EXISTS idx_party_members_campaign_id
  ON party_members(campaign_id);

CREATE TABLE IF NOT EXISTS inventory_items (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 1,
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(character_id, name)
);

CREATE INDEX IF NOT EXISTS idx_inventory_items_character_id
  ON inventory_items(character_id);

CREATE TABLE IF NOT EXISTS quests (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  summary TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_quests_campaign_id
  ON quests(campaign_id);

CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_index INTEGER NOT NULL,
  speaker_role TEXT NOT NULL,
  speaker_entity_id TEXT,
  user_text TEXT,
  assistant_text TEXT,
  proposed_actions_json TEXT NOT NULL DEFAULT '[]',
  retrieval_debug_json TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(session_id, turn_index)
);

CREATE TABLE IF NOT EXISTS game_events (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  event_index INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  actor_id TEXT,
  target_id TEXT,
  details_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(turn_id, event_index)
);

CREATE INDEX IF NOT EXISTS idx_game_events_event_type
  ON game_events(event_type);

CREATE TABLE IF NOT EXISTS combat_encounters (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'active',
  name TEXT,
  round_number INTEGER NOT NULL DEFAULT 1,
  turn_index INTEGER NOT NULL DEFAULT 0,
  winning_side TEXT,
  outcome_summary TEXT,
  started_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_combat_encounters_campaign_session
  ON combat_encounters(campaign_id, session_id);

CREATE TABLE IF NOT EXISTS combatants (
  id INTEGER PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES combat_encounters(id) ON DELETE CASCADE,
  source_character_id TEXT REFERENCES characters(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  initiative INTEGER,
  current_hp INTEGER,
  max_hp INTEGER,
  base_armor_class INTEGER,
  armor_class INTEGER,
  base_speed INTEGER,
  speed INTEGER,
  size TEXT NOT NULL DEFAULT 'Medium',
  saving_throw_bonuses_json TEXT NOT NULL DEFAULT '{}',
  conditions_json TEXT NOT NULL DEFAULT '[]',
  effects_json TEXT NOT NULL DEFAULT '[]',
  is_player INTEGER NOT NULL DEFAULT 0,
  party_order INTEGER,
  position_x INTEGER,
  position_y INTEGER,
  notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_combatants_encounter_id
  ON combatants(encounter_id);

CREATE TABLE IF NOT EXISTS scene_summaries (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
  summary_kind TEXT NOT NULL DEFAULT 'scene',
  summary_text TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_facts (
  id INTEGER PRIMARY KEY,
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
  fact_type TEXT NOT NULL,
  fact_text TEXT NOT NULL,
  tags_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corpus_imports (
  id INTEGER PRIMARY KEY,
  corpus_type TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_version TEXT,
  source_commit_hash TEXT,
  ruleset TEXT,
  chunker_version TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS rules_documents (
  id TEXT PRIMARY KEY,
  import_id INTEGER NOT NULL REFERENCES corpus_imports(id) ON DELETE CASCADE,
  doc_type TEXT NOT NULL,
  ruleset TEXT NOT NULL,
  source_file TEXT NOT NULL,
  chapter TEXT,
  section TEXT NOT NULL,
  subsection TEXT,
  part TEXT,
  heading_path_json TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  word_count INTEGER NOT NULL,
  text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rules_documents_import_id
  ON rules_documents(import_id);

CREATE INDEX IF NOT EXISTS idx_rules_documents_section
  ON rules_documents(section);

CREATE INDEX IF NOT EXISTS idx_rules_documents_subsection
  ON rules_documents(subsection);

CREATE VIRTUAL TABLE IF NOT EXISTS rules_documents_fts USING fts5(
  document_id UNINDEXED,
  section,
  subsection,
  text
);
