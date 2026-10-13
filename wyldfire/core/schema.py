"""SQLite DDL schema for the disposable projection."""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS applied_events (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  actor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fires (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  description TEXT DEFAULT '',
  phase TEXT NOT NULL DEFAULT 'prototype',
  is_current INTEGER NOT NULL DEFAULT 0,
  core_loop TEXT DEFAULT '',
  toys_json TEXT NOT NULL DEFAULT '[]',
  scope_attested_at TEXT,
  scope_attest_note TEXT DEFAULT '',
  slice_bundles_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flames (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  description TEXT DEFAULT '',
  state TEXT NOT NULL DEFAULT 'sparked',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fire_flames (
  fire_id INTEGER NOT NULL REFERENCES fires(id) ON DELETE CASCADE,
  flame_id INTEGER NOT NULL REFERENCES flames(id) ON DELETE CASCADE,
  pinned_version INTEGER,
  added_at TEXT NOT NULL,
  PRIMARY KEY (fire_id, flame_id)
);

CREATE TABLE IF NOT EXISTS flame_versions (
  id INTEGER PRIMARY KEY,
  flame_id INTEGER NOT NULL REFERENCES flames(id) ON DELETE CASCADE,
  n INTEGER NOT NULL,
  notes TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (flame_id, n)
);

CREATE TABLE IF NOT EXISTS stokes (
  id INTEGER PRIMARY KEY,
  target_kind TEXT NOT NULL,
  target_id INTEGER NOT NULL,
  flame_version_id INTEGER REFERENCES flame_versions(id),
  tester TEXT NOT NULL DEFAULT 'dev',
  notes TEXT DEFAULT '',
  excluded INTEGER NOT NULL DEFAULT 0,
  exclude_reason TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  prompt TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'text',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stoke_metrics (
  stoke_id INTEGER NOT NULL REFERENCES stokes(id) ON DELETE CASCADE,
  metric_name TEXT NOT NULL,
  value_text TEXT NOT NULL,
  value_num REAL,
  PRIMARY KEY (stoke_id, metric_name)
);

CREATE TABLE IF NOT EXISTS testers (
  name TEXT PRIMARY KEY,
  note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS smoke (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  context_kind TEXT NOT NULL,
  context_ref TEXT NOT NULL DEFAULT '',
  severity INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  stoke_id INTEGER REFERENCES stokes(id),
  tags TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS smoke_transitions (
  id INTEGER PRIMARY KEY,
  smoke_id INTEGER NOT NULL REFERENCES smoke(id) ON DELETE CASCADE,
  to_status TEXT NOT NULL,
  note TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS embers (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  note TEXT DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'content',
  state TEXT NOT NULL DEFAULT 'banked',
  state_note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wick_bundles (
  id INTEGER PRIMARY KEY,
  fire_id INTEGER NOT NULL REFERENCES fires(id) ON DELETE CASCADE,
  parent_id INTEGER REFERENCES wick_bundles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  position INTEGER NOT NULL,
  cut INTEGER NOT NULL DEFAULT 0,
  cut_reason TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE (fire_id, parent_id, name)
);

CREATE TABLE IF NOT EXISTS wick_fuel (
  id INTEGER PRIMARY KEY,
  bundle_id INTEGER NOT NULL REFERENCES wick_bundles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  fuel_kind TEXT NOT NULL DEFAULT 'task',
  type_tag TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'queued',
  time_min INTEGER NOT NULL DEFAULT 0,
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS templates (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  definition_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gate_config (
  fire_id INTEGER PRIMARY KEY REFERENCES fires(id) ON DELETE CASCADE,
  min_stokes INTEGER NOT NULL DEFAULT 3,
  blocked_severity INTEGER NOT NULL DEFAULT 2
);

CREATE TABLE IF NOT EXISTS gate_verdicts (
  id INTEGER PRIMARY KEY,
  fire_id INTEGER NOT NULL REFERENCES fires(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  lap_no INTEGER,
  verdict TEXT NOT NULL,
  reasons_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gate_overrides (
  id INTEGER PRIMARY KEY,
  fire_id INTEGER NOT NULL REFERENCES fires(id) ON DELETE CASCADE,
  check_name TEXT NOT NULL,
  kind TEXT NOT NULL,
  ref_id INTEGER,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""
