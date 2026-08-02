"""Track C1: tests for POST /api/print/preview -- the composited chained-job
preview endpoint (jobs/chained_preview.build_chained_preview).

Follows test_api_print.py/test_api_print_task29.py's own conventions
(_text_label helper, byte/pixel-parity against an in-test render_definition/
estimate() call using the SAME pipeline the endpoint itself uses) --
`total_mm` parity is asserted against render.estimate.estimate() directly
(the ONE authoritative tape-usage model, never re-derived by this endpoint),
never a hand-computed golden number.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from labelmaker.driver.geometry import MIN_FEED_MM, MediaFamily, dots_to_mm, find_tape, mm_to_dots
from labelmaker.driver.job import JobOptions
from labelmaker.render import render_definition
from labelmaker.render.document import LabelDefinition
from labelmaker.render.estimate import estimate

_TAPE_24MM_TZE = find_tape(24, MediaFamily.TZE)
assert _TAPE_24MM_TZE is not None

# gap(4) + dashes(4) + gap(4) -- see jobs/chained_preview.py's
# _CUT_MARK_GAP_DOTS/_CUT_MARK_WIDTH_DOTS (hand-duplicated from
# driver.job.JobOptions' own cut_mark_gap/cut_mark_width defaults, see the
# drift-guard test below).
_CUT_MARK_GAP_DOTS = 4
_CUT_MARK_WIDTH_DOTS = 4
_MARK_BLOCK_DOTS = 2 * _CUT_MARK_GAP_DOTS + _CUT_MARK_WIDTH_DOTS


def _text_label(text: str, length_mm: float | None = None) -> dict:
    params: dict = {"lines": [text]}
    if length_mm is not None:
        params["length_mm"] = length_mm
    return {"type": "text", "tape": {"width_mm": 24, "family": "tze"}, "params": params}


def _rendered_width_px(label: dict) -> int:
    return render_definition(LabelDefinition.model_validate(label)).width_px


def _decode_png(png_b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(png_b64)))


# --- 0. Drift guard: this module's hand-duplicated cut-mark constants must -
# stay in lockstep with driver.job.JobOptions' own cut_mark_gap/cut_mark_width
# defaults -- see jobs/chained_preview.py's module docstring and
# render/estimate.py's own equivalent guard in test_estimate.py.


def test_chained_preview_cut_mark_dimensions_match_job_options_defaults():
    defaults = JobOptions()
    assert defaults.cut_mark_gap == _CUT_MARK_GAP_DOTS
    assert defaults.cut_mark_width == _CUT_MARK_WIDTH_DOTS


# --- (a) DRIFT GUARD: endpoint total_mm == estimate() total_mm exactly, ----
# across a matrix of label counts/lengths x all 3 chain modes x 2 margins.


_LENGTH_MATRIX: list[list[float]] = [
    [10.0],
    [15.0, 30.0],
    [8.0, 20.0, 45.0],
]
_CHAIN_MODES = ["cut_each", "chain_ff", "strip_marks"]
_MARGINS = [2.0, 5.0]


@pytest.mark.parametrize("lengths_mm", _LENGTH_MATRIX)
@pytest.mark.parametrize("chain_mode", _CHAIN_MODES)
@pytest.mark.parametrize("margin_mm", _MARGINS)
async def test_preview_total_mm_matches_estimate_exactly(client, lengths_mm, chain_mode, margin_mm):
    labels = [_text_label(f"L{i}", length_mm=length) for i, length in enumerate(lengths_mm)]

    resp = await client.post(
        "/api/print/preview",
        json={"labels": labels, "options": {"chain_mode": chain_mode, "margin_mm": margin_mm}},
    )
    assert resp.status_code == 200
    body = resp.json()

    actual_lengths_mm = [dots_to_mm(_rendered_width_px(label)) for label in labels]
    expected = estimate(actual_lengths_mm, chain_mode=chain_mode, margin_mm=margin_mm)

    assert body["chain_mode"] == chain_mode
    assert body["total_mm"] == pytest.approx(expected.total_mm)
    assert body["content_mm"] == pytest.approx(expected.content_mm)
    assert body["feed_overhead_mm"] == pytest.approx(expected.feed_overhead_mm)
    assert body["per_label_mm"] == pytest.approx(expected.per_label_mm)
    assert body["notes"] == expected.notes


# --- (b) composite pixel width per mode -------------------------------------


@pytest.mark.parametrize("chain_mode", _CHAIN_MODES)
async def test_preview_composite_pixel_width_per_mode(client, chain_mode):
    labels = [
        _text_label("ONE", length_mm=15.0),
        _text_label("TWO", length_mm=30.0),
        _text_label("THREE", length_mm=10.0),
    ]
    widths_px = [_rendered_width_px(label) for label in labels]

    if chain_mode == "cut_each":
        gap_dots = mm_to_dots(MIN_FEED_MM)
    elif chain_mode == "strip_marks":
        gap_dots = _MARK_BLOCK_DOTS
    else:  # chain_ff
        gap_dots = 0
    expected_width = sum(widths_px) + gap_dots * (len(labels) - 1)

    resp = await client.post(
        "/api/print/preview",
        json={"labels": labels, "options": {"chain_mode": chain_mode}, "scale": 1},
    )
    assert resp.status_code == 200
    body = resp.json()

    img = _decode_png(body["png_b64"])
    assert img.width == expected_width
    assert img.height == _TAPE_24MM_TZE.print_dots


async def test_preview_scale_multiplies_composite_pixel_dimensions(client):
    labels = [_text_label("ONE", length_mm=15.0), _text_label("TWO", length_mm=30.0)]
    widths_px = [_rendered_width_px(label) for label in labels]
    expected_width_scale1 = sum(widths_px)  # chain_ff: butted, zero gap

    resp = await client.post(
        "/api/print/preview",
        json={"labels": labels, "options": {"chain_mode": "chain_ff"}, "scale": 3},
    )
    assert resp.status_code == 200
    img = _decode_png(resp.json()["png_b64"])
    assert img.width == expected_width_scale1 * 3
    assert img.height == _TAPE_24MM_TZE.print_dots * 3


# --- (c) strip_marks dash cadence: sample the mark columns' pixels ---------


async def test_preview_strip_marks_dash_cadence_pixel_pattern(client):
    labels = [_text_label("ONE", length_mm=15.0), _text_label("TWO", length_mm=30.0)]
    width0_px = _rendered_width_px(labels[0])

    resp = await client.post(
        "/api/print/preview",
        json={"labels": labels, "options": {"chain_mode": "strip_marks"}, "scale": 1},
    )
    assert resp.status_code == 200
    img = _decode_png(resp.json()["png_b64"]).convert("1")
    height = img.height
    pixels = img.load()

    # The mark block sits right after label 0: gap(4) blank, then 4 dash
    # columns, then gap(4) blank -- see jobs/chained_preview.py's _composite.
    dash_start_x = width0_px + _CUT_MARK_GAP_DOTS

    for dx in range(_CUT_MARK_WIDTH_DOTS):
        x = dash_start_x + dx
        for y in range(height):
            expect_black = (y // 4) % 2 == 0
            is_black = pixels[x, y] == 0
            assert is_black == expect_black, f"x={x} y={y} expected black={expect_black}"

    # The blank gap columns immediately flanking the dashes are entirely white.
    for x in (width0_px, dash_start_x + _CUT_MARK_WIDTH_DOTS):
        for y in range(height):
            assert pixels[x, y] != 0, f"expected blank gap column white at x={x} y={y}"


# --- (d) tape-mismatch 422, matching the existing /print message -----------


async def test_preview_rejects_mixed_tapes_with_422_matching_print_message(client):
    labels = [
        _text_label("ONE"),
        {**_text_label("TWO"), "tape": {"width_mm": 12, "family": "tze"}},
    ]
    print_resp = await client.post("/api/print", json={"labels": labels})
    assert print_resp.status_code == 422

    preview_resp = await client.post("/api/print/preview", json={"labels": labels})
    assert preview_resp.status_code == 422
    assert preview_resp.json()["detail"] == print_resp.json()["detail"]
    assert preview_resp.json()["detail"] == "all labels in a print job must share the same tape"


# --- (e) single label -> 1 segment, no gaps ---------------------------------


async def test_preview_single_label_one_segment_no_gaps(client):
    label = _text_label("SOLO", length_mm=20.0)
    width_px = _rendered_width_px(label)

    resp = await client.post(
        "/api/print/preview",
        json={"labels": [label], "options": {"chain_mode": "strip_marks"}, "scale": 1},
    )
    assert resp.status_code == 200
    body = resp.json()

    img = _decode_png(body["png_b64"])
    assert img.width == width_px  # no gaps/marks possible with a single label

    assert len(body["segments"]) == 1
    segment = body["segments"][0]
    assert segment["index"] == 0
    assert segment["start_mm"] == pytest.approx(0.0)
    assert segment["end_mm"] == pytest.approx(dots_to_mm(width_px))
    assert segment["length_mm"] == pytest.approx(dots_to_mm(width_px))


# --- (f) serialization + multi-label 422 parity with /print ----------------


def _serial_template(text: str = "Port {seq}") -> dict:
    return {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": [text]},
    }


async def test_preview_serialization_with_multi_label_422_parity_with_print(client):
    body = {
        "labels": [_text_label("ONE"), _text_label("TWO")],
        "serialization": {"kind": "list", "values": ["A", "B"]},
    }

    print_resp = await client.post("/api/print", json=body)
    assert print_resp.status_code == 422

    preview_resp = await client.post("/api/print/preview", json=body)
    assert preview_resp.status_code == 422
    assert preview_resp.json()["detail"] == print_resp.json()["detail"]


async def test_preview_serialization_expands_and_matches_estimate(client):
    serialization = {"kind": "list", "values": ["A", "B", "C"], "copies_per_value": 1}
    body = {
        "labels": [_serial_template()],
        "serialization": serialization,
        "options": {"chain_mode": "chain_ff", "margin_mm": 2.0},
    }

    resp = await client.post("/api/print/preview", json=body)
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["segments"]) == 3

    from labelmaker.render.serialize import Sequence, expand_definition

    seq = Sequence.model_validate(serialization)
    bound = expand_definition(_serial_template(), seq)
    lengths_mm = [
        dots_to_mm(render_definition(LabelDefinition.model_validate(d)).width_px) for d in bound
    ]
    expected = estimate(lengths_mm, chain_mode="chain_ff", margin_mm=2.0)
    assert payload["total_mm"] == pytest.approx(expected.total_mm)


# --- (g) segments monotonic; last end == content+gaps length ---------------


@pytest.mark.parametrize("chain_mode", _CHAIN_MODES)
async def test_preview_segments_monotonic_and_last_end_matches_composite_length(client, chain_mode):
    labels = [
        _text_label("ONE", length_mm=12.0),
        _text_label("TWO", length_mm=40.0),
        _text_label("THREE", length_mm=18.0),
    ]
    widths_px = [_rendered_width_px(label) for label in labels]

    if chain_mode == "cut_each":
        gap_dots = mm_to_dots(MIN_FEED_MM)
    elif chain_mode == "strip_marks":
        gap_dots = _MARK_BLOCK_DOTS
    else:
        gap_dots = 0
    expected_total_width_px = sum(widths_px) + gap_dots * (len(labels) - 1)

    resp = await client.post(
        "/api/print/preview",
        json={"labels": labels, "options": {"chain_mode": chain_mode}},
    )
    assert resp.status_code == 200
    segments = resp.json()["segments"]

    assert len(segments) == 3
    values = [v for s in segments for v in (s["start_mm"], s["end_mm"])]
    assert values == sorted(values)  # monotonically non-decreasing throughout
    for s in segments:
        assert s["start_mm"] <= s["end_mm"]

    assert segments[-1]["end_mm"] == pytest.approx(dots_to_mm(expected_total_width_px))


# --- (h) H1: pixel-budget guard -- a legal-but-huge request 422s instead --
# of building the composite -- docs/code-review-2026-08.md.


async def test_preview_rejects_legal_but_huge_serialized_request_with_422_budget_cap(client):
    """Every individual figure here is within its own documented cap --
    length_mm=1000 is exactly tape.max_length_mm for 24mm TZe
    (driver/geometry.py), scale=8 is the field's own `le=8` ceiling, and 2
    serialized labels is far under both the 100-label direct cap and the
    1000-label serialized cap -- but the composite they'd multiply out to
    (2 x 7086 dots wide x 128 dots tall, upscaled 8x) is ~117.5 MP, well
    past MAX_PREVIEW_PIXELS (40 MP). This must 422 BEFORE any rasterize/
    Image.new() call, not exhaust memory or hang building an unusable PNG.
    """
    template = {
        "type": "text",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"lines": ["Port {seq}"], "length_mm": 1000.0},
    }
    body = {
        "labels": [template],
        "serialization": {"kind": "list", "values": ["A", "B"]},
        "options": {"chain_mode": "cut_each"},
        "scale": 8,
    }

    resp = await client.post("/api/print/preview", json=body)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "exceeding" in detail
    assert "40,000,000" in detail  # MAX_PREVIEW_PIXELS, formatted
    assert "scale=8" in detail


async def test_preview_pixel_budget_uses_post_scale_dimensions(client):
    """A request whose PRE-scale composite is comfortably under the budget
    but whose scale pushes it over must still 422 -- the guard checks
    width_dots*scale x height_dots*scale, not the unscaled figure."""
    label = _text_label("BUDGET", length_mm=900.0)  # ~6380 dots x 128 -> ~0.82 MP pre-scale

    small_scale_resp = await client.post(
        "/api/print/preview", json={"labels": [label], "scale": 1}
    )
    assert small_scale_resp.status_code == 200  # ~0.82 MP: nowhere near the cap

    large_scale_resp = await client.post(
        "/api/print/preview", json={"labels": [label], "scale": 8}
    )
    # ~0.82 MP x 64 (scale=8 squared) =~ 52.3 MP: over the 40 MP cap.
    assert large_scale_resp.status_code == 422
    assert "40,000,000" in large_scale_resp.json()["detail"]


# --- (i) H1: MemoryError from the render/composite/encode calls maps to ----
# 507, never a raw 500 -- docs/code-review-2026-08.md.


async def test_preview_memory_error_during_composite_maps_to_507_not_500(client, monkeypatch):
    """A backstop for whatever the pixel-budget check above doesn't catch:
    if the actual rasterize/composite/encode work raises MemoryError, the
    endpoint must still respond with a clean error, not an unhandled 500."""

    def _out_of_memory(*args, **kwargs):
        raise MemoryError("simulated OOM")

    monkeypatch.setattr(
        "labelmaker.api.router_print.build_chained_preview_from_rendered", _out_of_memory
    )

    label = _text_label("SOLO", length_mm=20.0)
    resp = await client.post("/api/print/preview", json={"labels": [label], "scale": 1})
    assert resp.status_code == 507
    assert "memory" in resp.json()["detail"].lower()


# --- Regression: no full-suite run, but a spot check that /print itself ----
# still behaves -- run separately via `uv run pytest tests/test_api_print.py -q`
# per this track's own instructions, not duplicated here.
