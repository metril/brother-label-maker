"""BarTender-model sequence serialization (task 2.4): server-side expansion
of a Sequence spec into one bound label definition per output label.

BarTender separates "how many DISTINCT values" (Sequence.count, or the
length of `values`/`rows` for LIST/CSV -- see effective_count()) from "how
many COPIES of each value" (Sequence.copies_per_value): total_labels(seq)
== effective_count(seq) * seq.copies_per_value is always the length
expand_definition() returns. Collation controls whether those copies sit
adjacent to each other (COPIES_ADJACENT: v1,v1,v2,v2 -- BarTender's own
default, "copies of each serial") or the whole distinct run repeats
(SEQUENCE_REPEATED: v1,v2,v1,v2).

Server-side, DECIDED (task 2.4 brief): POST /api/print stores the
UNEXPANDED template definition + this Sequence spec in the job snapshot;
jobs/worker.py re-expands via expand_definition() at render time. Reprint
is therefore reproducible from the same (template, Sequence) pair without
ever persisting N separate label definitions -- see router_print.py and
jobs/worker.py.
"""

from __future__ import annotations

import copy
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_MAX_TOTAL_LABELS = 1000
_MIN_LIST_VALUES = 1
_MAX_LIST_VALUES = 500
_MIN_CSV_ROWS = 1
# Public (not underscore-prefixed): also imported by api/router_labels.py's
# POST /api/serialize/csv upload endpoint, so the "500 data rows" cap has
# exactly one owner instead of two independently-maintained constants that
# could drift apart.
MAX_CSV_ROWS = 500

# Spreadsheet-style (bijective) base-26 ordinal of "ZZZ" -- see _ordinal's
# docstring for the ordinal("A")=0 .. ordinal("Z")=25, ordinal("AA")=26
# convention. alpha_start's own pattern caps at 3 letters, so this is also
# the ordinal ceiling ANY stepped ALPHA value in a run may reach (checked
# at expansion time in sequence_values(), not at Sequence construction,
# since it depends on `count`/`step` together -- see that function).
_MAX_ALPHA_ORDINAL = 18277

# Matches the two token shapes expand_tokens understands: a bare "{seq}",
# or "{csv.<anything but a closing brace>}". Anything else (unmatched
# braces, a bare "{csv}", an empty "{csv.}") simply doesn't match and is
# left untouched by _TOKEN_RE.sub.
_TOKEN_RE = re.compile(r"\{seq\}|\{csv\.([^}]+)\}")


class SequenceKind(StrEnum):
    NUMERIC = "numeric"
    ALPHA = "alpha"
    LIST = "list"
    CSV = "csv"


class Collation(StrEnum):
    """BarTender's copies-of-each-serial vs whole-run-repeated split -- see
    this module's docstring."""

    COPIES_ADJACENT = "copies_adjacent"  # v1,v1,v2,v2 (BarTender default)
    SEQUENCE_REPEATED = "sequence_repeated"  # v1,v2,v1,v2


