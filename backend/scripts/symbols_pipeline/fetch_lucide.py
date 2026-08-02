#!/usr/bin/env python
"""Fetch + stroke-to-fill-convert + normalize the curated (full-set) Lucide
icon list (lucide_ids.txt) into backend/assets/symbols/ as lucide_<id>.svg +
manifest v2 entries.

Usage (from backend/):

    uv run python scripts/symbols_pipeline/fetch_lucide.py

Downloads lucide-static@<PINNED_VERSION> from its npm registry tarball to a
temp dir (same download_and_extract recipe as fetch_material.py/
fetch_phosphor.py: urllib against a pinned registry.npmjs.org URL, no npm
CLI), reading icons/<id>.svg for every id in lucide_ids.txt (parsed via
common.parse_curated_ids_with_category, same '# category: <bucket>' directive
the other two sources' lists use).

Why this source needs a real conversion step, unlike Material/Phosphor
--------------------------------------------------------------------------
Material's and Phosphor's source SVGs are already-filled pictograms: each is
(or nearly always is) a single <path> with an implicit black fill, so
common.extract_single_path_d's "grab the one verbatim <path> d string" is
enough. Lucide's source SVGs are the opposite: STROKE-based line-icon
markup -- multiple <path>/<circle>/<rect>/<line>/<polyline> elements, all
`fill="none" stroke="currentColor" stroke-width="2"`, meant to be rendered as
outlines, not filled shapes. That's categorically incompatible with
extract_single_path_d (there's rarely exactly one <path> element to begin
with, and even a single stroked <path> isn't the filled shape this project's
symbol_object() needs -- rendering it with an implicit fill would either
paint nothing, given fill="none", or paint the wrong thing if fill were just
forced on).

So every candidate goes through an actual stroke->fill OUTLINING step before
normalization can even start: `npx oslllo-svg-fixer@STROKE_TOOL_VERSION`
(see _stroke_to_fill_batch's docstring), a rasterize-then-potrace tool built
for exactly this conversion. This is a genuinely LOSSY transform (a raster
trace approximating the stroked outline, not an exact vector operation) --
unlike Material/Phosphor's byte-verbatim `d` reuse, see LICENSES.md's Lucide
section for why that's called out explicitly there. Batch-run once (all
curated source SVGs in one `npx` invocation) rather than once per icon:
npx's own startup cost would otherwise dominate runtime across ~1750 icons.

After conversion, common.extract_single_path_d is reused as-is to pull the
outliner's own single-<path> output (skip + log if that ever produces
something else) -- same guard fetch_material.py/fetch_phosphor.py already
have, just applied to the outliner's output instead of the raw source file.

Normalization: unlike Material's 960-unit or Phosphor's 256-unit native
coordinate systems, Lucide's own viewBox is already "0 0 24 24" and
oslllo-svg-fixer's traced path comes back in that same space, so NO
`transform=` is needed -- _build_svg_document below is a local (not
common.py -- this attribute is specific to this source's tracing step, see
its own docstring) variant of common.build_svg_document that keeps the
outliner's `fill-rule="evenodd"` attribute instead (needed for icons whose
traced outline has a hole, e.g. "circle" or "at-sign" -- see that function's
docstring) and omits `transform` entirely.

Idempotent: re-running replaces every lucide_* file + index.json entry from
scratch (see common.emit_source's docstring).
"""

from __future__ import annotations

import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import common

PINNED_VERSION = "1.28.0"
TARBALL_URL = f"https://registry.npmjs.org/lucide-static/-/lucide-static-{PINNED_VERSION}.tgz"
SOURCE = f"lucide@{PINNED_VERSION}"
LICENSE = "ISC"

# The stroke->fill outlining tool + pinned version (see the module docstring
# for why this source needs one at all). Invoked via `npx`, never installed
# as a project dependency -- script-only, per common.py's own docstring
# about heavy converters staying out of runtime code.
STROKE_TOOL = "oslllo-svg-fixer"
STROKE_TOOL_VERSION = "6.0.1"

IDS_FILE = Path(__file__).resolve().parent / "lucide_ids.txt"


def download_and_extract(url: str, dest: Path) -> Path:
    print(f"downloading {url}")
    tarball_path = dest / "package.tgz"
    urllib.request.urlretrieve(url, tarball_path)  # noqa: S310 -- pinned https npm registry URL
    with tarfile.open(tarball_path) as tf:
        tf.extractall(dest, filter="data")  # noqa: S202 -- trusted, pinned npm registry tarball
    return dest / "package"


def _build_svg_document(d: str) -> str:
    """Lucide-specific variant of common.build_svg_document: no `transform`
    (Lucide's native viewBox already IS this project's "0 0 24 24" -- see
    the module docstring's Normalization section), and keeps a
    `fill-rule="evenodd"` attribute on the <path> rather than relying on the
    implicit default (nonzero).

    That attribute matters here specifically because of HOW the `d` this
    wraps was produced: oslllo-svg-fixer rasterizes the stroked icon and
    potraces the result back into vector contours, and any icon whose
    stroked outline traces to a ring/annulus (a hole in the middle -- e.g.
    "circle", "at-sign", "camera"'s lens, "donut") depends on the inner and
    outer contours being told apart by fill-rule rather than by trusting
    winding direction alone. oslllo-svg-fixer's own output always sets
    fill-rule="evenodd" on the path it emits; this function preserves that
    choice instead of silently dropping it when re-wrapping just the `d`
    (dropping it was checked, by hand, against a handful of hole-shaped
    icons during development -- see the spike notes in this track's report;
    it happened to render identically for the ones sampled, but there's no
    guarantee a rarer self-intersecting contour among the full ~1750 would,
    so the attribute stays rather than betting on it).
    """
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<path d="{d}" fill-rule="evenodd"/></svg>'
    )


