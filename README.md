# Brother PT-E720BT Label Studio

A self-hosted web app for designing and printing labels on a **Brother
PT-E720BT** label printer over USB. Everything runs as a single Docker
container (amd64 + arm64): a FastAPI backend serving both the API and the
built SPA, backed by SQLite for presets/history.

The printer driver is a from-scratch implementation of the Brother P-touch
raster protocol — the PT-E720BT has no existing open-source driver, so the
whole raster pipeline (init handshake, packbits, chaining, cut behavior) was
built from the printer's own status responses and adjacent-model raster
manuals, then verified against real hardware (see
[Physical checkpoint status](#physical-checkpoint-status) below).

**What it can do:**

- Design and preview 11 label types pixel-exact in the browser: `text`,
  `barcode`, `patch_panel`, `punch_down`, `faceplate`, `terminal_block`,
  `breaker_box`, `cable_wrap`, `cable_flag`, plus two HomeBox-flavored types
  (`homebox_location`, `homebox_asset`).
- QR, Code128/39, and DataMatrix barcodes (decode-verified), image upload
  with Floyd-Steinberg dithering, and a 60-icon symbol library.
- BarTender-style serialization (numeric/alpha/list/CSV) to print a
  sequence of labels from one template.
- A multi-label job tray with three chain modes and tape-usage estimates,
  plus presets and print history with reprint.
- Optional [HomeBox](https://github.com/sysadminsmedia/homebox) integration:
  browse HomeBox entities and print labels for them directly, or run as a
  HomeBox External Label Service so HomeBox's own "print label" button
  renders through this app.

## Contents

- [Quick start (mock mode, no printer)](#quick-start-mock-mode-no-printer)
- [Real printer setup](#real-printer-setup)
- [Environment variable reference](#environment-variable-reference)
- [Security notes](#security-notes)
- [Container image](#container-image)
- [Physical checkpoint status](#physical-checkpoint-status)
- [Development](#development)

## Quick start (mock mode, no printer)

`PRINTER_MODE=mock` is the default baked into the image — you can design and
preview labels in the browser with zero hardware attached. Build the image
from the repo (the GHCR image below exists from the first tagged release
onward):

```bash
docker build -f docker/Dockerfile -t brother-label-maker:local .
docker run -d --name labelmaker \
  -p 8000:8000 \
  -v labeldata:/data \
  brother-label-maker:local
```

Open <http://localhost:8000>. Every render, print job, preset, and history
entry works exactly as it would with a real printer attached — `mock` mode
just skips the final USB write, so nothing prints.

Equivalent as a compose service (no USB passthrough needed for mock mode):

```yaml
services:
  labelmaker:
    image: ghcr.io/metril/brother-label-maker:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      PRINTER_MODE: mock   # the default — set explicitly for clarity
    volumes:
      - labeldata:/data

volumes:
  labeldata: {}
```

## Real printer setup

**1. Install the udev rule on the Docker host.** The container never runs
as root and is never `--privileged`, so the host has to grant non-root USB
access before the container can open the printer at all:

```bash
sudo cp docker/99-brother-pte720bt.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
# then unplug and replug the printer so udev re-evaluates the new rule
```

Verify it took effect:

```bash
lsusb -d 04f9:224a
# Bus 001 Device 007: ID 04f9:224a Brother Industries, Ltd

ls -l /dev/bus/usb/001/007
# crw-rw-rw- 1 root root 189, 6 ...  /dev/bus/usb/001/007
```

`crw-rw-rw-` (mode `0666`) is what makes the device node writable by the
container's non-root `app` user. Full troubleshooting (permission errors,
hotplug/power-cycle caveats, a zero-libusb `usblp` fallback) is in
[docs/usb-setup.md](docs/usb-setup.md) — read it before filing a "printer
not found" issue against yourself.

**2. Run with USB passthrough.** A GHCR-based deployment looks like this
(shipped ready-to-run as `docker/docker-compose.ghcr.yml`) —
the repo's own `docker/docker-compose.yml` is the build-from-source variant
of the same shape (it uses `build:` instead of `image:` and carries the
verified printer-protocol env knobs as comments):

```yaml
services:
  labelmaker:
    image: ghcr.io/metril/brother-label-maker:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      PRINTER_MODE: usb
    volumes:
      # Bind-mount the *directory*, not a specific device node -- a
      # `/dev/bus/usb/001/005`-style path renumbers on every replug/reboot.
      - /dev/bus/usb:/dev/bus/usb
      - labeldata:/data
    # Grants the container permission to open USB device nodes (major 189)
    # without `--privileged` (which hands over the ENTIRE host device
    # namespace for one device) and without a `devices:` list (which pins a
    # specific, unstable bus/device path). Actual non-root write permission
    # on the node still comes from the udev rule installed in step 1 above --
    # this cgroup rule only lets the container's cgroup touch USB at all.
    device_cgroup_rules:
      - "c 189:* rmw"

volumes:
  labeldata: {}
```

To run the repo's build-from-source compose file instead:

```bash
docker compose -f docker/docker-compose.yml up --build -d
```

(`--build` applies to that file's `build:` section; a compose file using the
GHCR `image:` as above just needs `up -d`.)

See [docs/usb-setup.md](docs/usb-setup.md) for the full reasoning behind
this shape (why a directory mount + cgroup rule instead of `--privileged` or
a pinned `devices:` entry) and what each failure mode in the table there
actually means.

**Protocol defaults are already correct — no tuning needed.** As of the
first real print (2026-07-28), the PT-E720BT's init strategy, raster bit
order, and pin mapping are all hardware-verified and baked in as the
`AppConfig` defaults: `PRINTER_INIT_STRATEGY=classic`,
`PRINTER_BIT_ORDER=msb_first`, `PRINTER_FLIP_PINS=true`. You should not need
to set any of these three env vars for a stock PT-E720BT — they exist as
override knobs for experimentation, not normal deployment.

## Environment variable reference

`AppConfig` (`backend/src/labelmaker/config.py`) reads every setting
directly from the process environment with no prefix — the env var name is
just the field name, uppercased.

### Core

| Env var | Default | Meaning |
|---|---|---|
| `PRINTER_MODE` | `mock` | `mock` (no hardware, safe for design/preview) or `usb` (talks to a real printer). |
| `DATA_DIR` | `./data` (image sets this to `/data`, matching the Dockerfile's `VOLUME /data`) | Where the SQLite db and print-job artifacts live. |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | JSON array (not a bare string) of allowed browser origins — see the [security warning](#security-notes) below before changing this. |

`STATIC_DIR` is also read (via `os.environ`, not `AppConfig`) but isn't
something you should need to set — the shipped image already bakes it to
`/app/static`, where the built SPA lives.

### Printer protocol knobs

**Verified 2026-07-28 — don't touch unless experimenting.** These are the
three raster-encoding decisions the physical checkpoint resolved; the
defaults below are correct for a stock PT-E720BT.

| Env var | Default | Meaning |
|---|---|---|
| `PRINTER_INIT_STRATEGY` | `classic` | Raster init sequence (`classic` = PackBits + `ESC i M`/`ESC i d`; `e310bt` = the RAW/`MAGIC`-packet alternative, never needed on this printer). |
| `PRINTER_BIT_ORDER` | `msb_first` | Bit order within each raster pin byte. A wrong value scrambles glyphs, it doesn't mirror them. |
| `PRINTER_FLIP_PINS` | `true` | Whether row 0 of a rendered label maps to the low- or high-pin end of the print head. A wrong value mirrors the print across the tape width. |

### HomeBox integration

Enabled only when **both** URL and key are set; unset either one and the
HomeBox UI in this app stays hidden.

| Env var | Default | Meaning |
|---|---|---|
| `HOMEBOX_URL` | unset | Your HomeBox instance's root URL, e.g. `https://homebox.example.com`. |
| `HOMEBOX_API_KEY` | unset | An `hb_`-prefixed static API key (HomeBox v0.26+). Mint one from your HomeBox user profile's API Keys page (or `POST /v1/users/api-keys`). It stays server-side — the browser only ever talks to this app's `/api/homebox/*` proxy routes, never HomeBox directly. |

**HomeBox-side gotcha:** HomeBox v0.26+ requires its own
`HBOX_AUTH_API_KEY_PEPPER` (32+ random characters) to be set on the *HomeBox*
server before static API keys work at all — without it, HomeBox itself
crash-loops on startup. This is a HomeBox env var, not one of ours, but it's
the single most common reason "mint an API key" fails on a fresh v0.26+
HomeBox install. Set it before creating the key this app needs.

`qr_base_url` is **not** an env var — it's a database-backed app setting
(`PUT /api/homebox/settings` / this app's own settings page), because it
needs to be changeable without a restart and because HomeBox's own QR
base-URL resolution is fragile behind a reverse proxy. Unset, it falls back
to `HOMEBOX_URL`.

### HomeBox External Label Service (ELS)

| Env var | Default | Meaning |
|---|---|---|
| `ELS_ENABLED` | `false` | Registers `GET /api/els/label` so HomeBox can delegate its own label rendering to this app. |
| `ELS_TAPE_MM` | `24.0` | Tape width (mm) ELS labels render at — HomeBox's own width/height/DPI query params describe its *own* internal renderer's canvas and are not honored here. |

**Security caveat:** HomeBox's ELS caller sends this endpoint a plain,
unauthenticated `GET` — that's HomeBox's own design (`fetchLabelFromURL`),
not a shortcut on our side, and there's no way to make it otherwise. `/api/els/label`
is therefore exempt from the OIDC gate below even in `AUTH_MODE=oidc`
(gating it would just break every HomeBox print button with no security
benefit, since HomeBox has no browser session to present). Leave
`ELS_ENABLED=false` unless HomeBox can actually reach this app — don't
expose it to the open internet.

To wire it up, point HomeBox's own `HBOX_LABEL_MAKER_LABEL_SERVICE_URL` at
this app's `/api/els/label` endpoint (e.g.
`http://labelmaker:8000/api/els/label` on a shared Docker network).

### Auth (optional — off by default)

| Env var | Default | Meaning |
|---|---|---|
| `AUTH_MODE` | `none` | `none` = today's zero-auth LAN behavior, byte-for-byte (no session middleware is even added). `oidc` = gate every `/api/*` route (except `/api/health`, `/api/auth/*`, `/api/els/*`) behind a signed session cookie. |
| `OIDC_ISSUER` | unset, **required if** `AUTH_MODE=oidc` | Your IdP's issuer URL, e.g. `https://auth.example.com/realms/labelmaker`. The rest of the endpoints are discovered from `{issuer}/.well-known/openid-configuration`. |
| `OIDC_CLIENT_ID` | unset, **required if** `AUTH_MODE=oidc` | OIDC client id. |
| `OIDC_CLIENT_SECRET` | unset, **required if** `AUTH_MODE=oidc` | Confidential client secret — stays server-side. |
| `OIDC_SCOPES` | `openid profile email` | Space-separated scopes sent to the IdP's authorize endpoint. `openid` must stay in this list. |
| `SESSION_SECRET` | unset, **required if** `AUTH_MODE=oidc`, min 32 chars | Signs the session cookie. Generate with `openssl rand -hex 32`. A weak secret lets anyone on the network forge a session and bypass auth entirely — the HMAC is the whole gate. |
| `SESSION_MAX_AGE_S` | `28800` (8h), min `300` | This app's own session lifetime, in seconds. Deliberately independent of the IdP's `id_token` expiry (which most IdPs cap at a few minutes). Values under 300 fail validation at startup. |
| `SESSION_COOKIE_SECURE` | `false` | Set `true` when serving over TLS, so the session cookie is marked `Secure` and never rides plain HTTP. Recommended `true` for any real (non-LAN-only) deployment. |

If `AUTH_MODE=oidc` is set but any of the four required fields above is
missing, the app **fails at startup** (not on the first login attempt) with
a clear error naming which env var is missing.

## Security notes

- **LAN-first by default.** With `AUTH_MODE=none` (the default), there is no
  authentication at all — anyone who can reach the container's port 8000
  can design, print, and browse HomeBox data (if configured). This is meant
  for a trusted home/LAN network. Put it behind OIDC (or a reverse proxy
  with its own auth) before exposing it beyond that.
- **Enabling OIDC** gates every API route except health, auth, and ELS
  behind a signed session — see the [Auth table](#auth-optional--off-by-default) above for the four
  required env vars.
- **Never set `CORS_ORIGINS` to `'["*"]'`.** This app enables
  `allow_credentials=True` on its CORS middleware (required for the session
  cookie to work cross-origin at all). Combined with a wildcard origin,
  browsers' CORS credentialed-request rules push most CORS libraries
  (Starlette's included) to *echo back whatever `Origin` header the request
  sent* rather than literally sending `*` — which means a wildcard here
  doesn't just allow "anyone read-only", it lets **any website on the
  internet ride a signed-in user's session** if they have it open in
  another tab. Only ever list specific origins you actually trust.
- **ELS exposure.** `/api/els/label` is unauthenticated by HomeBox's own
  design (see the [ELS section](#homebox-external-label-service-els) above) and cannot be gated without
  breaking the integration. Keep `ELS_ENABLED=false` unless HomeBox can
  reach this app on a network you control.

## Container image

Published to GHCR on every release, built for `linux/amd64` and
`linux/arm64` (`.github/workflows/release.yml`):

```
ghcr.io/metril/brother-label-maker:latest
ghcr.io/metril/brother-label-maker:<major>.<minor>
ghcr.io/metril/brother-label-maker:<version>          # e.g. 1.2.3
```

Releases are automatic: every merge to `main` that contains `feat`, `fix`,
`perf` or `revert` commits (conventional commits; `!:` / `BREAKING CHANGE`
bumps major) makes `.github/workflows/auto-release.yml` compute the next
version, push the `v<version>` tag, create a GitHub Release with generated
notes, and publish `:<version>`, `:<major>.<minor>` and `:latest`. The first
release is `0.1.0`. Pushes with only `docs`/`chore`/`test`/`ci`/`refactor`/
`style` commits publish nothing. Keep PR titles and commit messages in conventional-commit form so they are picked up. Pushing a `v*` tag by hand still works too.

`latest` only moves on a new release (automatic, or a manual non-prerelease
tag push) — running the release workflow manually (`workflow_dispatch`)
against an old tag never moves it backwards.

Two one-time notes for the maintainer: the image exists only from the first
`v*` tag push onward, and GHCR packages created by `GITHUB_TOKEN` are
**private by default** — after the first publish, flip the package to Public
(repo → Packages → package settings) or anonymous `docker pull` will 401.

To build locally instead of pulling from GHCR:

```bash
docker build -f docker/Dockerfile -t brother-label-maker:local .
```

(Build from the **repo root** — the Dockerfile expects both `backend/` and
`frontend/` in its build context.)

## Physical checkpoint status

The driver was built entirely from research and adjacent-printer manuals
before ever touching real hardware — every place it had to guess is marked
`# UNVERIFIED:` in the source. As of 2026-07-28, **the printer has printed**:
the first real label (browser path, all defaults, 24mm TZe tape) resolved
the init-strategy, bit-order, and pin-mapping questions all at once (see
[docs/protocol-notes.md](docs/protocol-notes.md)'s RESULTS section for the
full reasoning) — those are now the verified `AppConfig` defaults described
above.

Remaining hardware checkpoints (raw status/media-byte decode, chain/cut
behavior, one-print-of-each-type end-to-end, tape-usage estimator
calibration) are tracked in
[docs/project-handoff.md](docs/project-handoff.md) §4. Every still-unverified
value in the code carries the same grep-able marker:

```bash
grep -rn "# UNVERIFIED:" backend/src/labelmaker/
```

## Development

```bash
# backend (mock printer, no hardware required)
cd backend && uv run uvicorn labelmaker.main:app --port 8000

# frontend dev server (proxies /api to :8000)
cd frontend && npm run dev          # http://localhost:5173

# tests + lint (1265 backend tests, 233 frontend tests, all green as of this writing)
cd backend  && uv run pytest -q && uv run ruff check .
cd frontend && npm run test && npm run lint && npm run typecheck && npm run build
```

Anything byte-exact — raster frames, printer job streams, rendered label
PNGs — is covered by golden-file tests whose expected bytes are hand-derived
literals with derivation comments in the test itself, never bytes produced
by calling the code under test. That means a regression in the encoder
actually fails the test instead of the test tautologically re-deriving the
same (now-wrong) answer.
