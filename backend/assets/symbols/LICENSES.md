# Bundled symbols

The label-icon catalog `backend/src/labelmaker/render/symbols.py` loads
(`index.json` + one `<id>.svg` per entry), from these sources:

| Source | Id prefix | License | Icons |
| --- | --- | --- | --- |
| Material Symbols (original 60, task 2.7) | none (bare id, e.g. `bolt`) | Apache-2.0 | 60 |
| Material Symbols (commit 7 pipeline) | `material_` | Apache-2.0 | see `index.json` |
| Phosphor (fill weight, commit 7 pipeline) | `phosphor_` | MIT | see `index.json` |
| Lucide (full set, Track D1 pipeline) | `lucide_` | ISC | see `index.json` |
| Tabler (filled style, full set, Track D2 pipeline) | `tabler_` | MIT | see `index.json` |
| Remix Icon (fill variants, full set, Track D2 pipeline) | `remix_` | Remix Icon License 1.0 (see its own section below -- NOT literally Apache-2.0 despite upstream's own package.json `license` field) | see `index.json` |
| Bootstrap Icons (fill variants, full set, Track D2 pipeline) | `bootstrap_` | MIT | see `index.json` |
| Fluent System Icons (24px filled, full set, Track D2 pipeline) | `fluent_` | MIT | see `index.json` |

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
needs the explicit fill-rule instead (see its own section below). The four
Track D2 sources (Tabler/Remix/Bootstrap/Fluent) follow Lucide's no-transform
convention where their own native viewBox already is `0 0 24 24` (all but
Bootstrap, which keeps a `transform="scale(1.5)"` for its native 16-unit
square) and, unlike Lucide, only carry `fill-rule="evenodd"` on the subset of
icons that actually need it (a source path declaring it, or a merged
multi-path candidate where any contributing path did -- see
`common.extract_fill_path`'s docstring) rather than unconditionally, since
their source SVGs are already-filled pictograms (not Lucide's stroke-traced
output, which always carries it).
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

## Tabler -- filled style, full set (Track D2 pipeline, `tabler_*` ids)

- Source: the [`@tabler/icons`](https://www.npmjs.com/package/@tabler/icons)
  npm package, version **3.46.0** (pinned in `fetch_tabler.py`),
  `icons/filled/<icon>.svg` (native `viewBox="0 0 24 24"`; the parallel
  `icons/outline/` style is NOT this project's concern).
- License: **MIT**. Upstream's own `LICENSE` file at that version is
  reproduced byte-for-byte as
  [`LICENSE-MIT-tabler.txt`](./LICENSE-MIT-tabler.txt) in this directory.
- Manifest `source` value: `tabler-icons@3.46.0`.
- Normalization: Tabler's native viewBox already IS `0 0 24 24`, so no
  `transform` is applied. Every filled icon ships an invisible, full-canvas
  `<path stroke="none" d="M0 0h24v24H0z" fill="none" />` bounding-box path
  ahead of the real glyph path(s), and roughly a fifth of the curated set has
  2+ real glyph paths beyond that -- both handled by
  `common.extract_fill_path` (see "Multi-path merging" below), which drops
  the invisible bounding-box path (paints nothing regardless) and
  concatenates the survivors' `d` strings into one merged `<path>`,
  preserving an explicit `fill-rule` (`evenodd` if any survivor declared
  it, else `nonzero`).
- Selection: `backend/scripts/symbols_pipeline/tabler_ids.txt` -- unlike
  Material's/Phosphor's hand-trimmed subsets, this is the FULL current set
  of Tabler's `icons/filled/` style (1054 icons). `category` starts from
  Tabler's own per-icon metadata (`icons.json`'s `category`/`tags` fields)
  rather than a from-scratch keyword-map, per a fixed priority rule (its
  own "Arrows" category -> `arrow`; its own "Brand" category -> `misc`;
  otherwise `common.classify_by_keyword()` over the icon's own id tokens
  only, deliberately NOT unioned with `icons.json`'s tags -- a spike found
  Tabler's tags carry a repeated per-top-level-category "flavor" suffix
  that isn't real per-icon signal and would otherwise misclassify ~150
  unrelated icons) plus a small hand-picked exception list on top -- see
  that file's header comment for the full rule and reasoning.

## Remix Icon -- fill variants, full set (Track D2 pipeline, `remix_*` ids)

- Source: the [`remixicon`](https://www.npmjs.com/package/remixicon) npm
  package, version **4.9.1** (pinned in `fetch_remix.py`),
  `icons/<Category>/<icon>-fill.svg` (native `viewBox="0 0 24 24"`; the
  parallel `-line.svg` outline variants are NOT this project's concern).
- License: **Remix Icon License 1.0** -- **not** literally Apache-2.0,
  despite upstream's own `package.json` `license` field claiming
  `"Apache-2.0"`. The actual file upstream ships as its `License` (verbatim
  in this directory as
  [`LICENSE-REMIX-ICON-1.0.txt`](./LICENSE-REMIX-ICON-1.0.txt)) is a bespoke
  document, "Remix Icon License v1.0" (Copyright Remix Design), not the
  Apache-2.0 template -- this discrepancy between the SPDX tag and the
  actual bundled text is called out explicitly here rather than silently
  trusting the SPDX tag and reproducing generic Apache-2.0 boilerplate that
  wouldn't match what upstream actually distributes. The real terms are
  broadly MIT-like (free commercial/non-commercial use, modification,
  bundling into a larger product) but carry restrictions Apache-2.0/MIT
  don't: no selling the icons as a standalone icon pack or competing icon
  library (§3.1-3.2), and no use of an icon (brand icons especially) as a
  logo/trademark/brand identity (§3.3-4). This project bundles Remix's
  icons as functional UI/label glyphs inside a label-printing application --
  squarely the license's own permitted "Icons as part of a larger work"
  carve-out (§2.3), not a standalone icon pack or a logo -- but anyone
  redistributing this catalog (or a fork of it) should read
  `LICENSE-REMIX-ICON-1.0.txt` in full rather than assume Apache-2.0/MIT
  norms apply.
- Manifest `source` value: `remixicon@4.9.1`. Manifest `license` value:
  `Remix-Icon-1.0` (a project-local short label, not an SPDX identifier --
  none exists for this license).
- Normalization: Remix's native viewBox already IS `0 0 24 24`, so no
  `transform` is applied. Every fill icon in the curated set happens to
  already be a single `<path>` (verified against the full set) -- routed
  through `common.extract_fill_path` anyway (see "Multi-path merging"
  below) rather than the older extract_single_path_d, both for consistency
  with the other three Track D2 sources and because it preserves a lone
  path's own `fill-rule` rather than silently discarding it.
- Selection: `backend/scripts/symbols_pipeline/remix_ids.txt` -- unlike
  Material's/Phosphor's hand-trimmed subsets, this is the FULL set of
  `-fill.svg` variants (1539 icons) across all 19 of Remix's own category
  folders. `category` is assigned by mapping those folder names directly
  onto this project's 7 buckets (a strictly better signal than guessing
  from tokens, since Remix ships it) -- see that file's header comment for
  the full folder -> bucket table.

## Bootstrap Icons -- fill variants, full set (Track D2 pipeline, `bootstrap_*` ids)

- Source: the [`bootstrap-icons`](https://www.npmjs.com/package/bootstrap-icons)
  npm package, version **1.13.1** (pinned in `fetch_bootstrap.py`),
  `icons/<icon>-fill.svg` (native `viewBox="0 0 16 16"`; the plain
  non-suffixed outline variants are NOT this project's concern).
- License: **MIT**. Upstream's own `LICENSE` file at that version is
  reproduced byte-for-byte as
  [`LICENSE-MIT-bootstrap.txt`](./LICENSE-MIT-bootstrap.txt) in this
  directory.
- Manifest `source` value: `bootstrap-icons@1.13.1`.
- Normalization: Bootstrap's own 16-unit square (origin already at `(0,0)`,
  unlike Material's `(0,-960)`) -> this project's 24x24 square:
  `transform="scale(1.5)"` (`24 / 16 == 1.5`, no translate needed). Most
  fill icons are single-`<path>`, but ~22% of the curated set has 2+ real
  `<path>` elements, and one (`circle-fill.svg`) is a bare `<circle>` with
  no `<path>` at all -- all handled by `common.extract_fill_path` (see
  "Multi-path merging" below), which merges same-fill multi-path
  candidates, preserves the `fill-rule="evenodd"` ~70 of Bootstrap's own
  single-path fill icons declare (needed for ring/cusp hole geometry, e.g.
  `heart-fill.svg`'s cardioid notch), and skips+logs `circle-fill.svg`
  (no `<path>` to extract at all).
- Selection: `backend/scripts/symbols_pipeline/bootstrap_ids.txt` -- unlike
  Material's/Phosphor's hand-trimmed subsets, this is the FULL current set
  of `-fill.svg` variants (670 icons; 669 actually accepted, see above).
  Bootstrap ships no per-icon category metadata -- categorized via
  `common.classify_by_keyword()` over each icon's own id tokens, plus a
  small hand-picked exception list (mainly Bootstrap's own
  `cloud-<weather>` family, e.g. `cloud-rain`/`cloud-snow`, which the bare
  "cloud" token can't distinguish from actual cloud-computing icons) -- see
  that file's header comment for the full rule.

## Fluent System Icons -- 24px filled, full set (Track D2 pipeline, `fluent_*` ids)

- Source: the [`@fluentui/svg-icons`](https://www.npmjs.com/package/@fluentui/svg-icons)
  npm package, version **1.1.334** (pinned in `fetch_fluent.py`),
  `icons/<icon>_24_filled.svg` (native `viewBox="0 0 24 24"`; every other
  size (`_16_`/`_20_`/`_28_`/`_32_`/`_48_`) and every `_regular` (outline)
  variant is NOT this project's concern, and neither are the ~146
  RTL-locale duplicate files under `icons/<locale>/` -- see
  `fluent_ids.txt`'s header for why those are excluded).
- License: **MIT**. Unlike the other three Track D2 sources, this npm
  package does not bundle its own `LICENSE` file -- reproduced byte-for-byte
  as [`LICENSE-MIT-fluent.txt`](./LICENSE-MIT-fluent.txt) in this directory,
  fetched from the upstream
  [microsoft/fluentui-system-icons](https://github.com/microsoft/fluentui-system-icons)
  repository's `LICENSE` file at git tag `1.1.334` (commit
  `f2f75a6e4814153d5c049c0f06e197731718326b`), the exact tag matching this
  pinned npm release.
- Manifest `source` value: `fluentui-svg-icons@1.1.334`.
- Normalization: Fluent's native viewBox already IS `0 0 24 24`, so no
  `transform` is applied. ~99% of the curated set is single-`<path>`, but a
  few dozen have 2+ real `<path>` elements -- handled by
  `common.extract_fill_path` (see "Multi-path merging" below) the same way
  as the other three Track D2 sources. A handful of Fluent's OWN multi-path
  icons (the `flag_pride_*` family, e.g. `flag_pride_philadelphia`) are
  genuinely multi-color (each stripe its own hex `fill`) and get
  skipped+logged by that function's differing-fill check rather than
  flattened into a single wrong-colored shape -- the only source among all
  four where that specific guard actually triggers in practice, see
  `fetch_fluent.py`'s own module docstring.
- Selection: `backend/scripts/symbols_pipeline/fluent_ids.txt` -- unlike
  Material's/Phosphor's hand-trimmed subsets, this is the FULL current set
  of canonical (non-locale) `_24_filled.svg` files (2490 icons; 2486
  actually accepted, the 4 `flag_pride_*` icons above being the only
  skips). Fluent ships no per-icon category metadata -- categorized via
  `common.classify_by_keyword()` over each icon's own id tokens, plus a
  small hand-picked exception list (Fluent's own "_lightning" suffix is a
  UI badge convention for "quick/AI-powered action" on an otherwise
  unrelated base icon, not a literal electricity icon) -- see that file's
  header comment for the full rule.

## Multi-path merging (Tabler/Remix/Bootstrap/Fluent, shared)

Unlike Material/Phosphor/Lucide (each reliably single-`<path>`, whether
verbatim or post-stroke-outlining), the four Track D2 sources' filled icons
are sometimes genuinely multiple `<path>` elements for one glyph (Tabler
especially: every filled icon carries an extra invisible bounding-box path,
and roughly a fifth also has 2+ real glyph paths). `common.extract_fill_path`
is the ONE shared implementation all four `fetch_*.py` scripts use for this
(source-agnostic, added alongside these four sources rather than duplicated
per-source): it drops any `fill="none"` path outright (paints nothing,
removing it never changes the rendered result), then either accepts the
survivors -- concatenating their `d` strings into one merged `<path>` and
carrying forward an explicit `fill-rule` (`evenodd` if ANY survivor declared
it, needed for a merged shape's hole geometry to survive the merge; else
`nonzero`) -- or rejects the whole candidate (skip+log, never silently
mangled) if it finds a genuinely multi-color icon (differing explicit `fill`
values across survivors), a per-path `stroke` or `transform` it can't safely
fold into a flat `d` concatenation, or a non-`<path>` drawable element
(`<circle>`/`<rect>`/etc.) it doesn't know how to flatten at all. See that
function's own docstring in `common.py` for the exact rule.

Every accepted merge was spot-checked by hand, rendering a sample of
hole-shaped icons (rings/donuts/badges -- e.g. Tabler's `lifebuoy` and
`chart-donut`, Remix's `record-circle` and `disc`, Bootstrap's `heart-fill`
and `disc-fill`, Fluent's `record` and `cellular_3g`) through the real resvg
pipeline: the automated ink+background rasterize gate can catch a fully
self-cancelled shape (extrema wouldn't show both ink and background) but
NOT a hole that self-cancels into solid fill while the rest of the icon
still shows normal ink/background variation -- only an eyeballed render
catches that. Every sampled icon rendered with its hole intact.

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
`fetch_lucide.py`/`fetch_tabler.py`/`fetch_remix.py`/`fetch_bootstrap.py`/
`fetch_fluent.py` -- see that directory's own `README.md` for how to re-run
them (idempotent) or add another source. The original 60 were a one-off
hand-curated script (task 2.7) that predates this pipeline and isn't part of
it.