class Sequence(BaseModel):
    """One serialization spec. Which fields matter depends on `kind`:

    - NUMERIC reads start/step/pad_width/count.
    - ALPHA reads alpha_start/step/count.
    - LIST reads `values`; `count` is ignored (effective_count() derives it
      as len(values) instead -- see that function).
    - CSV reads `rows`; `count` is likewise ignored (derived as
      len(rows)), and each output label additionally gets that row's own
      columns bound via {csv.<col>} tokens -- see expand_tokens.
    """

    kind: SequenceKind
    count: int = Field(1, ge=1, le=500)
    copies_per_value: int = Field(1, ge=1, le=100)
    collation: Collation = Collation.COPIES_ADJACENT
    start: int = Field(1, ge=-999999, le=999999)
    step: int = Field(1, ge=-9999, le=9999)
    # zfill is sign-aware -- str(-1).zfill(3) == "-01" (the '-' doesn't
    # count against the padded digit width) -- and never truncates: a
    # value that naturally outgrows pad_width (e.g. 100 with pad_width=2)
    # is left at its full natural width ("100", not a truncated "00").
    # See test_serialize.py's numeric padding cases for hand-verified
    # examples of both.
    pad_width: int = Field(0, ge=0, le=6)
    alpha_start: str = Field("A", pattern=r"^[A-Z]{1,3}$")
    values: list[str] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)

    @field_validator("step")
    @classmethod
    def _check_step_nonzero(cls, step: int) -> int:
        if step == 0:
            raise ValueError("step must not be 0")
        return step

    @model_validator(mode="after")
    def _check_kind_requirements_and_cap(self) -> Sequence:
        if self.kind == SequenceKind.LIST:
            if not (_MIN_LIST_VALUES <= len(self.values) <= _MAX_LIST_VALUES):
                raise ValueError(
                    f"kind=list requires {_MIN_LIST_VALUES}-{_MAX_LIST_VALUES} values, "
                    f"got {len(self.values)}"
                )
        elif self.kind == SequenceKind.CSV:
            if not (_MIN_CSV_ROWS <= len(self.rows) <= MAX_CSV_ROWS):
                raise ValueError(
                    f"kind=csv requires {_MIN_CSV_ROWS}-{MAX_CSV_ROWS} rows, "
                    f"got {len(self.rows)}"
                )
            columns = set(self.rows[0])
            for i, row in enumerate(self.rows[1:], start=1):
                if set(row) != columns:
                    raise ValueError(
                        f"CSV row {i} has columns {sorted(row)}, expected {sorted(columns)}"
                    )

        count = effective_count(self)
        total = count * self.copies_per_value
        if total > _MAX_TOTAL_LABELS:
            raise ValueError(
                f"total labels {total} ({count} values x {self.copies_per_value} copies) "
                f"exceeds the {_MAX_TOTAL_LABELS} maximum"
            )
        return self


def effective_count(seq: Sequence) -> int:
    """The number of DISTINCT values `seq` produces -- `seq.count` for
    NUMERIC/ALPHA, or the length of `values`/`rows` for LIST/CSV (whose own
    `count` field is unused -- see the Sequence class docstring)."""
    if seq.kind in (SequenceKind.NUMERIC, SequenceKind.ALPHA):
        return seq.count
    if seq.kind == SequenceKind.LIST:
        return len(seq.values)
    return len(seq.rows)  # SequenceKind.CSV


def total_labels(seq: Sequence) -> int:
    """effective_count(seq) * copies_per_value -- the length
    expand_definition(...) (and ordered_values(...)) return for `seq`."""
    return effective_count(seq) * seq.copies_per_value


def _ordinal(letters: str) -> int:
    """Spreadsheet-style (bijective) base-26: ordinal("A")=0, ...,
    ordinal("Z")=25, ordinal("AA")=26. Each letter contributes 1-26 (never
    0) at its place -- the "+1" per digit is what makes "AA" come right
    after "Z" instead of colliding with "A" the way a plain 0-25-per-digit
    base-26 encoding would."""
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _to_alpha(ordinal: int) -> str:
    """Inverse of _ordinal: the spreadsheet-style letters for a given
    0-based ordinal."""
    n = ordinal + 1
    letters: list[str] = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def sequence_values(seq: Sequence) -> list[str]:
    """The distinct values `seq` produces, in order, with NO copies
    (copies_per_value/collation are applied later -- see _ordered_pairs /
    expand_definition / ordered_values). Length always equals
    effective_count(seq).

    Raises ValueError for an ALPHA run that steps below 'A' or beyond
    'ZZZ' at any point -- this is a runtime check (depends on `count` and
    `step` together), not a Sequence field validator.
    """
    if seq.kind == SequenceKind.NUMERIC:
        return [str(seq.start + i * seq.step).zfill(seq.pad_width) for i in range(seq.count)]

    if seq.kind == SequenceKind.ALPHA:
        base = _ordinal(seq.alpha_start)
        values = []
        for i in range(seq.count):
            n = base + i * seq.step
            if n < 0:
                raise ValueError(f"ALPHA sequence goes below 'A' at position {i}")
            if n > _MAX_ALPHA_ORDINAL:
                raise ValueError(f"ALPHA sequence goes beyond 'ZZZ' at position {i}")
            values.append(_to_alpha(n))
        return values

    if seq.kind == SequenceKind.LIST:
        return list(seq.values)

    # SequenceKind.CSV: rows carry the per-label data (bound via
    # {csv.<col>} -- see expand_tokens), so there's no single scalar
    # "value" column. {seq} in a CSV-mode template falls back to the row's
    # 1-based position -- a stable, always-present placeholder rather than
    # an error, in case a template written for another kind is reused.
    return [str(i + 1) for i in range(len(seq.rows))]


