// Pure helpers for task 3.4's HomeBox browse page (pages/Homebox.tsx) --
// kept UI/network-free, mirroring lib/tray.ts's own split between pure
// logic and the components/hooks that drive it: the asset-id shape check,
// the breadcrumb-from-path reduction, and the LabelDefinition each selected
// entity turns into are all deterministic given their inputs, so they're
// independently unit-testable without mocking fetch.

import type { HomeboxEntitySummary, HomeboxPathSegment, LabelDefinition, Tape } from "../api/types";

// HomeBox's own asset-id display format, e.g. "000-001" (three digits, a
// dash, three-or-more digits) -- an optional leading "#" is how the research
// doc/HomeBox's own UI sometimes prefixes it, tolerated here too.
const ASSET_ID_SHAPE_RE = /^#?\d{3}-\d{3,}$/;

/** True when `text` (trimmed) looks like a HomeBox asset id -- the browse
 * page's own signal to ALSO query GET /api/homebox/assets/{id} alongside
 * the normal entities search (see pages/Homebox.tsx). */
export function matchesAssetIdShape(text: string): boolean {
  return ASSET_ID_SHAPE_RE.test(text.trim());
}

/** Strips the search box's own optional leading "#" before the id is used
 * as a literal path segment in GET /api/homebox/assets/{id} -- HomeBox's
 * asset ids themselves never carry one. */
