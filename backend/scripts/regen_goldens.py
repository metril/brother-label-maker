#!/usr/bin/env python
"""Regenerate every golden PNG under tests/golden/render/, deterministically,
from the fixture definitions in tests/golden_fixtures.py.

Usage (from backend/):

    uv run python scripts/regen_goldens.py

This is the ONLY sanctioned way to update tests/golden/render/*.png. Do not
hand-edit or hand-copy a PNG into that directory -- always regenerate via
this script (so every golden is provably produced by the same pipeline
test_text_label.py's golden tests assert against) and VISUALLY INSPECT every
new/changed file before committing it.

Refuses to run if the installed resvg-py version doesn't match the one
pinned in pyproject.toml: resvg-py's own rasterization (font hinting,
anti-aliasing, exact pixel output) is part of what makes a golden's bytes
what they are, and this project's determinism/byte-lock guarantees
(test_golden_hello_render_twice_is_byte_identical, and every
test_golden_matches_committed_png case) explicitly assume a single pinned
version -- regenerating against a different one would silently bake in
whatever that other version's rasterizer happens to produce, defeating the
guardrail the golden tests exist to provide.

Idempotent: rendering is already byte-deterministic (same guarantee the
golden tests themselves rely on), so running this script twice in a row
regenerates byte-identical files both times -- the second run is a no-op
diff.
"""

from __future__ import annotations

import hashlib
import sys
import tomllib
from importlib import metadata
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_TESTS_DIR = _BACKEND_DIR / "tests"
_GOLDEN_DIR = _TESTS_DIR / "golden" / "render"

# Import tests/golden_fixtures.py directly -- tests/ has no __init__.py (see
# its own module docstring: it's meant to be sibling-importable exactly like
# this, the same way pytest itself imports it for test_text_label.py).
sys.path.insert(0, str(_TESTS_DIR))


def _pinned_resvg_py_version() -> str:
    pyproject = tomllib.loads((_BACKEND_DIR / "pyproject.toml").read_text())
    for dep in pyproject["project"]["dependencies"]:
        if dep.startswith("resvg-py=="):
            return dep.removeprefix("resvg-py==")
    raise RuntimeError("pyproject.toml has no pinned resvg-py==X.Y.Z dependency")


def _check_resvg_py_version() -> None:
    pinned = _pinned_resvg_py_version()
    installed = metadata.version("resvg-py")
    if installed != pinned:
        print(
            f"refusing to regenerate goldens: installed resvg-py=={installed} "
            f"!= pyproject.toml's pinned resvg-py=={pinned} -- goldens must always "
            "be cut against the exact pinned rasterizer version (see this script's "
            "module docstring). Install the pinned version first (`uv sync`).",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    _check_resvg_py_version()

    # Imported after sys.path is set up, and after the version check (no
    # point importing labelmaker.render's stack -- which does its own
    # resvg-py-backed rendering below -- against a version we've already
    # decided not to trust).
    import golden_fixtures

    from labelmaker.render.document import Tape
    from labelmaker.render.rasterize import preview_png, rasterize
    from labelmaker.render.types.text_label import TextLabelRenderer

    _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    renderer = TextLabelRenderer()
    for fixture in golden_fixtures.FIXTURES:
        tape = Tape(width_mm=fixture.tape_mm, family=fixture.tape_family).resolve()
        label = renderer.render(fixture.params, tape)
        img = rasterize(label)
        png_bytes = preview_png(img, scale=golden_fixtures.GOLDEN_SCALE)

        out_path = _GOLDEN_DIR / f"{fixture.name}.png"
        out_path.write_bytes(png_bytes)
        digest = hashlib.sha256(png_bytes).hexdigest()
        print(f"{out_path.relative_to(_BACKEND_DIR)}  sha256:{digest}")

    print(f"regenerated {len(golden_fixtures.FIXTURES)} golden(s) in {_GOLDEN_DIR}")
    print("INSPECT every new/changed golden visually before committing it.")


if __name__ == "__main__":
    main()
