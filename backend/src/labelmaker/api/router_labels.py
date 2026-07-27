"""GET /api/label-types, GET /api/fonts, GET /api/tapes, POST /api/render/preview.

Preview and print are the same bitmap (see labelmaker.render's module
docstring) -- this endpoint runs the exact same render_definition ->
rasterize -> preview_png pipeline the print worker will later run for the
same definition, just synchronously and without persisting a job.
"""

from __future__ import annotations

import base64

import anyio
from fastapi import APIRouter, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

from labelmaker.api.deps import error_message
from labelmaker.driver.geometry import all_tapes, dots_to_mm
from labelmaker.render import (
    FontInfo,
    list_fonts,
    list_types,
    preview_png,
    rasterize,
    render_definition,
)
from labelmaker.render.document import LabelDefinition, family_name

router = APIRouter(tags=["labels"])


@router.get("/label-types")
async def get_label_types() -> list[dict]:
    # Every LabelTypeInfo field (type/title/category/min_tape_mm/params_schema)
    # passes through as-is -- no per-field allowlist to keep in sync when
    # base.py's LabelTypeInfo shape grows (e.g. category/min_tape_mm, task 2.2).
    return [info.model_dump() for info in list_types()]


@router.get("/fonts")
async def get_fonts() -> list[FontInfo]:
    return list_fonts()


class TapeInfo(BaseModel):
    """GET /api/tapes' shape for one geometry.TapeSpec -- the API-facing
    view of tape geometry, kept separate from TapeSpec itself (which also
    carries driver-only fields like status_width_mm that no client needs)."""

    nominal_mm: float
    family: str
    print_dots: int
    print_mm: float
    max_length_mm: float


@router.get("/tapes")
async def get_tapes() -> list[TapeInfo]:
    return [
        TapeInfo(
            nominal_mm=tape.nominal_mm,
            family=family_name(tape.family),
            print_dots=tape.print_dots,
            print_mm=round(dots_to_mm(tape.print_dots), 1),
            max_length_mm=tape.max_length_mm,
        )
        for tape in all_tapes()
    ]


class PreviewRequest(BaseModel):
    definition: LabelDefinition
    scale: int = Field(default=2, ge=1, le=8)


def _render_and_encode(definition: LabelDefinition, scale: int) -> dict:
    rendered = render_definition(definition)
    img: Image.Image = rasterize(rendered)
    png_bytes = preview_png(img, scale=scale)
    return {
        "png_b64": base64.b64encode(png_bytes).decode("ascii"),
        # SCALED png dimensions (device dots x scale) -- named png_* so the
        # unit trap is visible at the field name itself: never derive mm
        # from these, always read length_mm below (see api/types.ts's
        # PreviewResponse doc on the frontend side of this contract).
        "png_width_px": img.width * scale,
        "png_height_px": img.height * scale,
        "length_mm": round(dots_to_mm(rendered.width_px), 1),
        "warnings": rendered.warnings,
    }


@router.post("/render/preview")
async def render_preview(body: PreviewRequest) -> dict:
    try:
        return await anyio.to_thread.run_sync(_render_and_encode, body.definition, body.scale)
    except (KeyError, ValueError) as exc:
        # ValueError also catches pydantic.ValidationError (a subclass) from
        # renderer.Params.model_validate() inside render_definition -- an
        # invalid `params` payload for the chosen label type surfaces here
        # the same way an unknown type/tape does.
        raise HTTPException(status_code=422, detail=error_message(exc)) from exc