export function stripAssetIdHash(text: string): string {
  return text.trim().replace(/^#/, "");
}

/** Turns a root-first ancestor PATH (the entity itself last, per
 * GET /api/homebox/entities/{id}/path's own contract) into the breadcrumb
 * string a homebox_asset/homebox_location label prints: the entity's OWN
 * segment is always dropped (its name is already printed separately, as
 * `name`/`asset_id`), and only LOCATION-typed ancestors are kept -- an
 * item's immediate parent can itself be another item (HomeBox nests items),
 * which does not belong in a "Garage › Shelf B" location breadcrumb. */
export function buildBreadcrumb(path: HomeboxPathSegment[]): string {
  return path
    .slice(0, -1)
    .filter((segment) => segment.type === "location")
    .map((segment) => segment.name)
    .join(" › ");
}

// Backend Field(...) bounds for the two homebox render types (see
// render/types/homebox_asset.py / homebox_location.py). Values from
// HomeBox can legitimately exceed them (its names go to 255; a deep
// location chain has no cap at all), and an over-long value would 422 the
// WHOLE print job at submit time -- long after the silent "Add to tray"
// succeeded. Decorative text gets clamped with an ellipsis instead.
const MAX_NAME_LEN = 120;
const MAX_BREADCRUMB_LEN = 160;

function clamp(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

/** Builds the LabelDefinition "Add to tray" queues for one selected entity
 * (task 3.4's own construction rules): `tape` is whatever the designer's
 * OWN current tape selection is (stores/designer.ts's `tape`, the same
 * value every Designer-added tray item snapshots) -- HomeBox entities carry
 * no tape opinion of their own. `qrBaseUrl` is
 * GET /api/homebox/settings' `effective_qr_base_url`; when it's null this
 * NEVER fabricates a scheme/host -- `show_qr` goes false and `qr_data`
 * falls back to a bare path (still non-empty, satisfying the render types'
 * own `min_length=1`, but never a lie about where it resolves).
 *
 * Review fix-up: an ITEM WITHOUT AN ASSET ID (HomeBox emits `""` for every
 * item predating asset-id auto-increment, and for a row whose entity_type
 * is null) used to build a homebox_asset with `asset_id: ""` -- which
 * passes the silent add, then 422s the whole tray job at print time on the
 * backend's `min_length=1`. Asset-less items now take the homebox_location
 * shape instead (name + breadcrumb + item-URL QR -- the same reasoning
 * router_els.py documents for the identical field-bound problem), so every
 * definition this function returns is renderable by construction. */
export function buildHomeboxLabelDefinition(
  entity: HomeboxEntitySummary,
  breadcrumb: string,
  qrBaseUrl: string | null,
  tape: Tape,
): LabelDefinition {
  const base = qrBaseUrl ?? "";
  const showQr = qrBaseUrl != null;
  const isLocation = entity.entity_type?.is_location ?? false;
  const crumb = clamp(breadcrumb, MAX_BREADCRUMB_LEN);
  const name = clamp(entity.name, MAX_NAME_LEN);

  if (isLocation || !entity.asset_id) {
    return {
      type: "homebox_location",
      tape,
      params: {
        name,
        path: crumb,
        qr_data: isLocation ? `${base}/location/${entity.id}` : `${base}/item/${entity.id}`,
        show_qr: showQr,
      },
    };
  }

  return {
    type: "homebox_asset",
    tape,
    params: {
      asset_id: entity.asset_id,
      name,
      location: crumb,
      qr_data: `${base}/a/${entity.asset_id}`,
      show_qr: showQr,
    },
  };
}

/** Which label type an entity row's "Add to tray" builds. */
export type HomeboxLabelKind = "homebox_asset" | "cable_wrap" | "cable_flag";

/** Backend bounds for cable_wrap/cable_flag `lines` (see render/types/cable_wrap.py). */
const CABLE_MAX_LINES = 2;
const CABLE_MAX_LINE_CHARS = 30;

/** The URL a printed QR should resolve to: `${base}/a/${asset_id}` when the
 * entity has an asset id, else `${base}/item/${id}` (`/location/${id}` for
 * locations). Null when no base URL is configured -- never fabricates a host. */
export function homeboxQrUrl(entity: HomeboxEntitySummary, qrBaseUrl: string | null): string | null {
  if (qrBaseUrl == null) return null;
  if (entity.entity_type?.is_location) return `${qrBaseUrl}/location/${entity.id}`;
  return entity.asset_id ? `${qrBaseUrl}/a/${entity.asset_id}` : `${qrBaseUrl}/item/${entity.id}`;
}

/** LabelDefinition for a cable_wrap / cable_flag label of one entity: lines
 * default to [name, asset id] (trailing blank dropped, each clamped to the
 * type's 30-char / 2-line limits); `qr_data` is set only when a QR base URL
 * is configured. `params` override the defaults (e.g. cable_diameter_mm). */
export function buildHomeboxCableLabelDefinition(
  entity: HomeboxEntitySummary,
  kind: "cable_wrap" | "cable_flag",
  qrBaseUrl: string | null,
  tape: Tape,
  params: Record<string, unknown> = {},
): LabelDefinition {
  const lines = [entity.name, entity.asset_id]
    .map((line) => clamp(line.trim(), CABLE_MAX_LINE_CHARS))
    .filter((line, i) => line !== "" || i === 0)
    .slice(0, CABLE_MAX_LINES);
  // Backend requires at least one non-blank line: fall back to a short entity id.
  if (!lines[0]) lines[0] = entity.id.slice(0, CABLE_MAX_LINE_CHARS);
  const qr = homeboxQrUrl(entity, qrBaseUrl);
  return {
    type: kind,
    tape,
    params: { lines, ...(qr != null ? { qr_data: qr } : {}), ...params },
  };
}

/** The tray item's own short caption (TrayItem.label, components/
 * TrayItemRow.tsx) -- "type title + name", the same "Type — text" shape
 * lib/tray.ts's describeCurrentDesign gives every Designer-added item, so a
 * HomeBox-sourced row in a tray full of designer-built ones reads
 * consistently rather than as a bare, unlabeled name. */
export function describeHomeboxEntity(entity: HomeboxEntitySummary): string {
  const isLocation = entity.entity_type?.is_location ?? false;
  return `${isLocation ? "HomeBox Location" : "HomeBox Asset"} — ${entity.name}`;
}
