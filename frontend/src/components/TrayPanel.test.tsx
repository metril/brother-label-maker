import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { TrayPanel, type CurrentDesign } from "./TrayPanel";
import { useChainPreviewStore } from "../stores/chainPreview";
import { useTrayStore } from "../stores/tray";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import type { LabelDefinition } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
  useChainPreviewStore.setState({ open: false });
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

/** Track C2 rework: components/ChainPreviewDrawer.tsx no longer renders
 * through TrayPanel at all -- it's mounted once, at AppShell level, and
 * reads its own content straight off stores/tray.ts (see that component's
 * own docstring). TrayPanel's own responsibility for "Preview chain" is
 * now just the button: disabled gating, and wiring stores/chainPreview.ts
 * + the optional `closeTrayDrawer` prop -- the drawer's actual content
 * (PNG/segments/stats/mode tabs/zoom/focus/Escape) is covered end-to-end
 * by ChainPreviewDrawer.test.tsx instead. */
describe("TrayPanel -- Preview chain button", () => {
  it("is disabled when the tray has nothing valid to print (mirrors the estimate/Print gate)", () => {
    renderWithProviders(<TrayPanel current={currentDesign({ canSubmit: false })} />);
    expect(screen.getByRole("button", { name: "Preview chain" })).toBeDisabled();
  });

  it("is enabled once there's something to print, and opens the shared drawer store without touching the tray's own chainMode", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TrayPanel current={currentDesign()} onAddToTray={vi.fn()} />);
    const previewButton = screen.getByRole("button", { name: "Preview chain" });
    expect(previewButton).toBeEnabled();
    expect(useChainPreviewStore.getState().open).toBe(false);

    await user.click(previewButton);

    expect(useChainPreviewStore.getState().open).toBe(true);
    // Opening the drawer does not touch the tray's own chainMode.
    expect(useTrayStore.getState().chainMode).toBe(INITIAL_TRAY_STATE.chainMode);
  });

  it("calls the optional closeTrayDrawer prop (GlobalTrayDrawer's own dialog.close) before opening the chain-preview drawer", async () => {
    const user = userEvent.setup();
    const closeTrayDrawer = vi.fn();
    renderWithProviders(
      <TrayPanel current={currentDesign()} onAddToTray={vi.fn()} closeTrayDrawer={closeTrayDrawer} />,
    );

    await user.click(screen.getByRole("button", { name: "Preview chain" }));

    expect(closeTrayDrawer).toHaveBeenCalledTimes(1);
    expect(useChainPreviewStore.getState().open).toBe(true);
  });
});
