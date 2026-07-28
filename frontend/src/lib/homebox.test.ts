import { describe, expect, it } from "vitest";
import { buildBreadcrumb, buildHomeboxLabelDefinition, describeHomeboxEntity, matchesAssetIdShape, stripAssetIdHash } from "./homebox";
import type { HomeboxEntitySummary, HomeboxPathSegment } from "../api/types";

function entity(overrides: Partial<HomeboxEntitySummary> = {}): HomeboxEntitySummary {
  return {
    id: "entity-1",
    name: "Impact Driver",
    description: "",
    asset_id: "000-001",
    archived: false,
    quantity: null,
    entity_type: { id: "et-1", name: "", is_location: false },
    parent: null,
    tags: [],
    thumbnail_id: null,
    image_id: null,
    ...overrides,
  };
}

describe("matchesAssetIdShape", () => {
  it("matches HomeBox's own 000-001 style, with or without a leading #", () => {
    expect(matchesAssetIdShape("000-001")).toBe(true);
    expect(matchesAssetIdShape("#000-001")).toBe(true);
    expect(matchesAssetIdShape("  000-042  ")).toBe(true);
    expect(matchesAssetIdShape("000-0001234")).toBe(true);
  });

  it("rejects plain search text", () => {
    expect(matchesAssetIdShape("impact driver")).toBe(false);
    expect(matchesAssetIdShape("000-01")).toBe(false); // needs 3+ digits after the dash
    expect(matchesAssetIdShape("0000-001")).toBe(false); // needs exactly 3 digits before the dash
    expect(matchesAssetIdShape("")).toBe(false);
  });
});

describe("stripAssetIdHash", () => {
  it("drops a leading # and surrounding whitespace, leaves a bare id alone", () => {
    expect(stripAssetIdHash("#000-001")).toBe("000-001");
    expect(stripAssetIdHash("  000-001  ")).toBe("000-001");
    expect(stripAssetIdHash("000-001")).toBe("000-001");
  });
});

describe("buildBreadcrumb", () => {
  const GARAGE: HomeboxPathSegment = { id: "loc-1", name: "Garage", type: "location" };
  const SHELF: HomeboxPathSegment = { id: "loc-2", name: "Shelf B", type: "location" };

  it("drops the entity's own trailing segment and keeps only location ancestors, root-first", () => {
    const path = [GARAGE, SHELF, { id: "entity-1", name: "Impact Driver", type: "item" }];
    expect(buildBreadcrumb(path)).toBe("Garage › Shelf B");
  });

  it("drops a non-location ancestor (an item nested under another item) from the breadcrumb", () => {
    const path = [GARAGE, { id: "box-1", name: "Toolbox", type: "item" }, { id: "entity-1", name: "Impact Driver", type: "item" }];
    expect(buildBreadcrumb(path)).toBe("Garage");
  });

  it("returns an empty string for a top-level entity (no ancestors at all)", () => {
    expect(buildBreadcrumb([{ id: "entity-1", name: "Impact Driver", type: "item" }])).toBe("");
  });
});

describe("buildHomeboxLabelDefinition", () => {
  const TAPE = { width_mm: 24, family: "tze" as const };

  it("builds a homebox_asset definition with a full qr_data URL when a base is configured", () => {
    const def = buildHomeboxLabelDefinition(entity(), "Garage › Shelf B", "https://homebox.example.com", TAPE);
    expect(def).toEqual({
      type: "homebox_asset",
      tape: TAPE,
      params: {
        asset_id: "000-001",
        name: "Impact Driver",
        location: "Garage › Shelf B",
        qr_data: "https://homebox.example.com/a/000-001",
        show_qr: true,
      },
    });
  });

  it("builds a FULLY RENDERABLE homebox_location for an item without an asset id", () => {
    // Review fix-up: this used to assert only qr_data while the definition
    // was still a homebox_asset with asset_id: "" -- silently added to the
    // tray, then 422ing the whole print job on the backend's min_length=1.
    const def = buildHomeboxLabelDefinition(
      entity({ asset_id: "" }), "Garage", "https://homebox.example.com", TAPE,
    );
    expect(def).toEqual({
      type: "homebox_location",
      tape: TAPE,
      params: {
        name: "Impact Driver",
        path: "Garage",
        qr_data: "https://homebox.example.com/item/entity-1",
        show_qr: true,
      },
    });
  });

  it("routes a null entity_type the same asset-less way (never an empty asset_id param)", () => {
    const def = buildHomeboxLabelDefinition(
      entity({ asset_id: "", entity_type: null }), "", "https://homebox.example.com", TAPE,
    );
    expect(def.type).toBe("homebox_location");
    expect(def.params.qr_data).toBe("https://homebox.example.com/item/entity-1");
  });

  it("clamps over-long names and breadcrumbs to the backend Field bounds with an ellipsis", () => {
    const def = buildHomeboxLabelDefinition(
      entity({ name: "N".repeat(255) }), "B".repeat(200), "https://homebox.example.com", TAPE,
    );
    expect((def.params.name as string).length).toBe(120);
    expect((def.params.name as string).endsWith("…")).toBe(true);
    expect((def.params.location as string).length).toBe(160);
    expect((def.params.location as string).endsWith("…")).toBe(true);
  });

  it("never fabricates a base URL: show_qr is false and qr_data is a bare path when no base is configured", () => {
    const def = buildHomeboxLabelDefinition(entity(), "", null, TAPE);
    expect(def.params.show_qr).toBe(false);
    expect(def.params.qr_data).toBe("/a/000-001");
  });

  it("builds a homebox_location definition (path, not location) for a location-type entity", () => {
    const locationEntity = entity({
      id: "loc-5",
      name: "Shelf B",
      asset_id: "",
      entity_type: { id: "et-2", name: "", is_location: true },
    });
    const def = buildHomeboxLabelDefinition(locationEntity, "Garage", "https://homebox.example.com", TAPE);
    expect(def).toEqual({
      type: "homebox_location",
      tape: TAPE,
      params: {
        name: "Shelf B",
        path: "Garage",
        qr_data: "https://homebox.example.com/location/loc-5",
        show_qr: true,
      },
    });
  });
});

describe("describeHomeboxEntity", () => {
  it("captions an item as \"HomeBox Asset — {name}\"", () => {
    expect(describeHomeboxEntity(entity({ name: "Impact Driver" }))).toBe("HomeBox Asset — Impact Driver");
  });

  it("captions a location as \"HomeBox Location — {name}\"", () => {
    expect(describeHomeboxEntity(entity({ name: "Shelf B", entity_type: { id: "et-2", name: "", is_location: true } }))).toBe(
      "HomeBox Location — Shelf B",
    );
  });
});
