CREATE TABLE settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL              -- JSON-encoded
);
CREATE TABLE presets (
  id            TEXT PRIMARY KEY,  -- uuid4 hex
  name          TEXT NOT NULL,
  label_type    TEXT NOT NULL,
  definition    TEXT NOT NULL,     -- LabelDefinition JSON
  tape_width_mm REAL,              -- nullable = any tape
  favorite      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE TABLE print_jobs (
  id             TEXT PRIMARY KEY,
  created_at     TEXT NOT NULL,
  status         TEXT NOT NULL,    -- queued|printing|done|failed|canceled
  error          TEXT,
  definition     TEXT NOT NULL,    -- full job JSON snapshot (labels + options) for reprint
  label_count    INTEGER NOT NULL,
  chain_mode     TEXT NOT NULL,    -- cut_each|chain_ff|strip_marks
  strategy       TEXT,             -- classic|e310bt (as used at print time; NULL for mock)
  tape_width_mm  REAL,             -- detected at print time
  media_raw_byte INTEGER,          -- raw status byte 11
  tape_used_mm   REAL,
  preview_png    BLOB              -- thumbnail of first label
);
CREATE INDEX idx_print_jobs_created ON print_jobs(created_at DESC);
CREATE TABLE media_observations (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  observed_at TEXT NOT NULL,
  raw_status  BLOB NOT NULL,       -- full 32 bytes
  media_byte  INTEGER NOT NULL,
  width_mm    INTEGER NOT NULL,
  user_note   TEXT
);
