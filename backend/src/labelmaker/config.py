"""App configuration: a pydantic-settings model read from the process
environment, field names matching the planned docker-compose service's env
vars exactly -- no prefix (`PRINTER_MODE`, not e.g. `LABELMAKER_PRINTER_MODE`).

`get_config()` is a process-wide cached accessor for the real server entry
point (`main.app = create_app()`); tests never use it -- they build their own
`AppConfig(...)` with a tmp `data_dir` and pass it straight to `create_app()`,
so cached env-derived state never leaks between tests.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    printer_mode: Literal["mock", "usb"] = "mock"
    data_dir: Path = Path("./data")
    # Verified 2026-07-28 (first physical print, browser path, 24mm TZe):
    # classic printed successfully; e310bt remains untested.
    printer_init_strategy: Literal["classic", "e310bt"] = "classic"
    # Verified 2026-07-28: msb_first printed clean glyphs (a wrong bit order
    # scrambles within each 8-pin byte -- see docs/protocol-notes.md RESULTS).
    printer_bit_order: Literal["msb_first", "lsb_first"] = "msb_first"
    # Verified 2026-07-28: flip_pins=False printed mirrored across the tape
    # width; True is correct for this printer. RasterConfig's dataclass
    # default stays False (library-neutral; driver goldens pin it) -- this
    # AppConfig default is the policy layer every real print goes through.
    printer_flip_pins: bool = True
    # HomeBox integration (Phase 3) -- enabled iff BOTH are set. The URL is
    # the instance root (https://homebox.example.com); the key is an
    # hb_-prefixed static API key (HomeBox v0.26+ user settings). The key
    # stays server-side: the browser only ever talks to this app's
    # /api/homebox/* proxy routes.
    homebox_url: str | None = None
    homebox_api_key: str | None = None
    # M3: pydantic-settings parses list-typed fields as JSON, not a bare
    # comma-separated string -- the env var value must be a JSON array,
    # quoted so the shell/compose file passes the brackets/quotes through
    # literally, e.g.: CORS_ORIGINS='["https://labels.example.com"]'
    # (multiple origins: '["https://a.example.com","https://b.example.com"]').
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
