"""Tests for backend/scripts/symbols_pipeline/fetch_lucide.py's own helpers
-- the stroke-to-fill conversion machinery Track D1 added, on top of the
`fetch_material.py`/`fetch_phosphor.py` pattern `common.py`'s existing tests
(exercised indirectly via test_symbols.py, since common.py has no dedicated
test file of its own either) already cover.

Scope, deliberately: `_build_svg_document` (pure, fast, no external
process) gets real behavioral coverage below. `_stroke_to_fill_batch`
actually shells out to `npx oslllo-svg-fixer` -- exercising that for real
here would mean every test run depends on network access and a minute-plus
`npx` invocation, which is what the pipeline's own idempotent, re-runnable
`fetch_lucide.py` (run once, by hand, as part of this track -- see its
README) is for, not something this suite should re-pay on every run. What
IS worth covering here, with `subprocess.run` monkeypatched out, is the
CONTRACT around that subprocess call: source files get written before it
runs, a non-zero exit is surfaced as a clear `RuntimeError` (not a bare
`CalledProcessError`), and an id the tool silently drops (produces no output
file for) comes back absent from the result rather than raising -- exactly
what main()'s post-batch reconciliation (skip + log) depends on.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PIPELINE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "symbols_pipeline"
if str(_PIPELINE_DIR) not in sys.path:
    # fetch_lucide.py is a bare script (`import common` at its top, not a
    # package-relative import) meant to be run as
    # `uv run python scripts/symbols_pipeline/fetch_lucide.py` from backend/,
    # which puts its own directory on sys.path[0] automatically. pytest
    # collects from backend/tests/ instead, so that has to happen by hand
    # here -- same reason common.py inserts backend/src for `labelmaker`.
    sys.path.insert(0, str(_PIPELINE_DIR))

import common  # noqa: E402
import fetch_lucide  # noqa: E402

# --- _build_svg_document: the Lucide-specific (no transform, keeps ---------
# --- fill-rule="evenodd") variant of common.build_svg_document -------------


# A real traced-annulus `d` (a ring: outer square minus an inner square,
# opposite winding order) -- representative of what oslllo-svg-fixer's
# potrace step produces for a hole-shaped icon (e.g. "circle", "at-sign").
# With fill-rule="evenodd" this renders as a ring (inner square unpainted);
# with the default nonzero rule AND same-direction winding it would paint
# solid instead -- exactly the failure mode fill-rule="evenodd" guards
# against (see fetch_lucide.py's _build_svg_document docstring).
_RING_D = "M2 2 H22 V22 H2 Z M8 8 H16 V16 H8 Z"


def test_build_svg_document_shape():
    svg_text = fetch_lucide._build_svg_document("M0 0 L10 0 L10 10 L0 10 Z")
    assert svg_text == (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M0 0 L10 0 L10 10 L0 10 Z" fill-rule="evenodd"/></svg>'
    )


def test_build_svg_document_has_no_transform_attribute():
    # Unlike common.build_svg_document (Material/Phosphor need one to
    # reconcile a non-24-unit native coordinate system) -- Lucide's native
    # viewBox already IS 0 0 24 24, so a transform would be a no-op at best
    # and a maintenance footgun at worst.
    svg_text = fetch_lucide._build_svg_document("M0 0 L1 1")
    assert "transform" not in svg_text


def test_build_svg_document_passes_the_real_pipeline_shape_gate():
    svg_text = fetch_lucide._build_svg_document("M0 0 L10 0 L10 10 L0 10 Z")
    common.validate_shape("lucide_test", "lucide_test.svg", svg_text)  # no raise


def test_build_svg_document_passes_the_real_rasterize_gate():
    svg_text = fetch_lucide._build_svg_document("M4 4 H20 V20 H4 Z")
    assert common.rasterize_check(svg_text)


def test_build_svg_document_evenodd_renders_a_hole_not_a_solid_square():
    # The concrete case fill-rule="evenodd" exists for: a traced ring must
    # keep its untouched-background hole, not fill solid -- belt-and-suspenders
    # over rasterize_check's own "some ink AND some untouched background"
    # requirement (which a solid-filled square would already fail), checked
    # directly by pixel-sampling the inner square's center.
    svg_text = fetch_lucide._build_svg_document(_RING_D)
    assert common.rasterize_check(svg_text)

    from labelmaker.render.document import RenderedLabel, _svg_document
    from labelmaker.render.rasterize import rasterize

    # rasterize_check's own approach (see its docstring): wrap just the
    # inner content in a <g>, not the whole <svg>...</svg> document, since
    # nesting a full <svg> inside a <g> isn't valid. `svg_text` here is
    # `_build_svg_document`'s known exact shape, so building that inner
    # content directly (rather than re-parsing svg_text) keeps this test
    # independent of common.py's own inner-extraction regex.
    inner = f'<path d="{_RING_D}" fill-rule="evenodd"/>'
    label = RenderedLabel(svg=_svg_document(24, 24, f"<g>{inner}</g>"), width_px=24, height_px=24)
    img = rasterize(label)
    # Center of the inner (12,12) square (the hole) must be untouched white;
    # a corner of the outer ring (e.g. (5,5)) must be ink.
    assert img.getpixel((12, 12)) == 255, "evenodd hole filled in solid"
    assert img.getpixel((5, 5)) == 0, "ring itself didn't render"


# --- _stroke_to_fill_batch: the subprocess contract, mocked ----------------


def test_stroke_to_fill_batch_writes_source_files_before_invoking_npx(tmp_path, monkeypatch):
    seen_src_files: dict[str, str] = {}

    def fake_run(cmd, check, capture_output, text):
        src_dir = Path(cmd[cmd.index("-s") + 1])
        for f in src_dir.glob("*.svg"):
            seen_src_files[f.stem] = f.read_text()
        dst_dir = Path(cmd[cmd.index("-d") + 1])
        for icon_id in seen_src_files:
            (dst_dir / f"{icon_id}.svg").write_text("<svg>fixed</svg>")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(fetch_lucide.subprocess, "run", fake_run)

    result = fetch_lucide._stroke_to_fill_batch(
        {"wifi": "<svg>raw-wifi</svg>", "battery": "<svg>raw-battery</svg>"}, tmp_path
    )

    assert seen_src_files == {"wifi": "<svg>raw-wifi</svg>", "battery": "<svg>raw-battery</svg>"}
    assert result == {"wifi": "<svg>fixed</svg>", "battery": "<svg>fixed</svg>"}


def test_stroke_to_fill_batch_omits_ids_the_tool_silently_drops(tmp_path, monkeypatch):
    def fake_run(cmd, check, capture_output, text):
        dst_dir = Path(cmd[cmd.index("-d") + 1])
        # Simulate the tool producing output for only ONE of the two inputs.
        (dst_dir / "wifi.svg").write_text("<svg>fixed</svg>")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(fetch_lucide.subprocess, "run", fake_run)

    result = fetch_lucide._stroke_to_fill_batch(
        {"wifi": "<svg>raw-wifi</svg>", "ghost-icon": "<svg>raw-ghost</svg>"}, tmp_path
    )

    assert result == {"wifi": "<svg>fixed</svg>"}
    assert "ghost-icon" not in result


def test_stroke_to_fill_batch_raises_runtime_error_on_npx_failure(tmp_path, monkeypatch):
    def fake_run(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(1, cmd, output="", stderr="oslllo-svg-fixer blew up")

    monkeypatch.setattr(fetch_lucide.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="oslllo-svg-fixer blew up"):
        fetch_lucide._stroke_to_fill_batch({"wifi": "<svg>raw-wifi</svg>"}, tmp_path)
