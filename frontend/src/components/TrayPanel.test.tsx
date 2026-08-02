import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { TrayPanel, type CurrentDesign } from "./TrayPanel";
import { useTrayStore } from "../stores/tray";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import type { LabelDefinition } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
});

function def(text: string): LabelDefinition {
  return { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: [text] } };
}

function currentDesign(overrides: Partial<CurrentDesign> = {}): CurrentDesign {
  return {
    definition: def("CURRENT"),
    canSubmit: true,
    isRenderable: () => true,
    png: null,
    lengthMm: 25.4,
    label: "Text — CURRENT",
    serializationEnabled: false,
    serialization: null,
    totalLabels: null,
    serializationHasVisibleError: false,
    ...overrides,
  };
}

/** components/GlobalTrayDrawer.tsx always passes `current={null}` (there's
 * no "current, unsaved design" away from the Designer page) -- these cover
 * the one shape GlobalTrayDrawer's own tests can't reach directly, since
 * that component hides itself entirely whenever the tray is empty (so a
 * `current === null` + empty-tray render never happens THROUGH it). Every
 * other `current === null` behavior (non-empty tray, printing, previews) is
 * already covered end-to-end via GlobalTrayDrawer.test.tsx. */
describe("TrayPanel -- current === null (away from the Designer page)", () => {
  it("an empty tray with no current design has nothing to print: Print is disabled, no crash, no serialization branch", async () => {
    server.use(http.post("/api/print/estimate", () => {
      throw new Error("must not be called: nothing renderable to estimate");
    }));

    renderWithProviders(<TrayPanel current={null} />);

    expect(await screen.findByText(/Nothing queued/)).toBeInTheDocument();
    expect(screen.getByText("Add content to estimate tape usage.")).toBeInTheDocument();
    // No "+ Add to tray" affordance either -- there's no current design to add.
    expect(screen.queryByRole("button", { name: "+ Add to tray" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print 0 labels" })).toBeDisabled();
    // Track C2: nothing (renderable) to chain-preview either -- same gate
    // as the estimate panel/Print button above.
    expect(screen.getByRole("button", { name: "Preview chain" })).toBeDisabled();
  });
});

/** Track C2: the "Preview chain" button + ChainedPreviewDialog, mounted
 * through TrayPanel exactly as the real app does (JobTray/GlobalTrayDrawer
 * both render TrayPanel directly, never ChainedPreviewDialog on their
 * own). */
describe("TrayPanel -- Preview chain dialog", () => {
  it("is disabled when the tray has nothing valid to print (mirrors the estimate/Print gate)", () => {
    renderWithProviders(<TrayPanel current={currentDesign({ canSubmit: false })} />);
    expect(screen.getByRole("button", { name: "Preview chain" })).toBeDisabled();
  });

  it("is enabled once there's something to print, and opens the dialog with the composite preview", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
    const previewButton = screen.getByRole("button", { name: "Preview chain" });
    expect(previewButton).toBeEnabled();

    await user.click(previewButton);
    const dialog = await screen.findByRole("dialog", { name: "Chain preview" });
    expect(await within(dialog).findByAltText("Chained job preview")).toBeInTheDocument();

    // Opening the dialog does not touch the tray's own chainMode.
    expect(useTrayStore.getState().chainMode).toBe(INITIAL_TRAY_STATE.chainMode);
  });

  it("closes on Escape and returns focus to the trigger button", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "Preview chain" });

    await user.click(trigger);
    await screen.findByRole("dialog", { name: "Chain preview" });

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Chain preview" })).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
