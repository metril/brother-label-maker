#!/usr/bin/env python
"""Fetch + normalize the curated (full-set) Fluent System Icons 24px filled
list (fluent_ids.txt) into backend/assets/symbols/ as fluent_<id>.svg +
manifest v2 entries.

Usage (from backend/):

    uv run python scripts/symbols_pipeline/fetch_fluent.py

Downloads @fluentui/svg-icons@<PINNED_VERSION> from its npm registry tarball
to a temp dir (same download_and_extract recipe as fetch_material.py/
fetch_phosphor.py/fetch_lucide.py/fetch_tabler.py/fetch_remix.py/
fetch_bootstrap.py: urllib against a pinned registry.npmjs.org URL, no npm
CLI), reading icons/<id>_24_filled.svg for every id in fluent_ids.txt
(parsed via common.parse_curated_ids_with_category, the same
'# category: <bucket>' directive every other source's list uses) --
DIRECTLY under icons/, not the locale (icons/ar/*, icons/he/*, ...)
subdirectory duplicates fluent_ids.txt's own header explains.

Fluent's filled icons are already-filled pictograms (not stroke-based like
Lucide) and mostly single-<path> (~99% of the curated set), but a few dozen
have 2+ real <path> elements -- every candidate goes through
common.extract_fill_path (the shared single-OR-multi-path extraction
fetch_tabler.py/fetch_remix.py/fetch_bootstrap.py also use). 4 of Fluent's
multi-path icons (the flag_pride_* family -- landing misc via
fluent_ids.txt's keyword-map, since none of their id tokens hit any of the
5 domain buckets) are genuinely MULTI-COLOR -- each stripe its own hex
`fill` -- and get correctly skipped+logged by extract_fill_path's
differing-fill check rather than flattened into a single wrong-colored
shape; this is the multi-color guard's one real (not just hypothetical)
trigger across all four Track D2 sources' curated sets.

Fluent's native viewBox is already "0 0 24 24", so no coordinate transform
is needed -- common.build_svg_document's `transform` argument is omitted
(defaults to "").

Idempotent: re-running replaces every fluent_* file + index.json entry from
scratch (see common.emit_source's docstring).
"""

from __future__ import annotations

import tarfile
import tempfile
import urllib.request
from pathlib import Path

import common

PINNED_VERSION = "1.1.334"
TARBALL_URL = f"https://registry.npmjs.org/@fluentui/svg-icons/-/svg-icons-{PINNED_VERSION}.tgz"
SOURCE = f"fluentui-svg-icons@{PINNED_VERSION}"
LICENSE = "MIT"

IDS_FILE = Path(__file__).resolve().parent / "fluent_ids.txt"


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

    with tempfile.TemporaryDirectory(prefix="fluentui-svg-icons-") as tmp:
        package_dir = download_and_extract(TARBALL_URL, Path(tmp))
        icons_dir = package_dir / "icons"

        candidates: list[common.Candidate] = []
        missing = 0
        unmergeable = 0
        for category, icon_id in curated:
            if category not in common.VALID_CATEGORIES:
                raise ValueError(f"{icon_id}: unknown category {category!r} in {IDS_FILE.name}")
            src_path = icons_dir / f"{icon_id}_24_filled.svg"
            if not src_path.is_file():
                print(f"  skip {icon_id}: not found in package at icons/{icon_id}_24_filled.svg")
                missing += 1
                continue
            merged = common.extract_fill_path(src_path.read_text())
            if merged is None:
                print(f"  skip {icon_id}: source SVG can't be reduced to one same-fill path")
                unmergeable += 1
                continue
            d, fill_rule = merged
            # Fluent ids are already underscore-separated natively (no
            # hyphens to convert, unlike Tabler/Remix/Bootstrap).
            base_id = icon_id
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

        report = common.emit_source(prefix="fluent", candidates=candidates)

    print(report.summary())
    print(
        f"fluent: {len(curated)} curated, {missing} missing from package, "
        f"{unmergeable} unmergeable (multi-fill/stroke/transform/non-path), "
        f"{len(report.accepted)} written, "
        f"{len(report.skipped)} failed the post-write rasterize gate"
    )


if __name__ == "__main__":
    main()
