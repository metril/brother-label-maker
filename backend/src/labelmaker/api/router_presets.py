"""POST/GET/PUT/DELETE /api/presets, POST /api/presets/{id}/print (task 2.8).

A preset is a saved label TYPE + PARAMS combination a user can reuse without
re-authoring it from scratch -- `definition` is validated the exact same way
a print job's per-label `params` is (renderer.Params.model_validate; see
render/types/base.py's render_definition), NOT a full LabelDefinition
(type+tape+params). `label_type` and `tape_width_mm` are separate, top-level
fields: `label_type` says which renderer's Params `definition` must satisfy,
and `tape_width_mm` is an OPTIONAL tape-width hint (nullable = "any tape",
per the presets table's own migration comment) -- presets don't track a tape
FAMILY at all, so POST .../print (below) can only build a real Tape when
`tape_width_mm` is set, and always assumes family "tze" (Tape's own pydantic
default) when it does.
"""

from __future__ import annotations

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


def _validate_definition(label_type: str, definition: dict) -> None:
    """Raises KeyError for an unknown `label_type` (get_renderer) or
    ValueError/pydantic.ValidationError for a `definition` that doesn't
    satisfy that type's own Params model -- the same two exception types
    (and the same error_message() unwrapping) POST /api/print's own
    _validate_render_side uses for the equivalent check."""
    renderer = get_renderer(label_type)
    renderer.Params.model_validate(definition)


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    label_type: str
    definition: dict
    tape_width_mm: float | None = None
    favorite: bool = False


class PresetUpdate(BaseModel):
    """Every field optional -- PUT is a partial update (matches
    db.update_preset's own **fields kwargs contract): a field OMITTED from
    the request body is left untouched, a field explicitly sent as `null`
    IS applied (e.g. `{"tape_width_mm": null}` clears it back to "any
    tape"). The router reads which fields were actually sent via
    `body.model_dump(exclude_unset=True)`, not by checking `is not None`.
    """

    name: str | None = Field(default=None, min_length=1, max_length=80)
    label_type: str | None = None
    definition: dict | None = None
    tape_width_mm: float | None = None
    favorite: bool | None = None


class PresetPrintRequest(BaseModel):
    options: PrintOptions = Field(default_factory=PrintOptions)
    serialization: Sequence | None = None


@router.post("", status_code=201)
async def create_preset(body: PresetCreate, db: DbDep) -> dict:
    try:
        _validate_definition(body.label_type, body.definition)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc

    return await db.create_preset(
        name=body.name,
        label_type=body.label_type,
        definition=body.definition,
        tape_width_mm=body.tape_width_mm,
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
    # Optional body: `{options, serialization}` are both themselves optional
    # (see PresetPrintRequest), so the whole body may be omitted entirely --
    # `| None = None` is FastAPI's documented way to make a pydantic-model
    # body param optional (no body sent -> None), rather than the client
    # being forced to POST an empty `{}`.
    body: PresetPrintRequest | None = None,
) -> dict:
    preset = await db.get_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="preset not found")
    if preset["tape_width_mm"] is None:
        raise HTTPException(
            status_code=422,
            detail="preset has no tape_width_mm set; cannot print without one",
        )

    label = LabelDefinition(
        type=preset["label_type"],
        # family always "tze" (Tape's own default) -- presets don't track a
        # tape family, only an optional width (see this module's docstring).
        tape=Tape(width_mm=preset["tape_width_mm"]),
        params=preset["definition"],
    )
    options = body.options if body is not None else PrintOptions()
    serialization = body.serialization if body is not None else None
    print_request = PrintRequest(labels=[label], options=options, serialization=serialization)
    # Delegates to POST /api/print's OWN handler, not a re-implementation of
    # it -- guarantees this endpoint's 202 {job_id} contract can never drift
    # from the real one (same validation, same tape-consistency check, same
    # persistence/broadcast/enqueue sequence).
    return await router_print.create_print_job(print_request, db, queue, bus, config)
