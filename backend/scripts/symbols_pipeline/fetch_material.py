#!/usr/bin/env python
"""Fetch + normalize the curated Material Symbols subset
(material_ids.txt) into backend/assets/symbols/ as material_<id>.svg +
manifest v2 entries.

Usage (from backend/):

    uv run python scripts/symbols_pipeline/fetch_material.py

Downloads @material-symbols/svg-400@<PINNED_VERSION> straight from its npm
registry tarball (the same bytes `npm pack @material-symbols/svg-400` would
give you) to a temp dir, reads outlined/<id>.svg for every id in
material_ids.txt, keeps only the ones with exactly one <path> (Material's
outlined style is single-path for every icon this project sampled, but the
check -- and its skip-and-log behavior -- stays in place as the general
multi-path guard the brief asks for), and normalizes each survivor's
verbatim `d` into this project's viewBox="0 0 24 24" convention via the same
transform the original 60 use (see assets/symbols/LICENSES.md).

Idempotent: re-running replaces every material_* file + index.json entry
from scratch (see common.emit_source's docstring), so editing
material_ids.txt and re-running cleans up anything removed from the list.
"""

from __future__ import annotations

import re
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import common

PINNED_VERSION = "0.45.10"
TARBALL_URL = f"https://registry.npmjs.org/@material-symbols/svg-400/-/svg-400-{PINNED_VERSION}.tgz"
SOURCE = f"material-symbols@{PINNED_VERSION}"
LICENSE = "Apache-2.0"

IDS_FILE = Path(__file__).resolve().parent / "material_ids.txt"

_CATEGORY_HEADER_RE = re.compile(r"^#\s*category:\s*(\w+)\s*$", re.I)

# Material's own coordinate system (viewBox="0 -960 960 960") -> this
# project's 24x24 square: 24/960 == 0.025, and translating y by +960 first
# (transform lists apply right-to-left to a point) shifts [-960,0] to
# [0,960] before the scale brings it down to [0,24]. Identical to the
# recipe documented for the original 60 in assets/symbols/LICENSES.md.
TRANSFORM = "scale(0.025) translate(0,960)"


def parse_curated_ids(text: str) -> list[tuple[str, str]]:
    """Returns [(category, material_icon_id), ...] in file order, honoring
    '# category: X' section headers (case-insensitive); '#'-prefixed lines
    are comments (including '##' human-only sub-headings), blank lines are
    skipped.
    """
    out: list[tuple[str, str]] = []
    category: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = _CATEGORY_HEADER_RE.match(line)
            if m:
                category = m.group(1).lower()
            continue
        if category is None:
            raise ValueError(
                f"{IDS_FILE.name}: id {line!r} appears before any '# category:' header"
            )
        out.append((category, line))
    return out


def download_and_extract(url: str, dest: Path) -> Path:
    print(f"downloading {url}")
    tarball_path = dest / "package.tgz"
    urllib.request.urlretrieve(url, tarball_path)  # noqa: S310 -- pinned https npm registry URL
    with tarfile.open(tarball_path) as tf:
        tf.extractall(dest, filter="data")  # noqa: S202 -- trusted, pinned npm registry tarball
    return dest / "package"


def main() -> None:
    curated = parse_curated_ids(IDS_FILE.read_text())
    print(f"{len(curated)} curated ids in {IDS_FILE.name}")

    with tempfile.TemporaryDirectory(prefix="material-symbols-") as tmp:
        package_dir = download_and_extract(TARBALL_URL, Path(tmp))
        outlined_dir = package_dir / "outlined"

        candidates: list[common.Candidate] = []
        missing = 0
        multi_path_skips = 0
        for category, icon_id in curated:
            if category not in common.VALID_CATEGORIES:
                raise ValueError(f"{icon_id}: unknown category {category!r} in {IDS_FILE.name}")
            src_path = outlined_dir / f"{icon_id}.svg"
            if not src_path.is_file():
                print(f"  skip {icon_id}: not found in package at outlined/{icon_id}.svg")
                missing += 1
                continue
            d = common.extract_single_path_d(src_path.read_text())
            if d is None:
                print(f"  skip {icon_id}: source SVG is not a single <path>")
                multi_path_skips += 1
                continue
            tags = sorted({category, *icon_id.split("_")})
            candidates.append(common.Candidate(
                base_id=icon_id,
                name=common.humanize_id(icon_id),
                tags=tags,
                category=category,
                source=SOURCE,
                license=LICENSE,
                svg_text=common.build_svg_document(d, TRANSFORM),
            ))

        report = common.emit_source(prefix="material", candidates=candidates)

    print(report.summary())
    print(
        f"material: {len(curated)} curated, {missing} missing from package, "
        f"{multi_path_skips} multi-path skips, {len(report.accepted)} written, "
        f"{len(report.skipped)} failed the post-write rasterize gate"
    )


if __name__ == "__main__":
    main()
