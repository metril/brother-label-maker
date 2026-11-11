# Label Maker HTTP API

The authoritative, machine-readable schema is [`openapi.json`](openapi.json),
also served live at `/openapi.json`, with interactive docs at `/docs` (Swagger
UI) and `/redoc`. This file is the human guide; the endpoint reference at the
bottom is generated from the code.

## Overview

- Base URL: `http://<host>:8000/api/v1` (the container serves the API, the web
  UI and the docs on one port).
- JSON in, JSON out, except binary routes (PNG images, SVG symbols, raw raster
  streams) which declare their media type in the schema.
- Errors always use one envelope (see below).

## Versioning

`/api/v1` is the canonical prefix. The unversioned `/api/*` paths are a
deprecated alias for the same handlers: responses carry `Deprecation: true`,
they are hidden from the schema, and they will be removed in a future major
release. Two legacy paths are intentionally **not** deprecated: ELS
(`/api/els/label`, HomeBox's caller cannot be reconfigured) and the OIDC
callback (`/api/auth/callback`, registered with your identity provider).

## Authentication

Three modes, selected by the `auth_mode` setting (Settings page):

- **`none`** (default): no authentication; every route is open. API keys are
  ignored. Intended for a trusted LAN.
- **`oidc` browser session**: sign in via `/api/v1/auth/login`; the signed
  `lm_session` cookie authorizes requests (the web UI uses this).
- **`oidc` API keys**: for scripts and machines. Create a key on the Settings
  page (name and scope). The plaintext `lm_...` is shown once. Send it as
  `Authorization: Bearer lm_...`.

Scopes: a `read` key may only issue `GET`, `HEAD` and `OPTIONS` (plus
`POST /ws-ticket`); a `write` key may call everything except key management,
which requires a browser session. Without a valid credential a request gets
`401 auth_required`; a read key attempting a write gets `403 forbidden`. These
routes never require authentication: `GET /health`, `/auth/*`, `/els/*`.
`/docs`, `/redoc` and `/openapi.json` are open in `none` mode and behind the
same gate in `oidc` mode.

```sh
export LM=http://labelmaker:8000/api/v1
export KEY=lm_xxxxxxxx

curl -H "Authorization: Bearer $KEY" $LM/printer/status
curl -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
     -d @print-request.json $LM/print
```

### WebSocket tickets

Keys should not appear in URLs, so browsers and scripts that cannot set headers
on a WebSocket exchange the key for a single-use ticket (valid 60 s):

```sh
TICKET=$(curl -s -X POST -H "Authorization: Bearer $KEY" $LM/ws-ticket | jq -r .ticket)
websocat "ws://labelmaker:8000/api/v1/ws?ticket=$TICKET"
```

Clients that can set headers may send the bearer header on the upgrade request
instead. An unauthenticated socket is refused with close code `4401`.

## Errors

Every error, including unknown routes, validation failures and unhandled
exceptions, has this shape:

```json
{"error": {"code": "not_found", "message": "preset not found", "details": null}}
```

`details` is `null` except for validation errors, where it is a list of
`{loc, msg, type}` (submitted values are never echoed); its `message` names
the offending fields, e.g. `invalid field: bogus_field`. 500 responses never
leak internals.

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `bad_request` | Malformed request |
| 401 | `auth_required` | Missing or invalid credentials |
| 403 | `forbidden` | Read-only key on a write, or key management without a session |
| 404 | `not_found` | Unknown route or resource |
| 405 | `method_not_allowed` | Method not supported on this path |
| 409 | `conflict` | State conflict (e.g. cancelling a finished job) |
| 413 | `payload_too_large` | Upload too large |
| 415 | `unsupported_media_type` | Unsupported upload type |
| 422 | `validation_error` | Request failed schema validation (`details` lists fields) |
| 422 | `invalid_design` | Label definition, params, tape or serialization rejected by the renderer |
| 422 | `invalid_csv` | CSV upload is empty, malformed or over the row limit |
| 422 | `invalid_image` | Upload is empty, undecodable, unsupported or too large to decode |
| 422 | `invalid_query` | Pagination or filter values out of range |
| 422 | `invalid_setting` | Settings update rejected (bad value or conflicting settings) |
| 422 | `invalid_field` | A non-nullable field was set to null |
| 422 | `invalid_tape_width` | Tape width does not exist for the tape family |
| 422 | `invalid_name` | A name is blank |
| 422 | `invalid_request` | Request is otherwise unusable (e.g. preset print without a tape) |
| 422 | `invalid_homebox_request` | HomeBox rejected the submitted data |
| 422 | `preview_too_large` | Chained preview would exceed the pixel cap |
| 429 | `rate_limited` | Too many requests |
| 500 | `internal_error` | Unhandled server error |
| 502 | `upstream_error` | Upstream (HomeBox) failure |
| 503 | `service_unavailable` | Dependency not configured or unavailable |
| 503 | `homebox_unavailable` | HomeBox is not configured or unreachable |
| 403 | `writes_disabled` | HomeBox writes are disabled in Settings |
| 507 | `insufficient_storage` | Job exceeds the printer or storage budget |

### Printer status `error_code`

`GET /printer/status` reports printer and bridge trouble in the body (HTTP 200
with `connected: false`) rather than as an HTTP error. `error_code` is one of:

| `error_code` | Meaning |
|---|---|
| `printer_busy` | Connected, but a job holds the printer |
| `printer_disconnected` | No printer found on USB |
| `printer_io_error` | USB read/write failed |
| `status_timeout` | Printer did not answer the status request |
| `bridge_not_configured` | Remote mode without a bridge URL |
| `bridge_unreachable` | Bridge host cannot be reached |
| `bridge_cert_mismatch` | Bridge certificate differs from the pinned one |
| `bridge_unpaired` | Bridge has not accepted this app's client certificate |
| `bridge_busy` | Bridge is serving another client |
| `bridge_error` | Any other bridge failure |

## Pagination

- `GET /history` and `GET /images` return
  `{"items": [...], "page": 1, "page_size": 20, "total": 135}`. Page with
  `page` (1-based) and `page_size` (1-100), or equivalently `limit` and
  `offset`.
- `GET /presets` returns a plain array. Pass `limit` and `offset`; the total
  matching count is in the `X-Total-Count` response header.

## WebSocket events

`GET /api/v1/ws` (upgrade) streams server-to-client JSON messages about print
jobs; the client sends nothing. Every message has `event` and `job_id`:

| `event` | Extra fields | When |
|---|---|---|
| `job.queued` | none | Job accepted into the queue |
| `job.started` | none | Worker began printing |
| `job.progress` | `sent`, `total` (bytes) | Throttled to roughly every 10%; ends with `sent == total` |
| `job.done` | none | Printed successfully |
| `job.failed` | `error` (string) | Failed; `error` explains why |
| `job.canceled` | none | Cancelled before printing |

```json
{"event": "job.failed", "job_id": "9f1c...", "error": "printer_disconnected"}
```

## External Label Service (ELS)

`GET /api/v1/els/label` renders a label image for HomeBox's External Label
Service. It is unauthenticated (HomeBox sends no credentials) and answers 404
unless ELS is enabled in Settings. The legacy path `/api/els/label` keeps
working and is not deprecated. See the README for HomeBox setup.

## Endpoint reference

Generated from the code by `make api-docs`; do not edit between the markers.
"Auth" shows the least privilege that is accepted in `oidc` mode.

<!-- BEGIN GENERATED -->

### health

Liveness probe; no authentication.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/health` | Health check | none | 200 | 500 |

### auth

OIDC login flow and current-session probe.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/auth/login` | Start OIDC sign-in | none | 302 | 404, 422, 502 |
| GET | `/api/v1/auth/callback` | Complete OIDC sign-in | none | 302 | 401, 404 |
| POST | `/api/v1/auth/logout` | Sign out | none | 204 | 404 |
| GET | `/api/v1/auth/me` | Get the current session | none | 200 | 500 |
| POST | `/api/v1/auth/oidc-test` | Start an OIDC test login | none | 200 | 401, 403, 422, 502 |
| POST | `/api/v1/auth/rotate-session-secret` | Rotate the session signing secret | none | 204 | 401, 403 |

### api-keys

Create, list and revoke API keys (browser session only).

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/api-keys` | List API keys | session only | 200 | 401, 403 |
| POST | `/api/v1/api-keys` | Create an API key | session only | 201 | 401, 403, 422 |
| DELETE | `/api/v1/api-keys/{key_id}` | Revoke an API key | session only | 204 | 401, 403, 404, 422 |

### settings

Runtime settings stored in the database overlay.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/settings` | List settings | read key or session | 200 | 500 |
| PUT | `/api/v1/settings` | Update settings | write key or session | 200 | 403, 409, 422 |

### labels

Label types, fonts, tapes, symbols, rendering and CSV expansion.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/label-types` | List label types | read key or session | 200 | 500 |
| GET | `/api/v1/fonts` | List bundled fonts | read key or session | 200 | 500 |
| GET | `/api/v1/tapes` | List supported tapes | read key or session | 200 | 500 |
| GET | `/api/v1/symbols` | List the symbol catalog | read key or session | 200, 304 | 500 |
| GET | `/api/v1/symbols/{symbol_id}` | Download a symbol SVG | read key or session | 200, 304 | 404, 422 |
| POST | `/api/v1/render/preview` | Render a label preview | write key or session | 200 | 422 |
| POST | `/api/v1/render/expand` | Expand a serialization sequence | write key or session | 200 | 422 |
| POST | `/api/v1/serialize/csv` | Parse a CSV for serialization | write key or session | 200 | 413, 422 |

### images

Uploaded images usable as label icons.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/images` | List uploaded images | read key or session | 200 | 422 |
| POST | `/api/v1/images` | Upload an image | write key or session | 201 | 413, 422 |
| GET | `/api/v1/images/{image_id}` | Download an image | read key or session | 200 | 404, 422 |
| DELETE | `/api/v1/images/{image_id}` | Delete an image | write key or session | 204 | 404, 422 |
| GET | `/api/v1/images/{image_id}/thumb` | Download an image thumbnail | read key or session | 200 | 404, 422 |

### gallery

Gallery of saved label artwork.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/gallery` | List gallery examples | read key or session | 200 | 500 |

### print

Queue print jobs, estimate tape use, preview chains, stream raster.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| POST | `/api/v1/print` | Queue a print job | write key or session | 202 | 422 |
| POST | `/api/v1/print/estimate` | Estimate tape usage | write key or session | 200 | 422 |
| POST | `/api/v1/print/preview` | Preview a chained print job | write key or session | 200 | 422, 507 |
| GET | `/api/v1/print/jobs/{job_id}` | Get a print job | read key or session | 200 | 404, 422 |
| POST | `/api/v1/print/jobs/{job_id}/cancel` | Cancel a queued print job | write key or session | 200 | 404, 409, 422 |
| GET | `/api/v1/print/jobs/{job_id}/stream` | Download a job's raster stream | read key or session | 200 | 404, 422 |

### printer

Printer status, bridge identity and cutter control.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/printer/status` | Get printer connection status | read key or session | 200 | 500 |
| GET | `/api/v1/printer/bridge-identity` | Get this app's bridge certificate | read key or session | 200 | 500 |
| POST | `/api/v1/printer/cut` | Feed tape and cut | write key or session | 202 | 500 |

### presets

Saved label presets; list supports X-Total-Count pagination.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/presets` | List presets | read key or session | 200 | 422 |
| POST | `/api/v1/presets` | Create a preset | write key or session | 201 | 422 |
| GET | `/api/v1/presets/{preset_id}` | Get a preset | read key or session | 200 | 404, 422 |
| PUT | `/api/v1/presets/{preset_id}` | Update a preset | write key or session | 200 | 404, 422 |
| DELETE | `/api/v1/presets/{preset_id}` | Delete a preset | write key or session | 204 | 404, 422 |
| POST | `/api/v1/presets/{preset_id}/print` | Print a preset | write key or session | 202 | 404, 422 |

### history

Print history, thumbnails and reprint.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/history` | List print history | read key or session | 200 | 422 |
| GET | `/api/v1/history/{job_id}` | Get a history job | read key or session | 200 | 404, 422 |
| DELETE | `/api/v1/history/{job_id}` | Delete a history job | write key or session | 204 | 404, 409, 422 |
| GET | `/api/v1/history/{job_id}/thumbnail` | Get a job thumbnail | read key or session | 200 | 404, 422 |
| POST | `/api/v1/history/{job_id}/reprint` | Reprint a job | write key or session | 202 | 404, 409, 422 |

### homebox

Proxy to a configured HomeBox server (entities, tags, bulk create).

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/homebox/status` | Get HomeBox integration status | read key or session | 200 | 500 |
| GET | `/api/v1/homebox/entities` | List HomeBox entities | read key or session | 200 | 404, 422, 502, 503 |
| GET | `/api/v1/homebox/entities/tree` | Get the HomeBox location tree | read key or session | 200 | 404, 422, 502, 503 |
| GET | `/api/v1/homebox/entities/{entity_id}` | Get a HomeBox entity | read key or session | 200 | 404, 422, 502, 503 |
| GET | `/api/v1/homebox/entities/{entity_id}/path` | Get an entity's location path | read key or session | 200 | 404, 422, 502, 503 |
| GET | `/api/v1/homebox/assets/{asset_id}` | Find entities by asset id | read key or session | 200 | 404, 422, 502, 503 |
| POST | `/api/v1/homebox/entities/bulk` | Bulk-create HomeBox entities | write key or session | 200 | 403, 404, 422, 502, 503 |
| POST | `/api/v1/homebox/entities/{entity_id}/attachments` | Upload an entity photo | write key or session | 200 | 403, 404, 422, 502, 503, 413, 415 |
| GET | `/api/v1/homebox/tags` | List HomeBox tags | read key or session | 200 | 403, 404, 422, 502, 503 |
| GET | `/api/v1/homebox/entity-types` | List HomeBox entity types | read key or session | 200 | 403, 404, 422, 502, 503 |
| GET | `/api/v1/homebox/settings` | Get HomeBox QR settings | read key or session | 200 | 500 |
| PUT | `/api/v1/homebox/settings` | Update HomeBox QR settings | write key or session | 200 | 422 |

### els

HomeBox External Label Service endpoint; unauthenticated by design.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| GET | `/api/v1/els/label` | Render an ELS label | none | 200 | 404, 422 |

### ws

WebSocket event stream and single-use ticket issuing.

| Method | Path | Summary | Auth | Success | Errors |
|---|---|---|---|---|---|
| POST | `/api/v1/ws-ticket` | Get a WebSocket ticket | read key or session | 200 | 401 |

<!-- END GENERATED -->
