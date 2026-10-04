import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomeboxEntityRow } from "./HomeboxEntityRow";
import type { HomeboxEntitySummary } from "../api/types";

const ENTITY: HomeboxEntitySummary = {
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
};

describe("HomeboxEntityRow label type choice", () => {
  it("renders no picker unless onLabelKindChange is given", () => {
    render(<ul><HomeboxEntityRow entity={ENTITY} checked={false} onToggle={() => {}} /></ul>);
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("defaults to Asset label and reports a changed kind", async () => {
    const onKind = vi.fn();
    render(<ul><HomeboxEntityRow entity={ENTITY} checked={false} onToggle={() => {}} onLabelKindChange={onKind} /></ul>);
    const select = screen.getByRole("combobox", { name: "Label type for Impact Driver" });
    expect(select).toHaveValue("homebox_asset");
    await userEvent.selectOptions(select, "cable_flag");
    expect(onKind).toHaveBeenCalledWith("cable_flag");
  });
});
