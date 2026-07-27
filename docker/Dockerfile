# syntax=docker/dockerfile:1
#
# Build from the repo root:
#   docker build -f docker/Dockerfile -t brother-label-maker:local .
#
# Three stages: `frontend-build` compiles the Vite SPA, `backend-build`
# resolves/builds the Python venv, `runtime` is the image that actually
# ships -- a single container serving both the built SPA and the FastAPI
# backend on :8000. See docs/usb-setup.md for what it takes to let that
# container talk to a real PT-E720BT over USB.
#
# Why three stages and not two: uv itself (the tool, not what it installs)
# is ~53MB and is only needed to *build* the venv, never to run it -- once
# `uv sync` has produced /app/backend/.venv, uvicorn can be exec'd directly
# by putting the venv's bin/ on PATH (see the runtime stage's CMD). Keeping
# uv out of `runtime` and out of the final `COPY --chown` (see below) was
# worth ~115MB off the shipped image; see the report's "Verification 3"
# section for the docker-history diff that found this.

# ---------------------------------------------------------------------------
# Stage 1: frontend-build -- node major matches the dev environment (node -v
# on the machine this was authored on reports v24) so `npm ci` resolves the
# same dependency tree developers see locally.
# ---------------------------------------------------------------------------
FROM node:24-slim AS frontend-build

WORKDIR /fe

# package*.json first so `npm ci` is its own cache layer -- only changes to
# dependencies invalidate it, not every source edit.
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build
# Vite's default outDir is "dist" relative to the project root -> /fe/dist.

# ---------------------------------------------------------------------------
# Stage 2: backend-build -- resolves and installs the Python dependency set
# plus the `labelmaker` project itself into a venv. Never shipped as-is;
# `runtime` below copies only /app/backend (venv + source) out of it, not
# this stage's apt cache, uv binary, or uv's own download cache.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS backend-build

# Pinned uv binary, copied rather than pip-installed so it isn't a Python
# dependency of itself. /uv and /uvx are the only two files this image ships
# (verified: `docker export` of ghcr.io/astral-sh/uv:0.10.9 contains exactly
# /uv and /uvx at the root, nothing else usable as a shell) -- only /uv is
# needed here.
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv

# UV_PYTHON_DOWNLOADS=never: this base image already has exactly one Python
# (3.12, matching backend/.python-version's "3.12"), and the goal is ONE
# interpreter in the final image. Without this, uv's default
# `python-downloads = automatic` can decide to fetch and install its own
# managed CPython the first time `.python-version` is present and it isn't
# 100% sure the system interpreter satisfies it -- silently doubling the
# Python install and defeating the point of using the slim base. Verified by
# building with and without the env var and diffing `docker history`/image
# size; with it set, `uv python list` inside the built image shows only the
# system interpreter at /usr/local/bin/python3.12, and the venv's
# `.venv/bin/python3.12` is a symlink back to it, not a second copy.
ENV UV_PYTHON_DOWNLOADS=never

WORKDIR /app/backend

# Dependency layer: only pyproject.toml/uv.lock/.python-version, so this
# `uv sync` is cached across rebuilds that only touch application code.
# --no-install-project skips building/installing the local `labelmaker`
# package itself -- that needs src/ on disk, which isn't copied yet.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Project layer: the rest of backend/ (src/, assets/ -- fonts the renderer
# needs, tests/ -- harmless extra weight, kept rather than special-cased out
# so this COPY stays a single line matching what .dockerignore already
# trims). Re-run sync so the `labelmaker` package itself is installed into
# the same venv -- as an editable install (uv's default for a local
# project), which is *why* src/ has to ship in the runtime image too: the
# venv's site-packages holds a .pth pointing back at /app/backend/src, not a
# copied package.
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Stage 3: runtime -- python:3.12-slim-bookworm, NOT Alpine. pyusb/libusb and
# resvg-py's native extension are glibc-linked; musl (Alpine) is a documented
# source of pain for both, so bookworm-slim is the floor here even though
# it's larger than Alpine would be.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# libusb-1.0-0 is the runtime half of pyusb's backend (host USB access is a
# separate, non-root story -- see docs/usb-setup.md's udev rule). No curl:
# HEALTHCHECK below is a python urllib one-liner specifically to avoid
# needing it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    DATA_DIR=/data \
    PRINTER_MODE=mock \
    PATH=/app/backend/.venv/bin:$PATH

# Non-root: uid 1000 has no meaningful relationship to host USB permissions
# by itself -- device access for a non-root container process comes from
# the udev rule in docker/99-brother-pte720bt.rules setting MODE="0666" on
# the device node, not from any group membership baked into this image (a
# `plugdev`-style group is host GID-dependent and would be wrong as often as
# right). See docs/usb-setup.md. /data is created (empty) and chowned here,
# before the COPY steps below -- everything under /app itself gets its
# ownership set by those COPY --chown flags instead of a later `chown -R`,
# which on an overlay filesystem would force a full copy-up (duplicate on
# disk) of the ~60MB venv this image is about to receive.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app/backend

# venv + editable-installed `labelmaker` source, built in the previous
# stage -- copied whole (not layered dependency-then-project like the build
# stage) since there's no cache-reuse benefit to splitting it here.
COPY --from=backend-build --chown=app:app /app/backend /app/backend

# Built SPA from stage 1, served by main.py's StaticFiles mount at STATIC_DIR.
COPY --from=frontend-build --chown=app:app /fe/dist /app/static

USER app

VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

# PATH already puts /app/backend/.venv/bin first (see ENV above), so
# `uvicorn` resolves straight to the venv's entry point -- no `uv run` (and
# no uv binary at all) needed in this stage. Chosen over `uv run --no-sync`
# specifically to avoid shipping uv itself in the final image; see the
# stage-count comment at the top of this file.
CMD ["uvicorn", "labelmaker.main:app", "--host", "0.0.0.0", "--port", "8000"]
