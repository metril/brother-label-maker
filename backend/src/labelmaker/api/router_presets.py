"""POST/GET/PUT/DELETE /api/presets, POST /api/presets/{id}/print (task 2.8).

A preset is a saved label TYPE + PARAMS combination a user can reuse without
re-authoring it from scratch -- `definition` is validated the exact same way
a print job's per-label `params` is (renderer.Params.model_validate; see
render/types/base.py's render_definition), NOT a full LabelDefinition
(type+tape+params). `label_type` and `tape_width_mm`/`tape_family` are
separate, top-level fields: `label_type` says which renderer's Params
`definition` must satisfy; `tape_width_mm` is an OPTIONAL tape-width hint
(nullable = "any tape", per db/database.py's presets-section docstring) and
`tape_family` (0002_preset_tape_family.sql, review fix-up) is NOT nullable
(every preset has SOME family, "tze" by default). Both are validated at
create/update time against the real tape table (Tape.resolve()) so a
preset with an impossible (family, width) combination 422s immediately
instead of surprising POST .../print later.

POST .../print builds a real Tape from the preset's own tape_width_mm/
tape_family when the request body doesn't supply one -- but a caller MAY
also pass an explicit `tape` in the body (review fix-up), which always
wins: this is the only way to print an "any tape" preset (tape_width_mm is
null) at all, and the only way to pick a DIFFERENT tape than whatever the
preset happens to have saved.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from labelmaker.api import router_print
from labelmaker.api.deps import AppConfigDep, BusDep, DbDep, QueueDep, error_message
from labelmaker.api.router_print import PrintOptions, PrintRequest
from labelmaker.render import get_renderer
from labelmaker.render.document import LabelDefinition, Tape
from labelmaker.render.serialize import Sequence

router = APIRouter(prefix="/presets", tags=["presets"])

_TapeFamily = Literal["tze", "hse_2_1", "hse_3_1"]

# PUT fields that the presets table does NOT allow NULL for (everything
# else -- currently just `tape_width_mm` and `definition` -- either IS
# nullable in the schema, or is already guarded by its own validation step;
# see update_preset's `definition`/`label_type` re-validation block below,
# which rejects `definition=null` as a pydantic ValidationError and
# `label_type=null` as an "unknown label type" KeyError either way, just
# with a less direct message than the explicit check below gives).
_NON_NULLABLE_UPDATE_FIELDS = ("name", "label_type", "favorite", "tape_family")


def _validate_definition(label_type: str, definition: dict) -> None:
    """Raises KeyError for an unknown `label_type` (get_renderer) or
    ValueError/pydantic.ValidationError for a `definition` that doesn't
    satisfy that type's own Params model -- the same two exception types
    (and the same error_message() unwrapping) POST /api/print's own
    _validate_render_side uses for the equivalent check."""
    renderer = get_renderer(label_type)
    renderer.Params.model_validate(definition)


def _validate_tape_width(family: str, width_mm: float) -> None:
    """Raises ValueError if no real TapeSpec exists at this (family,
    width_mm) combination -- reuses Tape.resolve()'s own exact-nominal-mm
    lookup (render/document.py) so this check can never drift from the one
    POST /api/print's own rendering path relies on. Review fix-up: without
    this, an impossible preset (e.g. hse_3_1 at a width only tze has) would
    only fail later, at print time, with a much less direct error."""
    Tape(width_mm=width_mm, family=family).resolve()


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    label_type: str
    definition: dict
    tape_width_mm: float | None = None
    tape_family: _TapeFamily = "tze"
    favorite: bool = False


class PresetUpdate(BaseModel):
    """Every field optional -- PUT is a partial update (matches
    db.update_preset's own **fields kwargs contract): a field OMITTED from
    the request body is left untouched. Of the fields that ARE sent
    explicitly as `null`, only `tape_width_mm` is actually nullable in the
    schema (clears back to "any tape") -- `name`/`label_type`/`favorite`/
    `tape_family` are all `NOT NULL` columns, so an explicit null for any
    of those is rejected with 422 (review fix-up: this used to reach
    sqlite3 unguarded, surfacing as a raw 500 for `name`/`label_type`, or
    silently coercing `favorite` to False via `int(bool(None))`). The
    router reads which fields were actually SENT via
    `body.model_dump(exclude_unset=True)`, not by checking `is not None`.
    """

    name: str | None = Field(default=None, min_length=1, max_length=80)
    label_type: str | None = None
    definition: dict | None = None
    tape_width_mm: float | None = None
    tape_family: _TapeFamily | None = None
    favorite: bool | None = None


class PresetPrintRequest(BaseModel):
    options: PrintOptions = Field(default_factory=PrintOptions)
    serialization: Sequence | None = None
    # Review fix-up: an explicit tape here always wins over the preset's
    # own tape_width_mm/tape_family -- the only way to print an "any tape"
    # preset (tape_width_mm is null) at all, and a way to override a
    # preset's saved tape without editing the preset itself.
    tape: Tape | None = None


@router.post("", status_code=201)
async def create_preset(body: PresetCreate, db: DbDep) -> dict:
    try:
        _validate_definition(body.label_type, body.definition)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc

    if body.tape_width_mm is not None:
        try:
            _validate_tape_width(body.tape_family, body.tape_width_mm)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=error_message(exc)) from exc

    return await db.create_preset(
        name=body.name,
        label_type=body.label_type,
        definition=body.definition,
        tape_width_mm=body.tape_width_mm,
        tape_family=body.tape_family,
        favorite=body.favorite,
    )


@router.get("")
async def list_presets(
    db: DbDep, label_type: str | None = None, q: str | None = None
) -> list[dict]:
    return await db.list_presets(label_type=label_type, q=q)


@router.get("/{preset_id}")
async def get_preset(preset_id: str, db: DbDep) -> dict:
    preset = await db.get_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="preset not found")
    return preset


@router.put("/{preset_id}")
async def update_preset(preset_id: str, body: PresetUpdate, db: DbDep) -> dict:
    existing = await db.get_preset(preset_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="preset not found")

    fields = body.model_dump(exclude_unset=True)

    for field in _NON_NULLABLE_UPDATE_FIELDS:
        if field in fields and fields[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be set to null")

    # Re-validate whenever EITHER half of the (label_type, definition) pair
    # changes -- a `label_type` change alone must still check the EXISTING
    # definition against the NEW type's Params (it may no longer satisfy
    # it), and a `definition` change alone must still check against
    # whichever label_type is in effect.
    if "definition" in fields or "label_type" in fields:
        label_type = fields.get("label_type", existing["label_type"])
        definition = fields.get("definition", existing["definition"])
        try:
            _validate_definition(label_type, definition)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=error_message(exc)) from exc

    # Likewise for the (tape_family, tape_width_mm) pair -- re-check
    # against the real tape table whenever either changes, using whichever
    # value (new or existing) is in effect for the one that didn't.
    if "tape_width_mm" in fields or "tape_family" in fields:
        width = fields.get("tape_width_mm", existing["tape_width_mm"])
        family = fields.get("tape_family", existing["tape_family"])
        if width is not None:
            try:
                _validate_tape_width(family, width)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=error_message(exc)) from exc

    if not fields:
        return existing
    return await db.update_preset(preset_id, **fields)


@router.delete("/{preset_id}", status_code=204)
async def delete_preset(preset_id: str, db: DbDep) -> Response:
    deleted = await db.delete_preset(preset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="preset not found")
    return Response(status_code=204)


@router.post("/{preset_id}/print", status_code=202)
async def print_preset(
    preset_id: str,
    db: DbDep,
    queue: QueueDep,
    bus: BusDep,
    config: AppConfigDep,
    # Optional body: every field (including `tape`, review fix-up) is
    # itself optional, so the whole body may be omitted entirely --
    # `| None = None` is FastAPI's documented way to make a pydantic-model
    # body param optional (no body sent -> None), rather than the client
    # being forced to POST an empty `{}`.
    body: PresetPrintRequest | None = None,
) -> dict:
    preset = await db.get_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="preset not found")

    # Review fix-up: an explicit `tape` in the body always wins -- the only
    # way to print an "any tape" preset (tape_width_mm is null) at all, and
    # a way to print a saved preset against a DIFFERENT tape than the one
    # it has stored. Falls back to the preset's own tape_width_mm/
    # tape_family only when the body supplies none; 422 only when BOTH are
    # absent (nothing to build a Tape from either way).
    tape = body.tape if body is not None else None
    if tape is None:
        if preset["tape_width_mm"] is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "preset has no tape_width_mm set and no `tape` was given in the "
                    "request body; cannot print without one"
                ),
            )
        tape = Tape(width_mm=preset["tape_width_mm"], family=preset["tape_family"])

    label = LabelDefinition(type=preset["label_type"], tape=tape, params=preset["definition"])
    options = body.options if body is not None else PrintOptions()
    serialization = body.serialization if body is not None else None
    print_request = PrintRequest(labels=[label], options=options, serialization=serialization)
    # Delegates to POST /api/print's OWN handler, not a re-implementation of
    # it -- guarantees this endpoint's 202 {job_id} contract can never drift
    # from the real one (same validation, same tape-consistency check, same
    # persistence/broadcast/enqueue sequence).
    return await router_print.create_print_job(print_request, db, queue, bus, config)