def distinct_pairs(seq: Sequence) -> list[tuple[str, dict[str, str] | None]]:
    """The (value, row) pair for each DISTINCT value `seq` produces --
    length == effective_count(seq), BEFORE copies_per_value/collation are
    applied (see _ordered_pairs, which multiplies/reorders this). `row` is
    the matching CSV row for kind=csv, else None. Exposed publicly (not
    just an _ordered_pairs implementation detail) because API callers that
    want per-distinct-value output -- e.g. POST /api/render/expand's
    `samples`, one expand_tokens() call per distinct value, no copies --
    need it without re-deriving the CSV row-pairing logic themselves."""
    values = sequence_values(seq)
    rows: list[dict[str, str] | None] = (
        list(seq.rows) if seq.kind == SequenceKind.CSV else [None] * len(values)
    )
    return list(zip(values, rows, strict=True))


def _ordered_pairs(seq: Sequence) -> list[tuple[str, dict[str, str] | None]]:
    """The (value, row) pair for every OUTPUT label, in order, after
    applying copies_per_value and collation -- length == total_labels(seq).
    Shared by expand_definition (which binds each pair into a definition)
    and ordered_values (which exposes just the value half, e.g. for API
    callers reporting "which sequence value produced label i" without
    re-deriving the collation logic)."""
    distinct = distinct_pairs(seq)
    if seq.collation == Collation.SEQUENCE_REPEATED:
        return distinct * seq.copies_per_value
    return [pair for pair in distinct for _ in range(seq.copies_per_value)]


def ordered_values(seq: Sequence) -> list[str]:
    """The `value` half of each output label's (value, row) pair, in the
    same collated order expand_definition() produces its bound
    definitions -- ordered_values(seq)[i] is the value that produced
    expand_definition(definition, seq)[i]."""
    return [value for value, _row in _ordered_pairs(seq)]


def expand_tokens(text: str, value: str, row: dict[str, str] | None) -> str:
    """Replace `{seq}` with `value` and `{csv.<col>}` with `row[col]`.

    An unknown `{csv.<col>}` (including when `row` is None -- no CSV row is
    bound at all) raises ValueError listing the columns that ARE available.
    Everything else -- including braces that don't match either exact
    pattern (`{foo}`, `{csv}`, `{csv.}`) -- passes through untouched.
    """

    def _replace(match: re.Match[str]) -> str:
        if match.group(0) == "{seq}":
            return value
        column = match.group(1)
        if row is None or column not in row:
            available = sorted(row) if row is not None else []
            raise ValueError(f"unknown CSV column {column!r}; available columns: {available}")
        return row[column]

    return _TOKEN_RE.sub(_replace, text)


def _substitute(node: Any, value: str, row: dict[str, str] | None) -> Any:
    """Recursively apply expand_tokens to every string found in `node`
    (walking dicts by value and lists by element -- dict KEYS are left
    alone). `node` is always a piece of a definition already deep-copied
    by expand_definition, so mutating dicts/lists in place here is safe:
    it never touches the caller's original definition."""
    if isinstance(node, str):
        return expand_tokens(node, value, row)
    if isinstance(node, dict):
        for key in node:
            node[key] = _substitute(node[key], value, row)
        return node
    if isinstance(node, list):
        for i, item in enumerate(node):
            node[i] = _substitute(item, value, row)
        return node
    return node


def expand_definition(definition: dict, seq: Sequence) -> list[dict]:
    """Walk `definition["params"]` recursively, substituting every string
    value via expand_tokens, once per output label (collation applied --
    see _ordered_pairs). Returns one deep-copied bound definition per
    label; `definition` itself is never mutated. len(result) ==
    total_labels(seq)."""
    out = []
    for value, row in _ordered_pairs(seq):
        bound = copy.deepcopy(definition)
        bound["params"] = _substitute(bound.get("params", {}), value, row)
        out.append(bound)
    return out
