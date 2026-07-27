"""Tests for labelmaker.render.serialize: BarTender-model sequence
expansion (task 2.4) -- NUMERIC/ALPHA/LIST/CSV distinct-value generation,
{seq}/{csv.<col>} token substitution, and expand_definition's recursive,
collation-aware, non-mutating fan-out of one template definition into N
bound label definitions.

Expected values throughout are hand-derived from the documented algorithms
(see serialize.py's own docstrings for the exact formulas), independent of
the implementation:

- NUMERIC: value_i = start + i*step, then str().zfill(pad_width) (zfill is
  sign-aware and never truncates -- verified against plain Python str.zfill
  semantics, e.g. str(-1).zfill(3) == "-01", str(100).zfill(2) == "100").
- ALPHA: spreadsheet-style (bijective) base-26, ordinal("A")=0 .. ordinal
  ("Z")=25, ordinal("AA")=26, ordinal("ZZZ")=18277 -- value_i =
  to_alpha(ordinal(alpha_start) + i*step).
- Collation: COPIES_ADJACENT groups each distinct value's copies together
  (v1,v1,v2,v2); SEQUENCE_REPEATED repeats the whole distinct run
  (v1,v2,v1,v2).
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from labelmaker.render.serialize import (
    Collation,
    Sequence,
    SequenceKind,
    distinct_pairs,
    effective_count,
    expand_definition,
    expand_tokens,
    ordered_values,
    sequence_values,
    total_labels,
)

# --- 0. Enum wire values (StrEnum -- JSON round-trips as these strings) ----


def test_sequence_kind_wire_values():
    assert SequenceKind.NUMERIC == "numeric"
    assert SequenceKind.ALPHA == "alpha"
    assert SequenceKind.LIST == "list"
    assert SequenceKind.CSV == "csv"


def test_collation_wire_values():
    assert Collation.COPIES_ADJACENT == "copies_adjacent"
    assert Collation.SEQUENCE_REPEATED == "sequence_repeated"


def test_collation_default_is_copies_adjacent():
    seq = Sequence(kind=SequenceKind.NUMERIC, count=1)
    assert seq.collation == Collation.COPIES_ADJACENT


# --- 1. NUMERIC ------------------------------------------------------------


def test_numeric_default_start_step_no_padding():
    # start=1 (default), step=1 (default), count=5, pad_width=0 (default):
    # 1, 2, 3, 4, 5 -- no zero-padding.
    seq = Sequence(kind=SequenceKind.NUMERIC, count=5)
    assert sequence_values(seq) == ["1", "2", "3", "4", "5"]


def test_numeric_negative_step():
    # start=10, step=-1, count=5: 10, 9, 8, 7, 6 (brief's own example).
    seq = Sequence(kind=SequenceKind.NUMERIC, start=10, step=-1, count=5)
    assert sequence_values(seq) == ["10", "9", "8", "7", "6"]


def test_numeric_zero_padding():
    # start=1, step=1, count=3, pad_width=3: "1".zfill(3)="001", etc.
    seq = Sequence(kind=SequenceKind.NUMERIC, start=1, step=1, count=3, pad_width=3)
    assert sequence_values(seq) == ["001", "002", "003"]


def test_numeric_negative_values_with_padding_documented_sign_behavior():
    # start=-1, step=-1, count=3, pad_width=3: values -1,-2,-3. zfill is
    # sign-aware: the '-' is stripped, the digits padded, then the sign is
    # re-applied -- str(-1).zfill(3) == "-01" (2 digit positions + sign),
    # NOT "0-1" or "-001". Verified directly against Python's str.zfill.
    seq = Sequence(kind=SequenceKind.NUMERIC, start=-1, step=-1, count=3, pad_width=3)
    assert sequence_values(seq) == ["-01", "-02", "-03"]


def test_numeric_pad_overflow_grows_naturally_past_pad_width():
    # start=95, step=1, count=6, pad_width=2: 95..100. zfill only ADDS
    # zeros, never truncates -- "99" (2 digits, fits pad_width=2) is
    # followed by "100" (3 digits, wider than pad_width, left as-is).
    seq = Sequence(kind=SequenceKind.NUMERIC, start=95, step=1, count=6, pad_width=2)
    assert sequence_values(seq) == ["95", "96", "97", "98", "99", "100"]


def test_numeric_step_zero_rejected():
    with pytest.raises(ValidationError):
        Sequence(kind=SequenceKind.NUMERIC, step=0)


# --- 2. ALPHA ----------------------------------------------------------


def test_alpha_a_through_z():
    # ordinal("A")=0 .. ordinal("Z")=25, step=1, count=26: A, B, ..., Z.
    seq = Sequence(kind=SequenceKind.ALPHA, alpha_start="A", step=1, count=26)
    expected = [chr(ord("A") + i) for i in range(26)]
    assert sequence_values(seq) == expected
    assert sequence_values(seq)[-1] == "Z"


def test_alpha_y_step1_count4_wraps_into_two_letters():
    # ordinal("Y")=24: 24, 25, 26, 27 -> Y, Z, AA, AB (brief's own example).
    seq = Sequence(kind=SequenceKind.ALPHA, alpha_start="Y", step=1, count=4)
    assert sequence_values(seq) == ["Y", "Z", "AA", "AB"]


def test_alpha_aa_start():
    # ordinal("AA")=26, step=1, count=3: AA, AB, AC.
    seq = Sequence(kind=SequenceKind.ALPHA, alpha_start="AA", step=1, count=3)
    assert sequence_values(seq) == ["AA", "AB", "AC"]


def test_alpha_step_2():
    # ordinal("A")=0, step=2, count=4: 0, 2, 4, 6 -> A, C, E, G.
    seq = Sequence(kind=SequenceKind.ALPHA, alpha_start="A", step=2, count=4)
    assert sequence_values(seq) == ["A", "C", "E", "G"]


def test_alpha_underflow_raises():
    # ordinal("A")=0, step=-1: i=1 gives ordinal -1 < 0.
    seq = Sequence(kind=SequenceKind.ALPHA, alpha_start="A", step=-1, count=2)
    with pytest.raises(ValueError, match="below 'A'"):
        sequence_values(seq)


def test_alpha_zzz_is_the_last_valid_value():
    # ordinal("ZZZ")=18277 exactly at the cap -- a single-value run ending
    # there must NOT raise.
    seq = Sequence(kind=SequenceKind.ALPHA, alpha_start="ZZZ", step=1, count=1)
    assert sequence_values(seq) == ["ZZZ"]


def test_alpha_beyond_zzz_raises():
    # ordinal("ZZZ")=18277; count=2, step=1 -> i=1 gives 18278, past the cap.
    seq = Sequence(kind=SequenceKind.ALPHA, alpha_start="ZZZ", step=1, count=2)
    with pytest.raises(ValueError, match="ZZZ"):
        sequence_values(seq)


# --- 3. LIST -----------------------------------------------------------


def test_list_values_pass_through_verbatim():
    seq = Sequence(kind=SequenceKind.LIST, values=["PORT-A", "PORT-B", "PORT-C"])
    assert sequence_values(seq) == ["PORT-A", "PORT-B", "PORT-C"]


def test_list_count_field_is_ignored_and_derived_from_values():
    # count defaults to 1 but effective_count must come from len(values), 3.
    seq = Sequence(kind=SequenceKind.LIST, values=["A", "B", "C"])
    assert effective_count(seq) == 3


def test_list_empty_values_rejected():
    with pytest.raises(ValidationError):
        Sequence(kind=SequenceKind.LIST, values=[])


def test_list_over_500_values_rejected():
    with pytest.raises(ValidationError):
        Sequence(kind=SequenceKind.LIST, values=[f"v{i}" for i in range(501)])


def test_list_exactly_500_values_accepted():
    seq = Sequence(kind=SequenceKind.LIST, values=[f"v{i}" for i in range(500)])
    assert effective_count(seq) == 500


# --- 4. CSV --------------------------------------------------------------


def test_csv_rows_derive_effective_count():
    seq = Sequence(
        kind=SequenceKind.CSV,
        rows=[{"port": "1", "name": "Alice"}, {"port": "2", "name": "Bob"}],
    )
    assert effective_count(seq) == 2


def test_csv_sequence_values_are_1_based_row_positions():
    # CSV rows have no single scalar "value" column -- sequence_values()
    # falls back to a 1-based positional string per row (see serialize.py's
    # docstring on this design choice); {csv.<col>} is the real per-row
    # substitution mechanism, exercised via expand_tokens/expand_definition
    # below.
    seq = Sequence(
        kind=SequenceKind.CSV,
        rows=[{"port": "1"}, {"port": "2"}, {"port": "3"}],
    )
    assert sequence_values(seq) == ["1", "2", "3"]


def test_csv_empty_rows_rejected():
    with pytest.raises(ValidationError):
        Sequence(kind=SequenceKind.CSV, rows=[])


def test_csv_over_500_rows_rejected():
    with pytest.raises(ValidationError):
        Sequence(kind=SequenceKind.CSV, rows=[{"a": str(i)} for i in range(501)])


def test_csv_ragged_rows_rejected():
    with pytest.raises(ValidationError):
        Sequence(
            kind=SequenceKind.CSV,
            rows=[{"port": "1", "name": "Alice"}, {"port": "2"}],
        )


def test_csv_extra_column_in_later_row_rejected():
    with pytest.raises(ValidationError):
        Sequence(
            kind=SequenceKind.CSV,
            rows=[{"port": "1"}, {"port": "2", "extra": "x"}],
        )


# --- 5. Collation --------------------------------------------------------


def test_collation_copies_adjacent_hand_verified():
    # 3 values x 2 copies, COPIES_ADJACENT: v1,v1,v2,v2,v3,v3.
    seq = Sequence(
        kind=SequenceKind.LIST,
        values=["v1", "v2", "v3"],
        copies_per_value=2,
        collation=Collation.COPIES_ADJACENT,
    )
    assert ordered_values(seq) == ["v1", "v1", "v2", "v2", "v3", "v3"]


def test_collation_sequence_repeated_hand_verified():
    # 3 values x 2 copies, SEQUENCE_REPEATED: v1,v2,v3,v1,v2,v3.
    seq = Sequence(
        kind=SequenceKind.LIST,
        values=["v1", "v2", "v3"],
        copies_per_value=2,
        collation=Collation.SEQUENCE_REPEATED,
    )
    assert ordered_values(seq) == ["v1", "v2", "v3", "v1", "v2", "v3"]


# --- 6. Cap: total = effective_count * copies_per_value <= 1000 --------


def test_cap_501_values_x2_copies_rejected():
    with pytest.raises(ValidationError):
        Sequence(
            kind=SequenceKind.LIST,
            values=[f"v{i}" for i in range(501)],
            copies_per_value=2,
        )


def test_cap_500_values_x2_copies_ok_at_exactly_1000():
    seq = Sequence(
        kind=SequenceKind.LIST,
        values=[f"v{i}" for i in range(500)],
        copies_per_value=2,
    )
    assert total_labels(seq) == 1000


def test_cap_enforced_even_when_each_field_individually_in_range():
    # count=500 (<= its own 500 max) and copies_per_value=3 (<= its own 100
    # max) are both individually legal, but 500*3=1500 exceeds the 1000
    # cross-field total cap -- this is the case that actually exercises the
    # cap validator itself, not just a single field's own Field() bound.
    with pytest.raises(ValidationError, match="1000"):
        Sequence(kind=SequenceKind.NUMERIC, count=500, copies_per_value=3)


def test_cap_boundary_500_count_x2_copies_ok():
    seq = Sequence(kind=SequenceKind.NUMERIC, count=500, copies_per_value=2)
    assert total_labels(seq) == 1000


# --- 7. expand_tokens ------------------------------------------------------


def test_expand_tokens_replaces_seq():
    assert expand_tokens("Port {seq}", "PORT-01", None) == "Port PORT-01"


def test_expand_tokens_replaces_multiple_seq_occurrences():
    assert expand_tokens("{seq}-{seq}", "X", None) == "X-X"


def test_expand_tokens_replaces_csv_column():
    assert expand_tokens("{csv.port}", "1", {"port": "24", "name": "Alice"}) == "24"


def test_expand_tokens_replaces_seq_and_csv_together():
    text = "{seq}: {csv.name} on port {csv.port}"
    row = {"name": "Alice", "port": "24"}
    assert expand_tokens(text, "1", row) == "1: Alice on port 24"


def test_expand_tokens_unknown_csv_column_lists_available_columns():
    with pytest.raises(ValueError, match="port") as excinfo:
        expand_tokens("{csv.port}", "1", {"name": "Alice"})
    assert "name" in str(excinfo.value)


def test_expand_tokens_csv_column_with_no_row_raises():
    # No row bound at all (e.g. a NUMERIC/ALPHA/LIST sequence's template
    # happens to contain a {csv.*} token) -- treated the same as "unknown
    # column", with an empty available-columns list.
    with pytest.raises(ValueError, match="port"):
        expand_tokens("{csv.port}", "1", None)


@pytest.mark.parametrize("text", ["{foo}", "{sequence}", "{csv}", "{csv.}", "plain text"])
def test_expand_tokens_leaves_non_matching_text_untouched(text):
    assert expand_tokens(text, "VALUE", {"col": "x"}) == text


def test_expand_tokens_no_tokens_returns_unchanged():
    assert expand_tokens("nothing to replace here", "X", None) == "nothing to replace here"


# --- 8. expand_definition --------------------------------------------------


def _patch_panel_definition() -> dict:
    # Nested params shape mirroring render/types/patch_panel.py's
    # PatchPanelParams (blocks: list[{lines: list[str]}]) -- the divided-
    # blocks family's nested-params shape the brief calls out for exercising
    # expand_definition's recursive substitution.
    return {
        "type": "patch_panel",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {
            "block_length_mm": 15.0,
            "blocks": [
                {"lines": ["Port {seq}", "static"]},
                {"lines": ["{seq}"]},
            ],
        },
    }


def test_expand_definition_reaches_nested_blocks_lines():
    seq = Sequence(kind=SequenceKind.NUMERIC, start=1, step=1, count=2)
    out = expand_definition(_patch_panel_definition(), seq)
    assert len(out) == 2
    assert out[0]["params"]["blocks"][0]["lines"] == ["Port 1", "static"]
    assert out[0]["params"]["blocks"][1]["lines"] == ["1"]
    assert out[1]["params"]["blocks"][0]["lines"] == ["Port 2", "static"]
    assert out[1]["params"]["blocks"][1]["lines"] == ["2"]


def test_expand_definition_preserves_non_string_fields():
    seq = Sequence(kind=SequenceKind.NUMERIC, count=1)
    out = expand_definition(_patch_panel_definition(), seq)
    assert out[0]["type"] == "patch_panel"
    assert out[0]["tape"] == {"width_mm": 24, "family": "tze"}
    assert out[0]["params"]["block_length_mm"] == 15.0


def test_expand_definition_does_not_mutate_input():
    original = _patch_panel_definition()
    snapshot = copy.deepcopy(original)
    seq = Sequence(kind=SequenceKind.NUMERIC, start=1, step=1, count=3)

    expand_definition(original, seq)

    assert original == snapshot


def test_expand_definition_length_matches_effective_count_times_copies():
    seq = Sequence(kind=SequenceKind.LIST, values=["a", "b", "c"], copies_per_value=2)
    out = expand_definition(_patch_panel_definition(), seq)
    assert len(out) == 6 == total_labels(seq)


def test_expand_definition_collation_order_copies_adjacent():
    seq = Sequence(
        kind=SequenceKind.LIST,
        values=["A", "B"],
        copies_per_value=2,
        collation=Collation.COPIES_ADJACENT,
    )
    out = expand_definition(_patch_panel_definition(), seq)
    seq_values = [d["params"]["blocks"][1]["lines"][0] for d in out]
    assert seq_values == ["A", "A", "B", "B"]


def test_expand_definition_collation_order_sequence_repeated():
    seq = Sequence(
        kind=SequenceKind.LIST,
        values=["A", "B"],
        copies_per_value=2,
        collation=Collation.SEQUENCE_REPEATED,
    )
    out = expand_definition(_patch_panel_definition(), seq)
    seq_values = [d["params"]["blocks"][1]["lines"][0] for d in out]
    assert seq_values == ["A", "B", "A", "B"]


def test_expand_definition_csv_binds_row_columns_per_label():
    definition = {
        "type": "patch_panel",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"blocks": [{"lines": ["{csv.name} - {csv.port}"]}]},
    }
    seq = Sequence(
        kind=SequenceKind.CSV,
        rows=[
            {"name": "Alice", "port": "1"},
            {"name": "Bob", "port": "2"},
        ],
    )
    out = expand_definition(definition, seq)
    assert out[0]["params"]["blocks"][0]["lines"] == ["Alice - 1"]
    assert out[1]["params"]["blocks"][0]["lines"] == ["Bob - 2"]


def test_expand_definition_unknown_csv_column_raises():
    definition = {
        "type": "patch_panel",
        "tape": {"width_mm": 24, "family": "tze"},
        "params": {"blocks": [{"lines": ["{csv.missing}"]}]},
    }
    seq = Sequence(kind=SequenceKind.CSV, rows=[{"port": "1"}])
    with pytest.raises(ValueError, match="missing"):
        expand_definition(definition, seq)


def test_expand_definition_is_deterministic():
    seq = Sequence(kind=SequenceKind.NUMERIC, start=1, step=1, count=5, pad_width=2)
    definition = _patch_panel_definition()
    first = expand_definition(definition, seq)
    second = expand_definition(definition, seq)
    assert first == second


# --- 9. effective_count / total_labels sanity across all kinds -----------


@pytest.mark.parametrize(
    ("kind_kwargs", "expected"),
    [
        ({"kind": SequenceKind.NUMERIC, "count": 7}, 7),
        ({"kind": SequenceKind.ALPHA, "count": 4}, 4),
        ({"kind": SequenceKind.LIST, "values": ["a", "b"]}, 2),
        ({"kind": SequenceKind.CSV, "rows": [{"a": "1"}, {"a": "2"}, {"a": "3"}]}, 3),
    ],
)
def test_effective_count_across_kinds(kind_kwargs, expected):
    seq = Sequence(**kind_kwargs)
    assert effective_count(seq) == expected


def test_total_labels_multiplies_effective_count_by_copies():
    seq = Sequence(kind=SequenceKind.NUMERIC, count=4, copies_per_value=3)
    assert total_labels(seq) == 12


# --- 10. distinct_pairs (samples/UI-chip primitive; no copies applied) ---


def test_distinct_pairs_numeric_rows_are_none():
    seq = Sequence(kind=SequenceKind.NUMERIC, start=1, step=1, count=3, copies_per_value=5)
    assert distinct_pairs(seq) == [("1", None), ("2", None), ("3", None)]


def test_distinct_pairs_csv_zips_values_with_their_own_row():
    seq = Sequence(
        kind=SequenceKind.CSV,
        rows=[{"port": "1"}, {"port": "2"}],
        copies_per_value=3,
    )
    assert distinct_pairs(seq) == [("1", {"port": "1"}), ("2", {"port": "2"})]
