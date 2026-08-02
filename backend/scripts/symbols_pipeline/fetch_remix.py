#!/usr/bin/env python
"""Fetch + normalize the curated (full-set) Remix Icon fill-variant list
(remix_ids.txt) into backend/assets/symbols/ as remix_<id>.svg + manifest v2
entries.

Usage (from backend/):

    uv run python scripts/symbols_pipeline/fetch_remix.py

Downloads remixicon@<PINNED_VERSION> from its npm registry tarball to a temp
dir (same download_and_extract recipe as fetch_material.py/fetch_phosphor.py/
fetch_lucide.py/fetch_tabler.py: urllib against a pinned registry.npmjs.org
URL, no npm CLI), reading icons/<Category>/<id>-fill.svg for every
(category, id) pair in remix_ids.txt (parsed via
common.parse_curated_ids_with_category -- here `category` is already this
project's own manifest bucket, since remix_ids.txt's category assignment
comes straight from Remix's own folder layout, see that file's header).

Remix's fill icons are already-filled pictograms like Material/Phosphor
(not stroke-based like Lucide), and -- unlike Tabler -- every one sampled
across the full curated set is already a single <path>; fetch_remix.py still
routes every candidate through common.extract_fill_path (the shared
single-OR-multi-path extraction fetch_tabler.py/fetch_bootstrap.py/
fetch_fluent.py also use) rather than the older extract_single_path_d, both
for consistency and because it preserves a lone path's own `fill-rule`
(extract_single_path_d discards it) -- cheap insurance against a future
remixicon release ever shipping a multi-path or evenodd-holed fill icon.
Remix's native viewBox is already "0 0 24 24", so no coordinate transform is
needed -- common.build_svg_document's `transform` argument is omitted
(defaults to "").

Idempotent: re-running replaces every remix_* file + index.json entry from
scratch (see common.emit_source's docstring).
"""

from __future__ import annotations

import tarfile
import tempfile
import urllib.request
from pathlib import Path

import common

PINNED_VERSION = "4.9.1"
TARBALL_URL = f"https://registry.npmjs.org/remixicon/-/remixicon-{PINNED_VERSION}.tgz"
SOURCE = f"remixicon@{PINNED_VERSION}"
LICENSE = "Remix-Icon-1.0"

IDS_FILE = Path(__file__).resolve().parent / "remix_ids.txt"

# remix_ids.txt's own `# category:` sections are grouped by manifest bucket
# (network/av/arrow/misc -- see that file's header), which is NOT the same
# axis as "which of Remix's 19 icons/<Category>/ folders is this id under" --
# fetch_remix.py needs the LATTER to find the file on disk (multiple
# manifest buckets can and do draw from many different upstream folders,
# e.g. misc pulls from 16 different folders). So this maps every curated id
# to its source folder up front by scanning the tarball's own namelist
# once, rather than trying to re-derive "which folder" from the manifest
# category the id line already carries.


def download_and_extract(url: str, dest: Path) -> Path:
    print(f"downloading {url}")
    tarball_path = dest / "package.tgz"
    urllib.request.urlretrieve(url, tarball_path)  # noqa: S310 -- pinned https npm registry URL
    with tarfile.open(tarball_path) as tf:
        tf.extractall(dest, filter="data")  # noqa: S202 -- trusted, pinned npm registry tarball
    return dest / "package"


def _index_fill_files(icons_dir: Path) -> dict[str, Path]:
    """{icon_id: path} for every icons/<Category>/<id>-fill.svg under
    `icons_dir`, across all folders at once -- see the module-level comment
    above for why fetch_remix.py can't derive the folder from remix_ids.txt's
    own (manifest-bucket) category column.
    """
    by_id: dict[str, Path] = {}
    for path in icons_dir.glob("*/*-fill.svg"):
        icon_id = path.name[: -len("-fill.svg")]
        by_id[icon_id] = path
    return by_id


def main() -> None:
    curated = common.parse_curated_ids_with_category(IDS_FILE.read_text(), IDS_FILE.name)
    print(f"{len(curated)} curated ids in {IDS_FILE.name}")

    with tempfile.TemporaryDirectory(prefix="remixicon-") as tmp:
        package_dir = download_and_extract(TARBALL_URL, Path(tmp))
        icons_dir = package_dir / "icons"
        fill_files = _index_fill_files(icons_dir)

        candidates: list[common.Candidate] = []
        missing = 0
        unmergeable = 0
        for category, icon_id in curated:
            if category not in common.VALID_CATEGORIES:
                raise ValueError(f"{icon_id}: unknown category {category!r} in {IDS_FILE.name}")
            src_path = fill_files.get(icon_id)
            if src_path is None:
                print(
                    f"  skip {icon_id}: not found in package under any "
                    f"icons/*/{icon_id}-fill.svg"
                )
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

        report = common.emit_source(prefix="remix", candidates=candidates)

    print(report.summary())
    print(
        f"remix: {len(curated)} curated, {missing} missing from package, "
        f"{unmergeable} unmergeable (multi-fill/stroke/transform/non-path), "
        f"{len(report.accepted)} written, "
        f"{len(report.skipped)} failed the post-write rasterize gate"
    )


if __name__ == "__main__":
    main()
