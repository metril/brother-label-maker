# Brother PT-E720BT Label Studio

A self-hosted web app for designing and printing labels on a **Brother
PT-E720BT** label printer over USB. Everything runs as a single Docker
container (amd64 + arm64): a FastAPI backend serving both the API and the
built SPA, backed by SQLite for presets/history.

**HTTP API:** see [API.md](API.md) (auth, errors, WebSocket events, endpoint
reference); the schema is [openapi.json](openapi.json), live at `/docs`.

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
  renders through this app. A phone-friendly Capture page scans a label's QR
  code and attaches a photo to that HomeBox item.

## Contents

- [Quick start (mock mode, no printer)](#quick-start-mock-mode-no-printer)
- [Real printer setup](#real-printer-setup)
- [Configuration](#configuration)
- [Security notes](#security-notes)
- [Container image](#container-image)
- [Physical checkpoint status](#physical-checkpoint-status)
- [Development](#development)

## Quick start (mock mode, no printer)

Mock printer mode is the default — you can design and
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
of the same shape (it uses `build:` instead of `image:`):

```yaml
services:
  labelmaker:
    image: ghcr.io/metril/brother-label-maker:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
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

**3. Select the printer.** Open **Settings → Printer** and set the mode to
**USB**. No environment variables are involved.

Printer on a Raspberry Pi instead of the server? See
[Printer on a Raspberry Pi](#printer-on-a-raspberry-pi).

See [docs/usb-setup.md](docs/usb-setup.md) for the full reasoning behind
this shape (why a directory mount + cgroup rule instead of `--privileged` or
a pinned `devices:` entry) and what each failure mode in the table there
actually means.

**Protocol defaults are already correct — no tuning needed.** The PT-E720BT's
init strategy, raster bit order and pin mapping are hardware-verified (first
real print, 2026-07-28) and are the defaults on the Settings page. Change them
there only to experiment.

## Printer on a Raspberry Pi

Run the app on a server and plug the PT-E720BT into a Raspberry Pi or other
Linux box. A small bridge on the Pi owns the USB connection, and the app talks
to it in Remote mode. Printing, status, cut and keep-awake work as
they do over local USB.

Traffic uses mutual TLS 1.3 with pinned self-signed certificates. Each side
generates its own key, only public certificates are exchanged, and each side
accepts only the one certificate it was paired with. There is no plaintext
mode. Private keys stay on their host (`<data dir>/bridge/client.key` on the
app, `/data/bridge.key` on the bridge).

Set `BRIDGE` to shorten the commands below, on the Pi, with this repo's
`docker/docker-compose.bridge.yml`:

```bash
BRIDGE="docker compose -f docker/docker-compose.bridge.yml"
```

1. **Get the bridge certificate** on the Pi:
   `$BRIDGE run --rm -T bridge python -m labelmaker.driver.bridge show-cert`
2. **Configure the app:** in Settings, set the printer mode to **Remote**, enter
   the bridge address (`host`, `host:port` or `[v6]:port`; default port 9177),
   paste the bridge certificate, and save. The page then shows this app's
   certificate.
3. **Pair:** copy the app's certificate to `app.crt` on the Pi, then:
   `$BRIDGE run --rm -T bridge python -m labelmaker.driver.bridge pair - < app.crt`
4. **Start the bridge:** `$BRIDGE up -d`. It refuses to start until step 3 is done.
5. **Check:** Diagnostics or `GET /api/v1/printer/status` shows `connected: true`.

The bridge has no environment config: it listens on port 9177, keeps its files
in `/data` and binds `0.0.0.0`. Outside Docker, the optional flags `--port`,
`--dir` and `--host` go before the subcommand, e.g.
`python -m labelmaker.driver.bridge --dir ~/bridge serve`.

**Behavior**

- One client at a time. A second waits up to 5s, then gets "busy".
- The bridge releases USB when the client disconnects or is idle for 60s.
- Writes are never retried. A network drop mid-print fails the job rather than
  risk a duplicate label.
- Prefer a wired connection for the Pi.

**Replacing a certificate:** delete `bridge.key` and `bridge.crt` from the bridge
volume, or `client.key` and `client.crt` from `<data dir>/bridge`, then pair
again and restart the bridge. Pinning a new app certificate revokes the old one.

| Symptom | Cause and fix |
|---|---|
| "not paired" | The bridge doesn't trust this app's certificate. Redo step 3 and restart the bridge. |
| "bridge certificate does not match the pinned certificate" | The saved certificate is stale. Re-run step 1 and paste it in Settings. |
| "cannot reach printer bridge" | Wrong address or port, bridge not running, or a firewall on 9177. |
| "bridge is serving another client" | Another app or CLI is connected. Wait or stop it. |
| "no USB printer found" or permission errors on the Pi | See `docs/usb-setup.md`. If `usblp` can't be detached in the container, blacklist it on the Pi. |

## Configuration

The app reads **no environment variables**. Everything is configured on the
**Settings page** and stored in the database: printer mode and bridge, HomeBox,
the External Label Service, authentication (OIDC), session options and CORS
origins. Paths are fixed: data lives in `/data` in the container (the
`VOLUME`), the built SPA is served from `/app/static`. Outside Docker the data
directory is `<repo>/data` unless `/data` exists and is writable.

**BREAKING (upgrading from older versions):** old env vars (`DATA_DIR`,
`STATIC_DIR`, `CORS_ORIGINS`, `AUTH_MODE`, `OIDC_*`, `SESSION_*`, and the earlier
`PRINTER_*`, `HOMEBOX_*`, `ELS_*`) are now ignored and nothing is imported from
them. Mount your existing data at `/data`, then re-enter CORS origins and
authentication on the Settings page and remove the vars from your compose file.
Until you do, the app runs with auth off and default CORS.

**Locked out?** Reset authentication to `none` from the host, then restart:

```bash
docker exec <container> labelmaker reset-auth && docker restart <container>
# add --rotate-session-secret to also sign everyone out
```

The server assumes a **single worker** (the default `uvicorn` command): settings
changes apply live in that process only.

### HomeBox and the External Label Service

Both are configured on the Settings page. HomeBox is enabled once a URL and
API key are saved there; until then the HomeBox UI stays hidden.

**HomeBox-side gotcha:** HomeBox v0.26+ requires its own
`HBOX_AUTH_API_KEY_PEPPER` (32+ random characters) to be set on the *HomeBox*
server before static API keys work at all — without it, HomeBox itself
crash-loops on startup. This is a HomeBox env var, not one of ours, but it's
the single most common reason "mint an API key" fails on a fresh v0.26+
HomeBox install. Set it before creating the key this app needs. Mint the key
(an `hb_`-prefixed static key) from your HomeBox user profile's API Keys page.
It stays server-side — the browser only ever talks to this app's
`/api/v1/homebox/*` proxy routes.

The QR base URL (`PUT /api/v1/homebox/settings`) is separate and falls back to
the HomeBox URL when unset.

**Phone capture:** on your phone open `<app-url>/capture` (or tap **Capture**
in the nav) and use Add to Home Screen for one-tap access. It scans a label's
QR code and attaches a photo to that HomeBox item.

**External Label Service:** enabling ELS on the Settings page registers
`GET /api/v1/els/label` (also `/api/els/label`) so HomeBox can delegate its own label rendering to this
app, at the tape width set there. Point HomeBox's own
`HBOX_LABEL_MAKER_LABEL_SERVICE_URL` at it (e.g.
`http://labelmaker:8000/api/v1/els/label` on a shared Docker network; the legacy
`/api/els/label` path still works and is not deprecated, so existing HomeBox
configs need no change).

**Security caveat:** HomeBox's ELS caller sends this endpoint a plain,
unauthenticated `GET` — that's HomeBox's own design (`fetchLabelFromURL`),
not a shortcut on our side, and there's no way to make it otherwise. `/api/v1/els/label`
is therefore exempt from the OIDC gate below even with OIDC on
(gating it would just break every HomeBox print button with no security
benefit, since HomeBox has no browser session to present). Leave ELS off
unless HomeBox can actually reach this app — don't expose it to the open
internet.

### Auth (optional — off by default)

Set on the Settings page (Authentication section).

- **Mode** `none` (default): zero-auth LAN behavior. `oidc`: gate every
  `/api/v1/*` route (except `/api/v1/health`, `/api/v1/auth/*`, `/api/v1/els/*`)
  behind a signed session cookie. Changing it needs no restart.
- **Issuer / client id / client secret / scopes:** your IdP's issuer URL (the
  rest is discovered from `{issuer}/.well-known/openid-configuration`), the
  confidential client's id and secret (write-only, never shown again), and
  space-separated scopes (`openid` required, default `openid profile email`).
- **Test login:** register the redirect URI shown on the page
  (`<app-url>/api/auth/callback`) with your IdP, then run **Test login**. OIDC
  can only be enabled after a successful test, and any later change to the issuer,
  client id, secret or scopes requires a new one.
- **Session lifetime** (default 8h, min 5 min) and **Secure cookie** (turn on when
  serving over HTTPS; leave off on plain HTTP or sign-in will fail).
- **Session secret:** generated automatically and stored in the database; use
  **Rotate session secret** to sign everyone out.
- With OIDC on, only a signed-in browser session (not an API key) can change
  authentication or CORS settings.

### API keys

For scripts and other machines under OIDC auth, create a `read` or `write`
key on the **Settings** page and send it as `Authorization: Bearer lm_...`. Scopes,
curl examples and the WebSocket ticket flow are in [API.md](API.md).

## Security notes

- **LAN-first by default.** With auth mode `none` (the default), there is no
  authentication at all — anyone who can reach the container's port 8000
  can design, print, and browse HomeBox data (if configured). This is meant
  for a trusted home/LAN network. Put it behind OIDC (or a reverse proxy
  with its own auth) before exposing it beyond that.
- **Enabling OIDC** gates every API route except health, auth, and ELS
  behind a signed session — see the [Auth section](#auth-optional--off-by-default) above.
- **Never allow `*` as a CORS origin** (the Settings page rejects it). This app enables
  `allow_credentials=True` on its CORS middleware (required for the session
  cookie to work cross-origin at all). Combined with a wildcard origin,
  browsers' CORS credentialed-request rules push most CORS libraries
  (Starlette's included) to *echo back whatever `Origin` header the request
  sent* rather than literally sending `*` — which means a wildcard here
  doesn't just allow "anyone read-only", it lets **any website on the
  internet ride a signed-in user's session** if they have it open in
  another tab. Only ever list specific origins you actually trust.
- **ELS exposure.** `/api/v1/els/label` is unauthenticated by HomeBox's own
  design (see the [ELS notes](#homebox-and-the-external-label-service) above) and cannot be gated without
  breaking the integration. Keep ELS off unless HomeBox can
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
[the protocol notes](the protocol notes)'s RESULTS section for the
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

# or serve a built frontend from the backend on :8001
cd frontend && npm run build
cd backend && uv run uvicorn labelmaker.main:app --port 8001

# frontend dev server (proxies /api, incl. /api/v1 and the WebSocket, to :8000)
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
