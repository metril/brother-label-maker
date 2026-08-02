#!/usr/bin/env python
"""Fetch + normalize the curated (full-set) Tabler filled icon list
(tabler_ids.txt) into backend/assets/symbols/ as tabler_<id>.svg + manifest
v2 entries.

Usage (from backend/):

    uv run python scripts/symbols_pipeline/fetch_tabler.py

Downloads @tabler/icons@<PINNED_VERSION> from its npm registry tarball to a
temp dir (same download_and_extract recipe as fetch_material.py/
fetch_phosphor.py/fetch_lucide.py: urllib against a pinned registry.npmjs.org
URL, no npm CLI), reading icons/filled/<id>.svg for every id in
tabler_ids.txt (parsed via common.parse_curated_ids_with_category, the same
'# category: <bucket>' directive the other sources' lists use).

Unlike Material/Phosphor, Tabler's filled icons are NOT reliably
single-<path>: every filled/*.svg ships an invisible, full-canvas
`<path stroke="none" d="M0 0h24v24H0z" fill="none" />` bounding-box path
ahead of the real glyph path(s), and roughly a fifth of the curated set has
2+ real glyph paths beyond that (see common.extract_fill_path's own
docstring for the general multi-path merge this shares with
fetch_remix.py/fetch_bootstrap.py/fetch_fluent.py -- all four Track D2
sources are already-filled pictograms like Material/Phosphor, just not
reliably single-path the way those two happen to be). Tabler's native
viewBox is already "0 0 24 24", so no coordinate transform is needed --
common.build_svg_document's `transform` argument is omitted (defaults to "").

Idempotent: re-running replaces every tabler_* file + index.json entry from
scratch (see common.emit_source's docstring).
"""

from __future__ import annotations

import tarfile
import tempfile
import urllib.request
from pathlib import Path

import common

PINNED_VERSION = "3.46.0"
TARBALL_URL = f"https://registry.npmjs.org/@tabler/icons/-/icons-{PINNED_VERSION}.tgz"
SOURCE = f"tabler-icons@{PINNED_VERSION}"
LICENSE = "MIT"

IDS_FILE = Path(__file__).resolve().parent / "tabler_ids.txt"


def download_and_extract(url: str, dest: Path) -> Path:
    print(f"downloading {url}")
    tarball_path = dest / "package.tgz"
    urllib.request.urlretrieve(url, tarball_path)  # noqa: S310 -- pinned https npm registry URL
    with tarfile.open(tarball_path) as tf:
        tf.extractall(dest, filter="data")  # noqa: S202 -- trusted, pinned npm registry tarball
    return dest / "package"


def main() -> None:
    curated = common.parse_curated_ids_with_category(IDS_FILE.read_text(), IDS_FILE.name)
    print(f"{len(curated)} curated ids in {IDS_FILE.name}")

    with tempfile.TemporaryDirectory(prefix="tabler-icons-") as tmp:
        package_dir = download_and_extract(TARBALL_URL, Path(tmp))
        filled_dir = package_dir / "icons" / "filled"

        candidates: list[common.Candidate] = []
        missing = 0
        unmergeable = 0
        for category, icon_id in curated:
            if category not in common.VALID_CATEGORIES:
                raise ValueError(f"{icon_id}: unknown category {category!r} in {IDS_FILE.name}")
            src_path = filled_dir / f"{icon_id}.svg"
            if not src_path.is_file():
                print(f"  skip {icon_id}: not found in package at icons/filled/{icon_id}.svg")
                missing += 1
                continue
            merged = common.extract_fill_path(src_path.read_text())
            if merged is None:
                print(f"  skip {icon_id}: source SVG can't be reduced to one same-fill path")
                unmergeable += 1
                continue
            d, fill_rule = merged
            base_id = icon_id.replace("-", "_")
            tags = sorted({category, *base_id.split("_")})
            candidates.append(common.Candidate(
                base_id=base_id,
                name=common.humanize_id(base_id),
                tags=tags,
                category=category,
                source=SOURCE,
                license=LICENSE,
                svg_text=common.build_svg_document(d, fill_rule=fill_rule),
            ))

        report = common.emit_source(prefix="tabler", candidates=candidates)

    print(report.summary())
    print(
        f"tabler: {len(curated)} curated, {missing} missing from package, "
        f"{unmergeable} unmergeable (multi-fill/stroke/transform/non-path), "
        f"{len(report.accepted)} written, "
        f"{len(report.skipped)} failed the post-write rasterize gate"
    )


if __name__ == "__main__":
    main()
