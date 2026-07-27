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
    # UNVERIFIED default until physical checkpoint (docs/protocol-notes.md) --
    # classic vs e310bt init strategy is one of the things it resolves.
    printer_init_strategy: Literal["classic", "e310bt"] = "classic"
    # UNVERIFIED default until physical checkpoint -- see raster.py's
    # RasterConfig docstring for the same caveat.
    printer_bit_order: Literal["msb_first", "lsb_first"] = "msb_first"
    printer_flip_pins: bool = False
    # M3: pydantic-settings parses list-typed fields as JSON, not a bare
    # comma-separated string -- the env var value must be a JSON array,
    # quoted so the shell/compose file passes the brackets/quotes through
    # literally, e.g.: CORS_ORIGINS='["https://labels.example.com"]'
    # (multiple origins: '["https://a.example.com","https://b.example.com"]').
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
