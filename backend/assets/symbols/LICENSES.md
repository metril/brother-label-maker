# Bundled symbols

The label-icon catalog `backend/src/labelmaker/render/symbols.py` loads
(`index.json` + one `<id>.svg` per entry), from these sources:

| Source | Id prefix | License | Icons |
| --- | --- | --- | --- |
| Material Symbols (original 60, task 2.7) | none (bare id, e.g. `bolt`) | Apache-2.0 | 60 |
| Material Symbols (commit 7 pipeline) | `material_` | Apache-2.0 | see `index.json` |
| Phosphor (fill weight, commit 7 pipeline) | `phosphor_` | MIT | see `index.json` |
| Lucide (full set, Track D1 pipeline) | `lucide_` | ISC | see `index.json` |

All rows share one manifest, `index.json`: a flat JSON list of
`{id, name, tags, path, category, source, license}`. `category` is one of
`general|electrical|network|av|arrow|safety|misc` -- `safety` sat unused
(reserved for a possible future source, see `backend/scripts/symbols_pipeline/
README.md`'s "Adding a source" section) until the Lucide pipeline's
keyword-map (see `scripts/symbols_pipeline/lucide_ids.txt`'s header) started
populating it. `source`/`license` name which row above (and which pinned
version) an entry came from. The `backend/scripts/symbols_pipeline/`
directory holds the fetch/normalize tooling that produced everything except
the original 60 -- see its own `README.md` for how to run it and how to add
another source.

Every bundled file, regardless of source, is exactly one
`<svg viewBox="0 0 24 24">` wrapping exactly one `<path d="...">` -- no
`style`/`font-family`, no embedded raster data, no additional groups. Most
files also carry a `transform="..."` attribute on that `<path>` (Material's
and Phosphor's normalization step, reconciling their native coordinate
systems with this project's 24x24 square -- see each section below); Lucide's
files instead carry `fill-rule="evenodd"` and no `transform` at all, since its
native viewBox already IS `0 0 24 24` and its stroke-to-fill conversion step
needs the explicit fill-rule instead (see its own section below).
`render/symbols.py`'s `_validate_symbol_svg` enforces the single-`<path>`/
viewBox/no-style-or-font-family shape at load time; `backend/scripts/
symbols_pipeline/common.py`'s `validate_shape` + `rasterize_check` enforce
the same shape PLUS a real-resvg non-blank render at generation time, before
a file is ever committed (see that pipeline's own README for detail) -- so
every file under this directory has already passed both checks once.

## Material Symbols -- original 60 (task 2.7, bare ids)

- Source: [google/material-design-icons](https://github.com/google/material-design-icons),
  commit `528cb964c01fb2b09bc3b9208f82b6d8f8c1c1e2` (`master` at download
  time), path `symbols/web/<icon>/materialsymbolsoutlined/<icon>_24px.svg`.
- License: **Apache License 2.0** (upstream's own `LICENSE` file at that
  same commit:
  <https://github.com/google/material-design-icons/blob/528cb964c01fb2b09bc3b9208f82b6d8f8c1c1e2/LICENSE>).
  Apache-2.0 §4(a) requires that any redistribution "must give any other
  recipients ... a copy of this License" -- satisfied by
  [`LICENSE-APACHE-2.0.txt`](./LICENSE-APACHE-2.0.txt) in this SAME
  directory (the license text itself, fetched from that exact commit, byte
  for byte), NOT a top-level project license (this repository does not
  currently have one).
- Manifest `source` value: `material-design-icons@528cb964c0`.

### Normalization

The upstream SVGs use `viewBox="0 -960 960 960"` (Material Symbols' own
960-unit em-square convention, y-origin at the descender). This project's
`symbol_object()` assumes a plain `viewBox="0 0 24 24"` square. Rather than
algebraically rewriting each path's `d` coordinates (would need a real SVG
path-command parser -- fragile for marginal benefit), every file here keeps
its original (unmodified, verbatim) `d` string and wraps it in one
coordinate-system transform on the `<path>` element itself:

```
transform="scale(0.025) translate(0,960)"
```

`24 / 960 == 0.025`; translating y by `+960` first (SVG transform lists
apply right-to-left to a point) shifts the range from `[-960, 0]` to
`[0, 960]` before the scale brings it down to `[0, 24]`. Verified by hand
against both extreme corners (`(0,-960) -> (0,0)`, `(960,0) -> (24,24)`)
and by rendering every file through the real pipeline (see `test_symbols.py`).

## Material Symbols -- expanded set (commit 7 pipeline, `material_*` ids)

- Source: the [`@material-symbols/svg-400`](https://www.npmjs.com/package/@material-symbols/svg-400)
  npm package, version **0.45.10** (pinned in `fetch_material.py`), `outlined/<icon>.svg`
  (outlined style, weight 400, native `viewBox="0 -960 960 960"`).
- License: **Apache License 2.0** -- same upstream project as the original
  60, same [`LICENSE-APACHE-2.0.txt`](./LICENSE-APACHE-2.0.txt) covers it.
- Manifest `source` value: `material-symbols@0.45.10`.
- Normalization: identical recipe to the original 60 above (same upstream
  coordinate system) -- `transform="scale(0.025) translate(0,960)"`.
- Selection: `backend/scripts/symbols_pipeline/material_ids.txt`, a curated
  id list generated from label-maker-relevant keyword categories (hardware,
  networking, AV, electrical, home/appliances, tools, security, transport,
  communication, arrows, office, eco/nature, medical, hazard/alarm), then
  hand-trimmed to drop noise. All of Material's `outlined/` icons happen to
  be single-path already, so `fetch_material.py`'s multi-path skip never
  actually triggers against this upstream version -- it stays in place as
  the general guard the brief asks for.

## Phosphor -- fill weight (commit 7 pipeline, `phosphor_*` ids)

- Source: the [`@phosphor-icons/core`](https://www.npmjs.com/package/@phosphor-icons/core)
  npm package, version **2.1.1** (pinned in `fetch_phosphor.py`),
  `assets/fill/<icon>-fill.svg` (native `viewBox="0 0 256 256"`).
- License: **MIT**. Upstream's own `LICENSE` file at that version is
  reproduced byte-for-byte as
  [`LICENSE-MIT-phosphor.txt`](./LICENSE-MIT-phosphor.txt) in this directory.
- Manifest `source` value: `phosphor@2.1.1`.
- Normalization: Phosphor's viewBox already originates at `(0,0)` (unlike
  Material's `(0,-960)`), so no translate is needed -- just
  `transform="scale(0.09375)"` (`24 / 256 == 0.09375`).
- Selection: `backend/scripts/symbols_pipeline/phosphor_ids.txt` -- gap-filler
  object glyphs Material Symbols lacks (animals, clothing, camping/sports
  gear, simple medical objects, stationery), hand-picked to avoid duplicating
  a concept already covered by a Material Symbols selection. 1504 of
  Phosphor's 1512 fill icons are single-path; the remaining 8 would be
  skipped-and-logged by `fetch_phosphor.py` if any ever showed up in a future
  curated-list expansion, though none of the currently curated ids hit that.

## Lucide -- full set (Track D1 pipeline, `lucide_*` ids)

- Source: the [`lucide-static`](https://www.npmjs.com/package/lucide-static)
  npm package, version **1.28.0** (pinned in `fetch_lucide.py`),
  `icons/<icon>.svg` (native `viewBox="0 0 24 24"`, but stroke-based markup --
  see Normalization below).
- License: **ISC**. Upstream's own `LICENSE` file at that version is
  reproduced byte-for-byte as
  [`LICENSE-ISC-lucide.txt`](./LICENSE-ISC-lucide.txt) in this directory. That
  file also carries a second notice: a named subset of Lucide's icons are
  derived from the Feather project and additionally MIT-licensed (Cole Bemis)
  -- reproducing upstream's `LICENSE` file verbatim, exactly as for the other
  two sources, carries that notice along with it regardless of which specific
  bundled ids it names.
- Manifest `source` value: `lucide@1.28.0`.
- Normalization -- **stroke-to-fill outlining, a lossy transform** (unlike
  Material's/Phosphor's verbatim-`d` reuse above): Lucide's source SVGs are
  stroke-based line icons (`path`/`circle`/`rect`/`line`/`polyline` elements,
  `fill="none" stroke="currentColor" stroke-width="2"`), not the
  already-filled single-`<path>` pictograms Material and Phosphor ship, so
  there is no verbatim `d` to reuse. `fetch_lucide.py` converts every
  candidate through `npx oslllo-svg-fixer@6.0.1` (a rasterize-then-potrace
  stroke outliner, batch-run once over the whole curated set), which traces
  each stroked icon into a single filled `<path>` -- an approximation of the
  original stroked outline, not an exact vector operation, chosen (over
  algebraically offsetting each stroke) because it's the tool built for
  exactly this conversion and its output was verified, both automatically
  (every accepted file passes the same `validate_shape`/`rasterize_check`
  gate as every other source) and by hand (rendering a sample including
  hole-shaped icons like "circle" and "at-sign" through the real resvg
  pipeline and eyeballing the result), to reproduce the source icon faithfully
  at this catalog's 24x24 size. Because Lucide's native viewBox is already
  `0 0 24 24`, no `transform` is applied afterward (unlike Material's/
  Phosphor's coordinate-system reconciliation) -- the traced path keeps
  `fill-rule="evenodd"` instead (needed so a traced hole, e.g. "circle"'s
  ring or "at-sign"'s counter, renders as a hole rather than filling in
  solid; see `fetch_lucide.py`'s `_build_svg_document` docstring).
- Selection: `backend/scripts/symbols_pipeline/lucide_ids.txt` -- unlike
  Material's/Phosphor's hand-trimmed subsets, this is the FULL current
  Lucide set (1756 icons, every key in the npm package's own `tags.json`;
  deliberately excludes 251 old-name alias files the package also ships,
  each byte-identical geometry to an icon already listed under its current
  name). `category` is assigned by a deterministic keyword-map on each id's
  own name (the npm package ships no ready-made category metadata) --
  see that file's header comment for the exact rule, including the small
  hand-picked exception list layered on top of it.

## Adding another source

See `backend/scripts/symbols_pipeline/README.md`'s "Adding a source"
section for the mechanics. Add a section here (upstream license text if
required alongside a `LICENSE-<spdx-id>-<source>.txt` in this directory,
exact pinned version/commit, normalization notes, and a per-file license
table instead if a single license doesn't cover the whole source) following
the same shape as the sections above.

## Generation

Everything except the original 60 is generated by
`backend/scripts/symbols_pipeline/`'s `fetch_material.py`/`fetch_phosphor.py`/
`fetch_lucide.py` -- see that directory's own `README.md` for how to re-run
them (idempotent) or add another source. The original 60 were a one-off
hand-curated script (task 2.7) that predates this pipeline and isn't part of
it.