def _stroke_to_fill_batch(svg_by_id: dict[str, str], tmp_root: Path) -> dict[str, str]:
    """Runs every {id: raw stroke-based svg_text} pair through ONE batched
    `npx oslllo-svg-fixer@STROKE_TOOL_VERSION` invocation (source dir ->
    destination dir -- oslllo-svg-fixer's own interface, built to process a
    whole directory of icons at once) rather than one subprocess per icon:
    npx resolves+caches the pinned tool on every invocation, and that
    overhead alone would dominate wall time across ~1750 separate calls.
    Measured during this track's spike: the full curated set converts in
    well under a minute this way.

    Returns {id: fixed_svg_text} for every id oslllo-svg-fixer actually wrote
    an output file for -- an id present in svg_by_id but absent from the
    result (it hasn't been observed to happen against this pinned version,
    but nothing guarantees it can't for some future icon) is main()'s job to
    detect and skip+log, the same "don't guess, skip and report" contract
    every other failure mode in this pipeline follows.

    Temp dirs live under `tmp_root` (a directory the caller owns and cleans
    up, per this script's own tempfile.TemporaryDirectory usage in main() --
    not a bare /tmp path), one subdirectory for the un-converted sources and
    one for oslllo-svg-fixer's output.
    """
    src_dir = tmp_root / "stroke_src"
    dst_dir = tmp_root / "stroke_fixed"
    src_dir.mkdir()
    dst_dir.mkdir()
    for icon_id, svg_text in svg_by_id.items():
        (src_dir / f"{icon_id}.svg").write_text(svg_text)

    print(
        f"converting {len(svg_by_id)} stroke-based icons to filled paths via "
        f"npx {STROKE_TOOL}@{STROKE_TOOL_VERSION} (this can take a minute or two)..."
    )
    try:
        subprocess.run(
            [
                "npx", "--yes", f"{STROKE_TOOL}@{STROKE_TOOL_VERSION}",
                "-s", str(src_dir), "-d", str(dst_dir), "--sp=false",
            ],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"npx {STROKE_TOOL}@{STROKE_TOOL_VERSION} failed (exit {exc.returncode}):\n"
            f"{exc.stderr}"
        ) from exc

    return {f.stem: f.read_text() for f in dst_dir.glob("*.svg")}


def main() -> None:
    curated = common.parse_curated_ids_with_category(IDS_FILE.read_text(), IDS_FILE.name)
    print(f"{len(curated)} curated ids in {IDS_FILE.name}")

    with tempfile.TemporaryDirectory(prefix="lucide-static-") as tmp:
        package_dir = download_and_extract(TARBALL_URL, Path(tmp))
        icons_dir = package_dir / "icons"

        raw_by_id: dict[str, str] = {}
        missing = 0
        for category, icon_id in curated:
            if category not in common.VALID_CATEGORIES:
                raise ValueError(f"{icon_id}: unknown category {category!r} in {IDS_FILE.name}")
            src_path = icons_dir / f"{icon_id}.svg"
            if not src_path.is_file():
                print(f"  skip {icon_id}: not found in package at icons/{icon_id}.svg")
                missing += 1
                continue
            raw_by_id[icon_id] = src_path.read_text()

        with tempfile.TemporaryDirectory(prefix="lucide-stroke-fix-") as fix_tmp:
            fixed_by_id = _stroke_to_fill_batch(raw_by_id, Path(fix_tmp))

            candidates: list[common.Candidate] = []
            conversion_failed = 0
            multi_path_skips = 0
            for category, icon_id in curated:
                if icon_id not in raw_by_id:
                    continue  # already counted+logged as `missing` above
                fixed_svg = fixed_by_id.get(icon_id)
                if fixed_svg is None:
                    print(f"  skip {icon_id}: stroke-to-fill conversion produced no output")
                    conversion_failed += 1
                    continue
                d = common.extract_single_path_d(fixed_svg)
                if d is None:
                    print(f"  skip {icon_id}: converted output is not a single <path>")
                    multi_path_skips += 1
                    continue
                base_id = icon_id.replace("-", "_")
                tags = sorted({category, *base_id.split("_")})
                candidates.append(common.Candidate(
                    base_id=base_id,
                    name=common.humanize_id(base_id),
                    tags=tags,
                    category=category,
                    source=SOURCE,
                    license=LICENSE,
                    svg_text=_build_svg_document(d),
                ))

        report = common.emit_source(prefix="lucide", candidates=candidates)

    print(report.summary())
    print(
        f"lucide: {len(curated)} curated, {missing} missing from package, "
        f"{conversion_failed} stroke-to-fill conversion failures, "
        f"{multi_path_skips} multi-path skips post-conversion, "
        f"{len(report.accepted)} written, "
        f"{len(report.skipped)} failed the post-write rasterize gate"
    )


if __name__ == "__main__":
    main()
