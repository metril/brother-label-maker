import { afterEach, describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { ChainPreviewDrawer } from "./ChainPreviewDrawer";
import { GlobalTrayDrawer } from "./GlobalTrayDrawer";
import { useChainPreviewStore } from "../stores/chainPreview";
import { useCurrentDesignStore, type CurrentDesign } from "../stores/currentDesign";
import { useTrayStore } from "../stores/tray";
import { TINY_PNG_B64 } from "../test/msw/handlers";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import type { LabelDefinition } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();
const INITIAL_CHAIN_PREVIEW_STATE = useChainPreviewStore.getState();

afterEach(() => {
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
  // Full reset (not just `open`) -- `docked` (dockable-preview feature) is
  // persisted via zustand's own `persist` middleware, so a test that
  // toggles it must not leak into the next one via the in-memory store
  // singleton (test/setup.ts's own `localStorage.clear()` only covers the
  // localStorage side of that, not this module's already-hydrated state).
  useChainPreviewStore.setState(INITIAL_CHAIN_PREVIEW_STATE, true);
  useCurrentDesignStore.setState({ current: null });
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

function seedTrayItems(n: number) {
  for (let i = 0; i < n; i++) {
    useTrayStore.getState().addItem({ definition: def(`ITEM-${i}`), png: null, lengthMm: 20 + i, label: `Text — ITEM-${i}` });
  }
}

/** ChainPreviewDrawer reads its own `open` flag off stores/chainPreview.ts
 * (shared, module-level -- see that store's own docstring) rather than
 * local/prop-driven state, so a tiny harness stands in for whichever real
 * TrayPanel instance would normally call `openDrawer()` -- same role the
 * old ChainedPreviewDialog.test.tsx's own Harness played for that dialog's
 * `open` prop, just sourced from the store instead of component state. */
function Harness() {
  const openDrawer = useChainPreviewStore((s) => s.openDrawer);
  return (
    <>
      <button type="button" onClick={openDrawer}>
        Open
      </button>
      <ChainPreviewDrawer />
    </>
  );
}

describe("ChainPreviewDrawer", () => {
  it("opens with the composite PNG, the correct segment count, and the stats row", async () => {
    seedTrayItems(2);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });

    const img = await within(drawer).findByAltText("Chained job preview");
    expect(img).toHaveAttribute("src", `data:image/png;base64,${TINY_PNG_B64}`);

    // The default printPreviewHandler returns exactly 2 segments.
    expect(within(drawer).getByTestId("segment-chip-0")).toHaveTextContent("1");
    expect(within(drawer).getByTestId("segment-chip-1")).toHaveTextContent("2");
    expect(within(drawer).queryByTestId("segment-chip-2")).not.toBeInTheDocument();

    expect(within(drawer).getByTestId("preview-total-mm")).toHaveTextContent("60.0 mm");
    expect(within(drawer).getByText(/UNVERIFIED estimate/)).toBeInTheDocument();
  });

  it("switching the mode tab refetches with the new chain_mode and does NOT touch the tray store's chainMode", async () => {
    seedTrayItems(1);
    const user = userEvent.setup();
    const capturedModes: string[] = [];
    server.use(
      http.post("/api/print/preview", async ({ request }) => {
        const body = (await request.json()) as { options?: { chain_mode?: string } };
        const mode = body.options?.chain_mode ?? "cut_each";
        capturedModes.push(mode);
        return HttpResponse.json({
          png_b64: TINY_PNG_B64,
          chain_mode: mode,
          total_mm: 40,
          content_mm: 30,
          feed_overhead_mm: 10,
          per_label_mm: 30,
          notes: [],
          segments: [{ index: 0, start_mm: 0, end_mm: 30, length_mm: 30 }],
          warnings: [],
        });
      }),
    );

    const storeBefore = useTrayStore.getState().chainMode;
    renderWithProviders(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("dialog", { name: "Print preview" });

    await waitFor(() => expect(capturedModes).toEqual(["cut_each"]));

    await user.click(screen.getByRole("radio", { name: "Chain" }));

    await waitFor(() => expect(capturedModes).toEqual(["cut_each", "chain_ff"]));
    expect(useTrayStore.getState().chainMode).toBe(storeBefore);
  });

  it("changing zoom changes the strip's on-screen width", async () => {
    seedTrayItems(1);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    // "Print preview zoom", not "Preview zoom" (L14 review fix) -- avoids
    // colliding with Designer's own same-named zoom control when both are
    // mounted on the Design route at once.
    expect(within(drawer).getByRole("radiogroup", { name: "Print preview zoom" })).toBeInTheDocument();
    const img = await within(drawer).findByAltText("Chained job preview");

    await waitFor(() => expect(img.style.width).not.toBe(""));
    const widthAt4x = img.style.width;

    await user.click(within(drawer).getByRole("radio", { name: "8×" }));
    expect(img.style.width).not.toBe(widthAt4x);
  });

  it("sizes the strip's height from the tape's PRINT height (print_mm), not its nominal width (M10)", async () => {
    seedTrayItems(1);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    const img = await within(drawer).findByAltText("Chained job preview");

    // The tray items' tape is 24mm/tze (see `def`); the tapes fixture's
    // matching row has print_mm: 18.1. At the drawer's opening zoom
    // (DEFAULT_PX_PER_MM, 4), the correct height is 18.1 * 4 = 72.4px --
    // the pre-fix, nominal-based figure would instead be 24 * 4 = 96px.
    await waitFor(() => expect(img.style.height).toBe("72.4px"));
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    seedTrayItems(1);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open" });

    await user.click(trigger);
    await screen.findByRole("dialog", { name: "Print preview" });

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Print preview" })).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("shows 'Nothing to preview' when the tray is empty, even though the drawer is open", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    expect(within(drawer).getByText("Nothing to preview.")).toBeInTheDocument();
  });

  it("empty tray falls back to Designer's mirrored current design, serialization included", async () => {
    // pages/Designer.tsx mirrors its current design into
    // stores/currentDesign.ts; the drawer previews it when the tray is
    // empty -- the same fallback TrayPanel's estimate/Print already have.
    interface CapturedBody {
      labels?: unknown[];
      serialization?: unknown;
    }
    let lastBody: CapturedBody | null = null;
    server.use(
      http.post("/api/print/preview", async ({ request }) => {
        lastBody = (await request.json()) as CapturedBody;
        return HttpResponse.json({
          png_b64: TINY_PNG_B64,
          chain_mode: "cut_each",
          total_mm: 30,
          content_mm: 25,
          feed_overhead_mm: 5,
          per_label_mm: 30,
          notes: [],
          segments: [{ index: 0, start_mm: 0, end_mm: 25, length_mm: 25 }],
          warnings: [],
        });
      }),
    );
    const serialization = { kind: "numeric", start: 1, end: 3, step: 1, pad: 0, copies_per_value: 1 };
    useCurrentDesignStore.getState().setCurrent(
      currentDesign({
        definition: def("CURRENT-UNSAVED"),
        serialization: serialization as never,
        canSubmit: true,
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Chained job preview");
    expect(within(drawer).queryByText("Nothing to preview.")).not.toBeInTheDocument();
    expect(lastBody).not.toBeNull();
    expect(lastBody!.labels).toHaveLength(1);
    expect(lastBody!.serialization).toEqual(serialization);
  });

  it("editing the tray while the drawer is open triggers a refetch", async () => {
    seedTrayItems(2);
    let requestCount = 0;
    server.use(
      http.post("/api/print/preview", async ({ request }) => {
        requestCount++;
        const body = (await request.json()) as { options?: { chain_mode?: string } };
        return HttpResponse.json({
          png_b64: TINY_PNG_B64,
          chain_mode: body.options?.chain_mode ?? "cut_each",
          total_mm: 60,
          content_mm: 50,
          feed_overhead_mm: 10,
          per_label_mm: 30,
          notes: [],
          segments: [
            { index: 0, start_mm: 0, end_mm: 25, length_mm: 25 },
            { index: 1, start_mm: 25, end_mm: 50, length_mm: 25 },
          ],
          warnings: [],
        });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("dialog", { name: "Print preview" });

    await waitFor(() => expect(requestCount).toBe(1));

    useTrayStore.getState().addItem({ definition: def("ITEM-2"), png: null, lengthMm: 20, label: "Text — ITEM-2" });

    await waitFor(() => expect(requestCount).toBe(2));
  });

  it("renders a non-empty `warnings` response as an alert (M13)", async () => {
    seedTrayItems(1);
    server.use(
      http.post("/api/print/preview", () =>
        HttpResponse.json({
          png_b64: TINY_PNG_B64,
          chain_mode: "cut_each",
          total_mm: 30,
          content_mm: 25,
          feed_overhead_mm: 5,
          per_label_mm: 30,
          notes: [],
          segments: [{ index: 0, start_mm: 0, end_mm: 25, length_mm: 25 }],
          warnings: ["label 1: text may be cramped at this tape width"],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Chained job preview");

    expect(within(drawer).getByRole("alert")).toHaveTextContent("label 1: text may be cramped at this tape width");
  });

  it("shows the request's error detail in an alert, and recovers without a permanent spinner (M14)", async () => {
    seedTrayItems(1);
    server.use(
      http.post("/api/print/preview", () =>
        HttpResponse.json({ detail: "combined tape length exceeds the 1000mm maximum" }, { status: 422 }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });

    const alert = await within(drawer).findByRole("alert");
    expect(alert).toHaveTextContent("combined tape length exceeds the 1000mm maximum");
    // Recovers to the error state rather than getting stuck showing the
    // loading spinner forever.
    expect(within(drawer).queryByRole("status", { name: "Loading" })).not.toBeInTheDocument();
  });

  it("opening the chain preview from TrayPanel's own button closes the GlobalTrayDrawer slide-over, and restores focus there on close", async () => {
    seedTrayItems(2);
    server.use(
      http.post("/api/print/estimate", () =>
        HttpResponse.json({
          label_count: 2,
          label_lengths_mm: [20, 21],
          content_mm: 41,
          feed_overhead_mm: 10,
          total_mm: 51,
          per_label_mm: 25.5,
          notes: [],
        }),
      ),
    );
    const user = userEvent.setup();

    renderWithProviders(
      <>
        <GlobalTrayDrawer />
        <ChainPreviewDrawer />
      </>,
    );

    const trayTrigger = await screen.findByRole("button", { name: /^Tray · 2/ });
    await user.click(trayTrigger);
    await screen.findByRole("dialog", { name: "Print tray" });

    await user.click(screen.getByRole("button", { name: "Preview" }));

    // Both slide-overs occupy the right edge -- opening the chain preview
    // drawer closes the tray drawer rather than stacking on top of it (see
    // TrayPanel.tsx's own `closeTrayDrawer` prop doc).
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Print tray" })).not.toBeInTheDocument());
    const chainDrawer = await screen.findByRole("dialog", { name: "Print preview" });
    expect(chainDrawer).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Close chain preview" })).toHaveFocus());

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Print preview" })).not.toBeInTheDocument());
    // Focus returns to GlobalTrayDrawer's own trigger -- the button that
    // was focused (by `closeTrayDrawer`'s own `dialog.close()`) the instant
    // the chain preview drawer opened, not the (now hidden) "Preview
    // chain" button nested inside the tray drawer's own panel.
    await waitFor(() => expect(trayTrigger).toHaveFocus());
  });
});

describe("ChainPreviewDrawer -- dockable preview", () => {
  it("the dock toggle flips the store's `docked` flag, and its accessible name flips with it", async () => {
    seedTrayItems(1);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("dialog", { name: "Print preview" });

    const dockButton = screen.getByRole("button", { name: "Dock preview" });
    await user.click(dockButton);

    expect(useChainPreviewStore.getState().docked).toBe(true);
    expect(screen.getByRole("button", { name: "Undock preview" })).toBeInTheDocument();
  });

  it("docked + open swaps in a complementary landmark -- no scrim, no aria-modal, no dialog role", async () => {
    seedTrayItems(1);
    useChainPreviewStore.setState({ docked: true });
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const panel = await screen.findByRole("complementary", { name: "Print preview" });

    expect(panel).not.toHaveAttribute("aria-modal");
    expect(document.querySelector('[aria-hidden][class*="bg-scrim/70"]')).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Print preview" })).not.toBeInTheDocument();
  });

  it("undocked + open keeps today's dialog semantics and scrim, unchanged", async () => {
    seedTrayItems(1);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const panel = await screen.findByRole("dialog", { name: "Print preview" });

    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(document.querySelector('[aria-hidden][class*="bg-scrim/70"]')).not.toBeNull();
  });

  it("close still works while docked, without stealing focus onto the close button", async () => {
    seedTrayItems(1);
    useChainPreviewStore.setState({ docked: true });
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    const trigger = screen.getByRole("button", { name: "Open" });
    await user.click(trigger);
    await screen.findByRole("complementary", { name: "Print preview" });

    // Docked mode skips the focus-steal contract entirely (see this
    // component's own docstring) -- the close button never gets
    // programmatic focus the way it does when undocked.
    expect(screen.getByRole("button", { name: "Close chain preview" })).not.toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Close chain preview" }));
    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "Print preview" })).not.toBeInTheDocument(),
    );
    expect(useChainPreviewStore.getState().open).toBe(false);
    // `docked` itself is untouched by closing -- remembered for next open
    // (stores/chainPreview.ts's own persisted preference).
    expect(useChainPreviewStore.getState().docked).toBe(true);
  });

  it("Escape does nothing while docked -- no Escape-to-close", async () => {
    seedTrayItems(1);
    useChainPreviewStore.setState({ docked: true });
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("complementary", { name: "Print preview" });

    await user.keyboard("{Escape}");
    expect(screen.getByRole("complementary", { name: "Print preview" })).toBeInTheDocument();
    expect(useChainPreviewStore.getState().open).toBe(true);
  });

  it("carries the xl:static in-flow-column class contract only while docked AND open", async () => {
    seedTrayItems(1);
    useChainPreviewStore.setState({ docked: true });
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("complementary", { name: "Print preview" });

    const panel = screen.getByTestId("chain-preview-drawer-panel");
    expect(panel.className).toContain("xl:static");
    expect(panel.className).toContain("xl:inset-auto");
    expect(panel.className).toContain("xl:w-[26rem]");
    expect(panel.className).toContain("xl:shrink-0");
    expect(panel.className).toContain("xl:border-l");
    // Docked mode drops the slide transition entirely (this component's
    // own docstring) -- nothing to animate once it's back in normal flow.
    expect(panel.className).not.toContain("transition-transform");
  });

  it("a closed docked panel is hidden exactly like an undocked one -- no xl: override leaks through while closed", () => {
    useChainPreviewStore.setState({ docked: true });
    renderWithProviders(<Harness />);

    const panel = screen.getByTestId("chain-preview-drawer-panel");
    expect(panel).not.toHaveAttribute("role");
    expect(panel.className).toContain("invisible");
    expect(panel.className).toContain("translate-x-full");
    expect(panel.className).not.toContain("xl:static");
  });
});
