"""Unit tests for the Track D2 additions to
backend/scripts/symbols_pipeline/common.py: extract_fill_path() (the
source-agnostic single-OR-multi-<path> merge every one of the four new
sources -- fetch_tabler.py/fetch_remix.py/fetch_bootstrap.py/fetch_fluent.py
-- uses instead of the older extract_single_path_d), the fill_rule= addition
to build_svg_document(), and classify_by_keyword() (the shared
priority-ordered keyword-map fetch_bootstrap.py/fetch_fluent.py use directly,
and fetch_tabler.py uses as its metadata-less fallback).

`common.py` lives under scripts/symbols_pipeline/ (dev tooling, not part of
the installed `labelmaker` package -- see that module's own docstring), so
it isn't importable as a normal dotted package the way `labelmaker.*` is;
this file adds that directory to sys.path itself, the same way every
fetch_*.py gets `import common` to work by virtue of being *run from* that
directory (this test file isn't run from there, so it can't rely on that).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PIPELINE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "symbols_pipeline"
if str(_PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_DIR))

import common  # noqa: E402

# --- extract_fill_path() -----------------------------------------------


def test_extract_fill_path_single_path_no_fill_rule_defaults_nonzero():
    svg = '<svg viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'
    result = common.extract_fill_path(svg)
    assert result == ("M0 0h24v24H0z", "nonzero")


def test_extract_fill_path_single_path_preserves_its_own_evenodd():
    # Unlike extract_single_path_d, which only ever returns the bare `d`
    # string and silently drops whatever fill-rule the source declared --
    # this matters in practice: ~70 Bootstrap Icons fill-*.svg files declare
    # fill-rule="evenodd" on a SINGLE <path> for hole/cusp geometry (e.g.
    # heart-fill.svg's cardioid notch).
    svg = '<svg viewBox="0 0 16 16"><path fill-rule="evenodd" d="M8 1 L8 15"/></svg>'
    result = common.extract_fill_path(svg)
    assert result == ("M8 1 L8 15", "evenodd")


def test_extract_fill_path_drops_fill_none_boilerplate_and_merges_rest():
    # The exact shape every Tabler filled/*.svg ships: an invisible
    # full-canvas hitbox path (fill="none") ahead of the real glyph path(s).
    svg = (
        '<svg viewBox="0 0 24 24">'
        '<path stroke="none" d="M0 0h24v24H0z" fill="none" />'
        '<path d="M1 1h2v2h-2z" />'
        "</svg>"
    )
    result = common.extract_fill_path(svg)
    assert result == ("M1 1h2v2h-2z", "nonzero")


def test_extract_fill_path_merges_multiple_real_paths_in_document_order():
    svg = '<svg viewBox="0 0 24 24"><path d="M1 1z" /><path d="M2 2z" /><path d="M3 3z" /></svg>'
    result = common.extract_fill_path(svg)
    assert result == ("M1 1z M2 2z M3 3z", "nonzero")


def test_extract_fill_path_union_evenodd_wins_if_any_path_declares_it():
    svg = '<svg viewBox="0 0 24 24"><path d="M1 1z" /><path fill-rule="evenodd" d="M2 2z" /></svg>'
    result = common.extract_fill_path(svg)
    assert result == ("M1 1z M2 2z", "evenodd")


# --- H3: relative moveto on a non-first survivor ------------------------


def test_extract_fill_path_rejects_relative_m_on_non_first_survivor():
    # Per the SVG path grammar a relative `m` is only absolute-equivalent
    # as the very first command of the whole path -- concatenated after a
    # preceding subpath's `z` it resolves against that subpath's current
    # point instead, silently displacing everything that follows (this is
    # the exact shape of bootstrap_house's second path in the real source:
    # docs/code-review-2026-08.md H3). Naive concatenation used to accept
    # this; it must now be rejected rather than "fixed" by guessing.
    svg = '<svg viewBox="0 0 24 24"><path d="M0 0h10v10h-10z" /><path d="m5 5h5v5h-5z" /></svg>'
    assert common.extract_fill_path(svg) is None


def test_extract_fill_path_accepts_relative_m_as_the_first_path():
    # A relative `m` IS absolute-equivalent when it's the first (here,
    # only) command in the whole path -- only a NON-FIRST survivor's
    # relative `m` is unsafe to concatenate.
    svg = '<svg viewBox="0 0 24 24"><path d="m1 1h2v2h-2z"/></svg>'
    assert common.extract_fill_path(svg) == ("m1 1h2v2h-2z", "nonzero")


# --- M5/M6: render-equivalence gate on multi-path merges -----------------


def test_extract_fill_path_render_equivalence_gate_rejects_hollowed_overlap():
    # Two overlapping same-fill rectangles that are each independently
    # solid when drawn as separate sibling <path> elements (SVG doesn't
    # XOR between siblings -- the overlap just gets painted twice) but
    # fill-rule is resolved PER <path> over ALL of that path's own
    # subpaths TOGETHER, so folding both rectangles into one evenodd path
    # makes the overlap region crossed by two boundaries (even count) and
    # therefore a HOLE -- exactly the mechanism that hollowed out 5 shipped
    # icons (docs/code-review-2026-08.md M5, e.g.
    # tabler_arrow_big_left_line's solid arrow rendering hollow). No
    # relative moveto and no mixed fill-rule declaration is involved here
    # -- structurally this is exactly the family test_symbols_pipeline_
    # common.py's older merge tests couldn't distinguish from a safe merge
    # (M6), which is why this needs a real render, not a `d`-string check.
    svg = (
        '<svg viewBox="0 0 24 24">'
        '<path fill-rule="evenodd" d="M2 2H12V12H2Z" />'
        '<path fill-rule="evenodd" d="M7 7H17V17H7Z" />'
        "</svg>"
    )
    assert common.extract_fill_path(svg) is None


def test_extract_fill_path_render_equivalence_gate_passes_disjoint_merge():
    # Two non-overlapping, non-touching same-fill rectangles: merging them
    # into one <path> can't change the rendered result (no shared geometry
    # for a fill-rule to resolve differently over), so the render-
    # equivalence gate must still let this real, legitimate merge through
    # -- this is the common case (the large majority of the four sources'
    # real multi-path merges), not just the toy cases above.
    svg = '<svg viewBox="0 0 24 24"><path d="M1 1H9V9H1Z" /><path d="M15 15H23V23H15Z" /></svg>'
    result = common.extract_fill_path(svg)
    assert result == ("M1 1H9V9H1Z M15 15H23V23H15Z", "nonzero")


def test_extract_fill_path_rejects_zero_paths():
    assert common.extract_fill_path('<svg viewBox="0 0 24 24"></svg>') is None


def test_extract_fill_path_rejects_all_paths_fill_none():
    svg = '<svg viewBox="0 0 24 24"><path d="M0 0h24v24H0z" fill="none"/></svg>'
    assert common.extract_fill_path(svg) is None


def test_extract_fill_path_rejects_other_drawable_elements():
    # Bootstrap Icons' circle-fill.svg: a bare <circle>, no <path> at all.
    svg = '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="8"/></svg>'
    assert common.extract_fill_path(svg) is None


def test_extract_fill_path_rejects_grouping_and_indirection_elements():
    for tag in ("g", "clipPath", "mask", "use", "defs"):
        svg = f'<svg viewBox="0 0 24 24"><{tag}><path d="M1 1z"/></{tag}></svg>'
        assert common.extract_fill_path(svg) is None, f"<{tag}> should reject"


def test_extract_fill_path_rejects_differing_explicit_fills():
    # Fluent's flag_pride_*_24_filled.svg shape: several stripe paths, each
    # its own hex fill -- a genuinely multi-color icon, not mergeable into
    # one single-fill path without silently discarding color information.
    svg = (
        '<svg viewBox="0 0 24 24">'
        '<path fill="#E62C46" d="M1 1z"/>'
        '<path fill="#1793E8" d="M2 2z"/>'
        "</svg>"
    )
    assert common.extract_fill_path(svg) is None


def test_extract_fill_path_accepts_same_explicit_fill_repeated():
    svg = (
        '<svg viewBox="0 0 24 24">'
        '<path fill="currentColor" d="M1 1z"/>'
        '<path fill="currentColor" d="M2 2z"/>'
        "</svg>"
    )
    assert common.extract_fill_path(svg) == ("M1 1z M2 2z", "nonzero")


def test_extract_fill_path_rejects_stroke_on_a_kept_path():
    svg = '<svg viewBox="0 0 24 24"><path d="M1 1z"/><path stroke="red" d="M2 2z"/></svg>'
    assert common.extract_fill_path(svg) is None


def test_extract_fill_path_accepts_explicit_stroke_none_on_a_kept_path():
    # Only an explicit fill="none" path is dropped outright; a real
    # (non-fill=none) path with stroke="none" is just a no-op stroke and
    # stays eligible.
    svg = '<svg viewBox="0 0 24 24"><path stroke="none" d="M1 1z"/></svg>'
    assert common.extract_fill_path(svg) == ("M1 1z", "nonzero")


def test_extract_fill_path_rejects_transform_on_a_kept_path():
    svg = (
        '<svg viewBox="0 0 24 24">'
        '<path d="M1 1z"/>'
        '<path transform="translate(1,1)" d="M2 2z"/>'
        "</svg>"
    )
    assert common.extract_fill_path(svg) is None


# --- build_svg_document() fill_rule= addition ---------------------------


def test_build_svg_document_existing_positional_call_style_unaffected():
    # The exact call shape fetch_material.py/fetch_phosphor.py already use
    # -- must keep producing a non-empty transform attribute.
    doc = common.build_svg_document("M0 0", "scale(0.025) translate(0,960)")
    assert 'transform="scale(0.025) translate(0,960)"' in doc
    assert "fill-rule" not in doc
    assert doc.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">')
    assert doc.endswith("</svg>")


def test_build_svg_document_omits_transform_attribute_when_not_given():
    doc = common.build_svg_document("M0 0")
    assert "transform=" not in doc


def test_build_svg_document_emits_fill_rule_when_given():
    doc = common.build_svg_document("M0 0", fill_rule="evenodd")
    assert 'fill-rule="evenodd"' in doc
    assert "transform=" not in doc


def test_build_svg_document_omits_fill_rule_when_none():
    doc = common.build_svg_document("M0 0", "scale(1.5)")
    assert "fill-rule" not in doc


def test_build_svg_document_is_still_a_single_path_document():
    doc = common.build_svg_document("M0 0", "scale(1.5)", fill_rule="evenodd")
    assert doc.count("<path") == 1


# --- classify_by_keyword() ------------------------------------------------


def test_classify_by_keyword_electrical():
    assert common.classify_by_keyword(["battery", "charge"]) == "electrical"


def test_classify_by_keyword_network():
    assert common.classify_by_keyword(["wifi", "off"]) == "network"


def test_classify_by_keyword_av():
    assert common.classify_by_keyword(["camera", "lens"]) == "av"


def test_classify_by_keyword_arrow():
    assert common.classify_by_keyword(["arrow", "autofit", "down"]) == "arrow"


def test_classify_by_keyword_safety():
    assert common.classify_by_keyword(["shield", "check"]) == "safety"


def test_classify_by_keyword_defaults_misc():
    assert common.classify_by_keyword(["banana", "sandwich"]) == "misc"


def test_classify_by_keyword_is_case_insensitive():
    assert common.classify_by_keyword(["WIFI"]) == "network"


def test_classify_by_keyword_priority_order_electrical_before_safety():
    # "battery-warning": battery (electrical) must win over warning
    # (safety) -- the documented fixed priority order (electrical, network,
    # av, arrow, safety), matching lucide_ids.txt's own example.
    assert common.classify_by_keyword(["battery", "warning"]) == "electrical"


def test_classify_by_keyword_priority_order_network_before_av():
    assert common.classify_by_keyword(["cast", "radio"]) == "network"


def test_classify_by_keyword_override_short_circuits_token_match():
    # "cable-car" would land electrical via the bare "cable" token without
    # the override -- the same hand-exception lucide_ids.txt's header
    # documents needing for its own keyword-map.
    tokens = ["cable", "car"]
    assert common.classify_by_keyword(tokens, base_id="cable_car") == "electrical"
    assert (
        common.classify_by_keyword(tokens, overrides={"cable_car": "misc"}, base_id="cable_car")
        == "misc"
    )


def test_classify_by_keyword_override_only_applies_to_matching_base_id():
    assert (
        common.classify_by_keyword(["battery"], overrides={"cable_car": "misc"}, base_id="battery")
        == "electrical"
    )
