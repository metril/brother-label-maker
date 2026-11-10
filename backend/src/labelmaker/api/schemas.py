"""Response models shared across the API routers (OpenAPI source of truth).

Field names are the JSON wire names the frontend (frontend/src/api/types.ts)
consumes -- do not rename. Models whose route previously returned a plain
dict mirror that dict's keys exactly.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from labelmaker.render.document import RenderWarning

JobStatus = Literal["queued", "printing", "done", "failed", "canceled"]
JobKind = Literal["print", "feed_cut"]
PrinterMode = Literal["mock", "usb", "remote"]

# Documented `error_code` values of GET /printer/status (derived from where
# driver/transport.py raises; see PrinterNotFoundError.code / TransportError.code).
PRINTER_ERROR_CODES = (
    "printer_busy",
    "printer_disconnected",
    "printer_io_error",
    "status_timeout",
    "bridge_not_configured",
    "bridge_unreachable",
    "bridge_cert_mismatch",
    "bridge_unpaired",
    "bridge_busy",
    "bridge_error",
)


def binary(media_type: str, description: str) -> dict[int | str, dict[str, Any]]:
    """`responses=` entry marking a 200 as raw bytes of `media_type`."""
    return {
        200: {
            "description": description,
            "content": {media_type: {"schema": {"type": "string", "format": "binary"}}},
        }
    }


# -- health / printer -----------------------------------------------------------


class HealthOut(BaseModel):
    status: str = Field(description="Always 'ok' when the process is serving")
    printer_mode: PrinterMode = Field(description="Effective printer transport")
    version: str = Field(description="Installed application version")


class PrinterStatusDetail(BaseModel):
    """Parsed 32-byte printer status block (driver.status.PrinterStatus.to_dict)."""

    model_code: int
    series_code: int
    country_code: int
    error_info1: int
    error_info2: int
    media_width_mm: int
    media_type_raw: int
    media_type: int | None
    number_of_colors: int
    status_type_raw: int
    status_type: int | None
    phase_type: int
    phase_number: int
    tape_color_raw: int
    text_color_raw: int
    raw_hex: str = Field(description="Space-separated hex of the raw status block")
    errors: list[str] = Field(description="Decoded printer error flags")
    has_error: bool
    is_e720bt: bool


class KeepAliveOut(BaseModel):
    enabled: bool
    last_attempt_at: str | None = None
    last_result: str | None = Field(
        default=None, description="'ok', 'skipped_busy', 'error' or null before the first attempt"
    )
    last_error: str | None = None


class PrinterStatusOut(BaseModel):
    connected: bool = Field(description="False when the printer/bridge could not be reached")
    printer_mode: PrinterMode
    status: PrinterStatusDetail | None = Field(
        default=None, description="Printer status block; null when not read"
    )
    error: str | None = Field(default=None, description="Human-readable error, if any")
    error_code: str | None = Field(
        default=None,
        description=(
            "Stable machine-readable classification of `error`; one of: "
            + ", ".join(PRINTER_ERROR_CODES)
            + ". Null when there is no error."
        ),
    )
    keep_alive: KeepAliveOut


class BridgeIdentityOut(BaseModel):
    cert_pem: str = Field(description="This app's PUBLIC client certificate (PEM)")
    fingerprint: str = Field(description="SHA-256 fingerprint of the certificate")


class JobCreatedOut(BaseModel):
    job_id: str = Field(description="Id of the queued print job (uuid4 hex)")


class CancelOut(BaseModel):
    status: Literal["canceled"]


# -- jobs / history ---------------------------------------------------------------


class JobOut(BaseModel):
    """Full print job resource (GET /print/jobs/{id}, GET /history/{id})."""

    id: str
    created_at: str
    status: JobStatus
    error: str | None = None
    definition: Any = Field(description="Stored job snapshot (labels + options) for reprint")
    label_count: int
    chain_mode: str
    strategy: str | None = None
    tape_width_mm: float | None = None
    media_raw_byte: int | None = None
    tape_used_mm: float | None = None
    thumbnail_png_b64: str | None = Field(
        default=None, description="Base64 PNG thumbnail of the first label, if printed"
    )
    kind: JobKind = "print"


class HistoryItemOut(BaseModel):
    """Light list row; omits the (potentially large) `definition`."""

    id: str
    created_at: str
    status: JobStatus
    error: str | None = None
    label_count: int
    chain_mode: str
    strategy: str | None = None
    tape_width_mm: float | None = None
    tape_used_mm: float | None = None
    kind: JobKind = "print"
    thumbnail_url: str | None = Field(
        default=None, description="URL of GET /history/{id}/thumbnail, null if no thumbnail"
    )


class HistoryPageOut(BaseModel):
    items: list[HistoryItemOut]
    page: int
    page_size: int
    total: int = Field(description="Total rows matching the filters")


# -- presets ---------------------------------------------------------------------


class PresetOut(BaseModel):
    id: str
    name: str
    label_type: str
    definition: dict[str, Any] = Field(description="Label-type params")
    tape_width_mm: float | None = Field(default=None, description="null = any tape")
    tape_family: Literal["tze", "hse_2_1", "hse_3_1"]
    favorite: bool
    created_at: str
    updated_at: str


# -- images ----------------------------------------------------------------------


class ImageListItem(BaseModel):
    image_id: str
    width: int
    height: int
    size_bytes: int
    mtime: str = Field(description="Upload mtime, ISO-8601 UTC")


class ImagePageOut(BaseModel):
    items: list[ImageListItem]
    page: int
    page_size: int
    total: int


# -- render / print -----------------------------------------------------------------


class PreviewOut(BaseModel):
    png_b64: str
    png_width_px: int
    png_height_px: int
    length_mm: float
    min_feed_mm: float
    warnings: list[RenderWarning]
    total_labels: int | None = None
    sequence_value: str | None = None


class ExpandOut(BaseModel):
    values: list[str]
    total_labels: int
    samples: list[str] | None = None


class CsvUploadOut(BaseModel):
    columns: list[str]
    rows: list[dict[str, str]]
    row_count: int


class EstimateOut(BaseModel):
    label_count: int
    label_lengths_mm: list[float]
    content_mm: float
    feed_overhead_mm: float
    total_mm: float
    per_label_mm: float
    notes: list[str]


# -- auth ---------------------------------------------------------------------------


class AuthUserOut(BaseModel):
    sub: str | None = None
    name: str | None = None
    email: str | None = None
    exp: int | None = None


class AuthMeOut(BaseModel):
    auth_mode: Literal["none", "oidc"]
    authenticated: bool
    user: AuthUserOut | None = None


# -- settings --------------------------------------------------------------------------


class SettingRow(BaseModel):
    """One settings row. `value` is absent for `homebox_api_key` (never echoed;
    `set` says whether one is configured); `set` is absent for every other row."""

    key: str
    value: str | int | float | bool | list[str] | None = None
    set: bool | None = Field(default=None, description="homebox_api_key only: is a key set")
    source: Literal["db", "env", "default"]
    editable: bool


class SettingsOut(BaseModel):
    settings: list[SettingRow]


# -- homebox ----------------------------------------------------------------------------


class HomeboxStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    reachable: bool | None = None
    healthy: bool | None = None
    version: str | None = None
    error: str | None = None
