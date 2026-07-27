"""GET /api/label-types, POST /api/render/preview.

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
from labelmaker.driver.geometry import dots_to_mm
from labelmaker.render import list_types, preview_png, rasterize, render_definition
from labelmaker.render.document import LabelDefinition

router = APIRouter(tags=["labels"])


@router.get("/label-types")
async def get_label_types() -> list[dict]:
    return [
        {"type": info.type, "title": info.title, "params_schema": info.params_schema}
        for info in list_types()
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
        "width_px": img.width * scale,
        "height_px": img.height * scale,
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
