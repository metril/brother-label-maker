"""Fixed filesystem locations -- the app reads no environment variables.

`default_data_dir()`: `/data` (the container volume) when it is a writable
directory, else `<repo>/data` for local development. `find_static_dir()`:
the built SPA, `<repo>/frontend/dist` first, then the image's `/app/static`.
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/src/labelmaker/paths.py -> parents[3] == repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTAINER_DATA_DIR = Path("/data")
CONTAINER_STATIC_DIR = Path("/app/static")


def default_data_dir() -> Path:
    if CONTAINER_DATA_DIR.is_dir() and os.access(CONTAINER_DATA_DIR, os.W_OK | os.X_OK):
        return CONTAINER_DATA_DIR
    return REPO_ROOT / "data"


def find_static_dir() -> Path | None:
    for candidate in (REPO_ROOT / "frontend" / "dist", CONTAINER_STATIC_DIR):
        if candidate.is_dir():
            return candidate
    return None
