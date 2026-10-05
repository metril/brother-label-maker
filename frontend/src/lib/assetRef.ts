// Parses what a scanned QR (or the typed "Enter asset #" box) says into a
// HomeBox reference for pages/Capture.tsx. Pure -- no DOM/network. A label
// printed by this app encodes `${qr_base_url}/a/{assetId}` (asset labels) or
// `${qr_base_url}/item/{uuid}` (asset-less items); HomeBox's own location
// labels use `/location/{uuid}`.

import { matchesAssetIdShape, stripAssetIdHash } from "./homebox";

export interface ScanRef {
  kind: "asset" | "entity" | "location";
  value: string;
}

/** HomeBox displays asset number N as zero-padded groups of three digits
 * ("000-001", "001-234"); a bare number typed into the numeric keypad is
 * normalised to that shape before it's used as a path segment. */
export function normalizeAssetId(text: string): string | null {
  const cleaned = stripAssetIdHash(text);
  if (matchesAssetIdShape(cleaned)) return cleaned;
  if (!/^\d{1,6}$/.test(cleaned)) return null;
  const padded = cleaned.padStart(6, "0");
  return `${padded.slice(0, 3)}-${padded.slice(3)}`;
}

const PATH_RE = /(?:^|\/)(a|item|location)\/([^/?#]+)\/?$/;

function fromPath(path: string): ScanRef | null {
  const m = PATH_RE.exec(path);
  if (!m) return null;
  let id: string;
  try {
    id = decodeURIComponent(m[2]);
  } catch {
    return null;
  }
  if (m[1] === "a") {
    const asset = normalizeAssetId(id);
    return asset ? { kind: "asset", value: asset } : null;
  }
  return { kind: m[1] === "item" ? "entity" : "location", value: id };
}

/** `qrBaseUrl` (GET /api/homebox/settings' `effective_qr_base_url`) is only
 * a hint for stripping a sub-path prefix; a URL on ANY host whose path ends
 * in /a/<id>, /item/<uuid> or /location/<uuid> is accepted (labels outlive
 * a changed base URL). Returns null for anything else. */
export function parseScan(text: string, qrBaseUrl?: string | null): ScanRef | null {
  const raw = text.trim();
  if (!raw) return null;

  if (/^https?:\/\//i.test(raw)) {
    const base = qrBaseUrl?.trim().replace(/\/+$/, "");
    if (base && raw.toLowerCase().startsWith(`${base.toLowerCase()}/`)) {
      const hit = fromPath(raw.slice(base.length).split(/[?#]/)[0]);
      if (hit) return hit;
    }
    try {
      return fromPath(new URL(raw).pathname);
    } catch {
      return null;
    }
  }

  const asset = normalizeAssetId(raw);
  return asset ? { kind: "asset", value: asset } : null;
}
