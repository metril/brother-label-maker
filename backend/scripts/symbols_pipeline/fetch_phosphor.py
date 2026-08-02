#!/usr/bin/env python
"""Fetch + normalize the curated Phosphor "fill" weight subset
(phosphor_ids.txt) into backend/assets/symbols/ as phosphor_<id>.svg +
manifest v2 entries.

Usage (from backend/):

    uv run python scripts/symbols_pipeline/fetch_phosphor.py

Downloads @phosphor-icons/core@<PINNED_VERSION> from its npm registry
tarball to a temp dir, reads assets/fill/<id>-fill.svg for every id in
phosphor_ids.txt (parsed via common.parse_curated_ids_with_category, the
same '# category: <bucket>' directive fetch_material.py's list uses -- every
id currently sits under a single "# category: general" header, but the
mechanism is real and enforced: an unknown bucket raises, same as
fetch_material.py), keeps only the ones with exactly one <path> (~1504 of
Phosphor's 1512 fill icons are single-path; the rest are skipped and
logged), and normalizes each survivor's verbatim `d` into this project's
viewBox="0 0 24 24" convention.

Idempotent: re-running replaces every phosphor_* file + index.json entry
from scratch (see common.emit_source's docstring).
"""

from __future__ import annotations

import tarfile
import tempfile
import urllib.request
from pathlib import Path

import common

PINNED_VERSION = "2.1.1"
TARBALL_URL = f"https://registry.npmjs.org/@phosphor-icons/core/-/core-{PINNED_VERSION}.tgz"
SOURCE = f"phosphor@{PINNED_VERSION}"
LICENSE = "MIT"

IDS_FILE = Path(__file__).resolve().parent / "phosphor_ids.txt"

# Phosphor's own coordinate system (viewBox="0 0 256 256", origin already at
# 0,0 -- unlike Material's 0,-960) -> this project's 24x24 square.
# 24 / 256 == 0.09375; no translate needed.
TRANSFORM = "scale(0.09375)"


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

    with tempfile.TemporaryDirectory(prefix="phosphor-core-") as tmp:
        package_dir = download_and_extract(TARBALL_URL, Path(tmp))
        fill_dir = package_dir / "assets" / "fill"

        candidates: list[common.Candidate] = []
        missing = 0
        multi_path_skips = 0
        for category, icon_id in curated:
            if category not in common.VALID_CATEGORIES:
                raise ValueError(f"{icon_id}: unknown category {category!r} in {IDS_FILE.name}")
            src_path = fill_dir / f"{icon_id}-fill.svg"
            if not src_path.is_file():
                print(f"  skip {icon_id}: not found in package at assets/fill/{icon_id}-fill.svg")
                missing += 1
                continue
            d = common.extract_single_path_d(src_path.read_text())
            if d is None:
                print(f"  skip {icon_id}: source SVG is not a single <path>")
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
                svg_text=common.build_svg_document(d, TRANSFORM),
            ))

        report = common.emit_source(prefix="phosphor", candidates=candidates)

    print(report.summary())
    print(
        f"phosphor: {len(curated)} curated, {missing} missing from package, "
        f"{multi_path_skips} multi-path skips, {len(report.accepted)} written, "
        f"{len(report.skipped)} failed the post-write rasterize gate"
    )


if __name__ == "__main__":
    main()
