-- Feed & cut trigger (docs/superpowers/specs/2026-08-04-feed-cut-trigger-design.md):
-- print_jobs gains `kind` so a queued feed-cut trigger job (no labels, no
-- fake definition) is distinguishable from a real print job -- surfaced on
-- job status/history payloads as "kind": "print" | "feed_cut".
--
-- Additive, defaulted: every row that exists before this migration runs is
-- a real print job, so DEFAULT 'print' backfills all of them correctly
-- with no separate data migration/backfill statement needed.
ALTER TABLE print_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'print';
