# Symbols fetch/normalize pipeline

Generates most of `backend/assets/symbols/` (the label-icon catalog
`render/symbols.py` loads) from upstream icon sets. This directory is
dev/generation tooling only -- nothing under `backend/src/labelmaker/`
imports it, and it isn't part of the installed package.

## Why this exists

The original 60 icons (task 2.7) were hand-curated and hand-normalized
one-off. Commit 7 expands the catalog to ~860 curated icons across
Material + Phosphor, which needs actual tooling: a committed, reviewable
list of *which* icons came from where (the `*_ids.txt` files), and a
repeatable, idempotent way to re-fetch + re-normalize + re-validate them
(the `fetch_*.py` scripts + `common.py`).

## Layout

- `common.py` -- shared helpers every `fetch_*.py` uses: `Candidate`/
  `SourceReport` dataclasses, SVG-document building (`build_svg_document`),
  single-`<path>` extraction (`extract_single_path_d`), the pipeline-time
  quality gate (`validate_shape` + `rasterize_check` -- see below), manifest
  read/write (`load_index`/`save_index`), legacy-entry upgrade
  (`upgrade_legacy_entries`), and the per-source idempotent
  generate-and-merge step (`emit_source`).
- `material_ids.txt`, `phosphor_ids.txt` -- the committed, human-reviewable
  curated id lists (see "Curated id lists" below).
- `fetch_material.py`, `fetch_phosphor.py` -- one script per source; each
  reads its `*_ids.txt`, fetches/normalizes/validates, and calls
  `common.emit_source()` once at the end.

Currently two sources: Material Symbols (`material_*` ids, Apache-2.0) and
Phosphor's fill weight (`phosphor_*` ids, MIT). A third (or fourth) source
can slot in the same way -- see "Adding a source" below; `common.py` and the
manifest shape (`category` includes a still-unused `safety` bucket) were
built source-agnostic on purpose so this isn't a rewrite later.

## Running it

From `backend/`, with the project's normal dev deps (`uv sync`):

```sh
uv run python scripts/symbols_pipeline/fetch_material.py
uv run python scripts/symbols_pipeline/fetch_phosphor.py
```

Each script prints a summary (accepted / skipped-with-reason counts) and is
**idempotent**: re-running it deletes every `<prefix>_*.svg` file and every
`index.json` entry with that source's id prefix first, then regenerates from
the current `*_ids.txt` + the pinned upstream version. So:

- Editing an id list and re-running cleans up anything removed from it.
- Running both (in either order) is safe and byte-reproducible given the
  pinned versions: `emit_source()` sorts `index.json` by id before writing
  it, so nothing here depends on run order between sources -- material-then-
  phosphor and phosphor-then-material produce an identical committed file,
  not just an equivalent one.
- Re-running one script does NOT touch the other source's entries, or the
  original 60's bare-id entries (see "Backward compatibility" below).

## Curated id lists

Each `*_ids.txt` is one bare id per line, `#`-prefixed comments allowed,
grouped into sections by human-readable headers -- see each file's own
header comment for its exact format (Material's has machine-read
`# category: X` markers; Phosphor's is flat).

Selection was keyword/category-driven and then hand-trimmed to drop noise --
numbered percentage/badge variants, near-duplicate icons, brand-specific
icons, concepts already covered by the other source. Neither list claims to
be exhaustive; they're a curated, reviewable starting point. **To expand the
catalog later:** add ids to the relevant `*_ids.txt` and re-run that
source's script.

## Adding a source

1. Pick and pin an exact upstream version/commit (write it into the new
   script as a constant, the way `fetch_material.py`/`fetch_phosphor.py`
   each pin an npm version).
2. Decide the id namespace prefix (`material_`/`phosphor_` are taken) and
   pick which of the 7 manifest categories
   (`general|electrical|network|av|arrow|safety|misc`) your icons anchor to.
3. Write a `<source>_ids.txt` curated list, committed and reviewable.
4. Write `fetch_<source>.py`: parse the id list, fetch the source SVG per
   id, get it down to a single verbatim `d` path (skip + log multi-path
   ones -- `common.extract_single_path_d` handles the common single-`<path>`
   case; a source with multi-shape/colored source files would need real
   flattening instead, e.g. via a library like picosvg -- keep any such
   dependency script-only, per `common.py`'s own module docstring, never a
   runtime dependency), wrap it via `common.build_svg_document()` with
   whatever transform reconciles your source's native coordinate system with
   `viewBox="0 0 24 24"`, and build a list of `common.Candidate`.
5. Call `common.emit_source(prefix=..., candidates=...)` once.
6. Add a section to `assets/symbols/LICENSES.md` for the new source
   (upstream license text if required, exact version/commit, normalization
   notes).
7. Re-run `backend/tests/test_symbols.py` (category coverage, per-entry
   license non-empty, etc. all generalize automatically -- nothing there is
   hardcoded to two sources).

## The pipeline-time quality gate

Every candidate goes through the SAME two checks before it's written,
regardless of source:

1. **Shape validation** (`common.validate_shape`, which calls
   `render.symbols._validate_symbol_svg` directly -- not a reimplementation):
   exactly one `<path>`, `viewBox="0 0 24 24"`, no `style`/`font-family`
   attributes. This is the exact check the runtime loader re-applies on
   every load, so nothing accepted here can ever fail at render time for a
   shape reason.
2. **Rasterize gate** (`common.rasterize_check`): renders the candidate
   through the real resvg pipeline (the same `RenderedLabel`/`_svg_document`/
   `rasterize` call sequence `symbol_object()` and the test suite use) and
   requires BOTH some ink and some untouched background pixels. The second
   half matters: a normalization bug that keeps the wrong layer tends to
   produce a solid, fully-inked square, which a bare "not blank" check would
   wrongly accept.

A candidate that fails either check is skipped and logged, never
hand-patched. This is what the brief calls the "pipeline-time exhaustive
rasterize check" -- every file that ends up committed under
`assets/symbols/` already passed it, once, at generation time (as opposed to
`test_symbols.py`'s own rasterize test, which only re-checks a sampled
subset by default -- see that file's module docstring for why a subset is
enough there given the pipeline already swept everything).

## Backward compatibility

The original 60 icons keep their bare ids (`bolt`, `wifi_off`, ...) and
their `.svg` files are never touched by any `fetch_*.py` (each script only
ever deletes/rewrites files under its OWN `<prefix>_*.svg` glob). Their
`index.json` entries get upgraded in place to the manifest v2 shape
(`category`/`source`/`license` added, inferred from their existing tags --
see `common.upgrade_legacy_entries`) the first time any `fetch_*.py` runs,
but their `id`/`name`/`tags`/`path` values, and the files those `path`
values point at, are unchanged. Anything that saved a label definition
referencing a bare id keeps resolving.
