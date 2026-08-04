import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { GlobalTrayDrawer } from "./GlobalTrayDrawer";
import { usePrintPreviewStore } from "../stores/printPreview";
import { useCurrentDesignStore, type CurrentDesign } from "../stores/currentDesign";
import { useTrayDrawerStore } from "../stores/trayDrawer";
import { useTrayStore } from "../stores/tray";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { TINY_PNG_B64 } from "../test/msw/handlers";
import type { LabelDefinition, PrintEstimateResponse } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();
const INITIAL_TRAY_DRAWER_STATE = useTrayDrawerStore.getState();
const INITIAL_CHAIN_PREVIEW_STATE = usePrintPreviewStore.getState();

afterEach(() => {
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
  useCurrentDesignStore.setState({ current: null });
  // `docked` (dockable-tray feature) is persisted via zustand's own
  // `persist` middleware, so a test that toggles it must not leak into the
  // next one via the in-memory store singleton (test/setup.ts's own
  // `localStorage.clear()` only covers the localStorage side of that, not
  // this module's already-hydrated state) -- same reasoning
  // PrintPreviewDeck.test.tsx's own afterEach already documents for
  // stores/printPreview.ts.
  useTrayDrawerStore.setState(INITIAL_TRAY_DRAWER_STATE, true);
  usePrintPreviewStore.setState(INITIAL_CHAIN_PREVIEW_STATE, true);
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

function estimateBody(overrides: Partial<PrintEstimateResponse> = {}): PrintEstimateResponse {
  return {
    label_count: 1,
    label_lengths_mm: [25.4],
    content_mm: 25.4,
    feed_overhead_mm: 10,
    total_mm: 35.4,
    per_label_mm: 35.4,
    notes: [],
    ...overrides,
  };
}

function seedTrayItems(n: number) {
  for (let i = 0; i < n; i++) {
    useTrayStore.getState().addItem({ definition: def(`ITEM-${i}`), png: null, lengthMm: 20 + i, label: `Text — ITEM-${i}` });
  }
}

describe("GlobalTrayDrawer -- hidden while the tray is empty", () => {
  // Dockable-tray feature: unlike the pre-split component (which returned
  // null outright, gating the panel too), GlobalTrayPanel now stays
  // permanently mounted -- see GlobalTrayDrawer.tsx's own top-of-file
  // docstring for why (an in-flight print job's state must survive) -- so
  // an empty tray with no current design hides only the trigger BUTTON;
  // the panel itself renders present-but-hidden, the exact resting state
  // PrintPreviewDeck's own panel already has with nothing to preview.
  it("hides the trigger button, but keeps the panel mounted and hidden, when there's nothing queued", () => {
    renderWithProviders(<GlobalTrayDrawer />);
    expect(screen.queryByRole("button", { name: /^Tray/ })).not.toBeInTheDocument();

    const panel = screen.getByTestId("global-tray-drawer-panel");
    expect(panel).not.toHaveAttribute("role");
    expect(panel.className).toContain("invisible");
    expect(panel.className).toContain("translate-x-full");
  });
});

describe("GlobalTrayDrawer -- header button, open/close, and focus management", () => {
  it('shows "Tray · N" (plus the tape estimate once it resolves), opens a right-side slide-over on click, and moves focus to its close button', async () => {
    seedTrayItems(2);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ label_count: 2, total_mm: 60 }))));
    const user = userEvent.setup();

    renderWithProviders(<GlobalTrayDrawer />);

    // Regex, not an exact name: the accessible name starts as "Tray · 2"
    // and gains a ", X.X mm" suffix once the (debounced) estimate resolves
    // -- an exact match would only pass if the query happened to land in
    // the narrow window before that suffix appears.
    const trigger = await screen.findByRole("button", { name: /^Tray · 2/ });
    await waitFor(() => expect(trigger).toHaveTextContent("Tray · 2, 60.0 mm"));

    await user.click(trigger);

    const panel = screen.getByTestId("global-tray-drawer-panel");
    expect(panel).toHaveAttribute("role", "dialog");
    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(panel).toHaveAttribute("aria-label", "Print tray");

    const closeButton = screen.getByRole("button", { name: "Close print tray" });
    await waitFor(() => expect(closeButton).toHaveFocus());
    expect(panel).toHaveTextContent("Text — ITEM-0");
    expect(panel).toHaveTextContent("Text — ITEM-1");
  });

  it("closes and restores focus to the trigger on Escape, and on a scrim click", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    const user = userEvent.setup();

    renderWithProviders(<GlobalTrayDrawer />);
    const trigger = await screen.findByRole("button", { name: /^Tray · 1/ });
    await user.click(trigger);
    await waitFor(() => expect(screen.getByRole("button", { name: "Close print tray" })).toHaveFocus());

    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.getByTestId("global-tray-drawer-panel")).not.toHaveAttribute("role");

    await user.click(trigger);
    await waitFor(() => expect(screen.getByRole("button", { name: "Close print tray" })).toHaveFocus());
    const scrim = document.querySelector('[aria-hidden][class*="bg-scrim/70"]');
    expect(scrim).not.toBeNull();
    await user.click(scrim!);
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

describe("GlobalTrayDrawer -- printing (current is always null: no current-design fallback)", () => {
  it("Print POSTs the tray's own items only, exactly like JobTray's own non-empty-tray path", async () => {
    seedTrayItems(2);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ label_count: 2 }))));
    let capturedBody: { labels: LabelDefinition[]; serialization?: unknown } | undefined;
    server.use(
      http.post("/api/print", async ({ request }) => {
        capturedBody = (await request.json()) as typeof capturedBody;
        return HttpResponse.json({ job_id: "job-global-1" }, { status: 202 });
      }),
    );
    const user = userEvent.setup();

    renderWithProviders(<GlobalTrayDrawer />);
    await user.click(await screen.findByRole("button", { name: /^Tray · 2/ }));

    const printButton = await screen.findByRole("button", { name: "Print 2 labels (tray)" });
    await user.click(printButton);

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody?.labels).toEqual([def("ITEM-0"), def("ITEM-1")]);
    expect(capturedBody?.serialization).toBeUndefined();
  });
});

describe("GlobalTrayDrawer -- tray item previews (useTrayPreviews)", () => {
  it("fetches and renders a preview (png + length) for an item queued with neither of its own (e.g. HomeBox's 'Add to tray')", async () => {
    useTrayStore.getState().addItem({ definition: def("HB"), png: null, lengthMm: null, label: "HomeBox — Shelf A" });
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    const user = userEvent.setup();

    const { container } = renderWithProviders(<GlobalTrayDrawer />);
    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));

    await waitFor(() =>
      expect(container.querySelector(`img[src="data:image/png;base64,${TINY_PNG_B64}"]`)).toBeInTheDocument(),
    );
    // previewHandler's own fixture length_mm (test/msw/handlers.ts).
    expect(screen.getByText("25.4 mm")).toBeInTheDocument();
  });
});

// The describe blocks below moved here (adapted from the Designer-only
// `current` prop to stores/currentDesign.ts, the SAME store
// pages/Designer.tsx now writes) from the now-deleted
// components/JobTray.test.tsx, as part of unifying the Designer page's own
// tray into this component -- GlobalTrayDrawer is now the ONE place a
// "current, unsaved design" (only ever non-null on the Design route) can
// power an empty-tray print fallback and "+ Add to tray".
describe("GlobalTrayDrawer -- current design (Design route)", () => {
  it('shows the empty-state prompt and "Print 1 label" for the current design when the tray is empty', async () => {
    useCurrentDesignStore.setState({ current: currentDesign() });
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    const user = userEvent.setup();

    renderWithProviders(<GlobalTrayDrawer />);
    await user.click(await screen.findByRole("button", { name: "Tray" }));

    expect(await screen.findByText(/Nothing queued\. Design a label and add it to print several at once\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print 1 label" })).toBeInTheDocument();
  });

  it("empty tray: Print POSTs a body whose `labels` is just the current design", async () => {
    useCurrentDesignStore.setState({ current: currentDesign() });
    const user = userEvent.setup();
    let capturedBody: { labels: LabelDefinition[] } | undefined;
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())),
      http.post("/api/print", async ({ request }) => {
        capturedBody = (await request.json()) as typeof capturedBody;
        return HttpResponse.json({ job_id: "job-1" }, { status: 202 });
      }),
    );

    renderWithProviders(<GlobalTrayDrawer />);
    await user.click(await screen.findByRole("button", { name: "Tray" }));
    const printButton = await screen.findByRole("button", { name: "Print 1 label" });
    await user.click(printButton);

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody?.labels).toEqual([def("CURRENT")]);
  });

  it("non-empty tray: Print POSTs the tray's own items, NOT the current design", async () => {
    useCurrentDesignStore.setState({ current: currentDesign() });
    seedTrayItems(2);
    const user = userEvent.setup();
    let capturedBody: { labels: LabelDefinition[] } | undefined;
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ label_count: 2 }))),
      http.post("/api/print", async ({ request }) => {
        capturedBody = (await request.json()) as typeof capturedBody;
        return HttpResponse.json({ job_id: "job-2" }, { status: 202 });
      }),
    );

    renderWithProviders(<GlobalTrayDrawer />);
    await user.click(await screen.findByRole("button", { name: /^Tray · 2/ }));
    const printButton = await screen.findByRole("button", { name: "Print 2 labels (tray)" });
    await user.click(printButton);

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody?.labels).toEqual([def("ITEM-0"), def("ITEM-1")]);
  });

  it("serialization on + a non-empty tray blocks Print with a clear message instead of ever POSTing", async () => {
    useCurrentDesignStore.setState({
      current: currentDesign({ serializationEnabled: true, serialization: { kind: "numeric", count: 5 }, totalLabels: 5 }),
    });
    seedTrayItems(1);
    const user = userEvent.setup();
    const printSpy = vi.fn();
    server.use(
      http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())),
      http.post("/api/print", () => {
        printSpy();
        return HttpResponse.json({ job_id: "job-x" }, { status: 202 });
      }),
    );

    renderWithProviders(<GlobalTrayDrawer />);
    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/can't be combined/);
    const printButton = screen.getByRole("button", { name: "Print 1 label (tray)" });
    expect(printButton).toBeDisabled();

    await user.click(printButton);
    expect(printSpy).not.toHaveBeenCalled();
  });
});

describe("GlobalTrayDrawer -- adding from the current design, and item controls", () => {
  it("+ Add to tray adds a DEEP-COPIED snapshot to the real store, and up/duplicate/remove work through it", async () => {
    useCurrentDesignStore.setState({ current: currentDesign() });
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    const user = userEvent.setup();

    renderWithProviders(<GlobalTrayDrawer />);
    await user.click(await screen.findByRole("button", { name: "Tray" }));

    await user.click(await screen.findByRole("button", { name: "+ Add to tray" }));
    expect(await screen.findByText("Text — CURRENT")).toBeInTheDocument();
    expect(useTrayStore.getState().items).toHaveLength(1);

    // Deep copy, not a live reference: mutating the queued item's
    // definition must never retroactively change the current-design
    // store's own copy (or vice versa) -- the exact regression the old
    // pages/Designer.tsx snapshot logic (structuredClone) guarded against,
    // now moved into this component's own `handleAddToTray`.
    const queuedDefinition = useTrayStore.getState().items[0]!.definition;
    expect(queuedDefinition).toEqual(def("CURRENT"));
    expect(queuedDefinition).not.toBe(useCurrentDesignStore.getState().current!.definition);

    await user.click(await screen.findByRole("button", { name: "+ Add to tray" }));
    expect(useTrayStore.getState().items).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Duplicate item 1" }));
    expect(useTrayStore.getState().items).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: "Move item 2 up" }));
    await user.click(screen.getByRole("button", { name: "Remove item 1" }));
    expect(useTrayStore.getState().items).toHaveLength(2);
  });
});

/** Dockable-tray feature -- mirrors PrintPreviewDeck.test.tsx's own
 * "dockable preview" block precisely (same store shape, same class/
 * semantics contract, just tray-flavored names/labels): stores/trayDrawer.ts
 * instead of stores/printPreview.ts, "Dock tray"/"Undock tray" instead of
 * "Dock preview"/"Undock preview", "Print tray" instead of "Print preview". */
describe("GlobalTrayDrawer -- dockable tray", () => {
  it("the dock toggle flips the store's `docked` flag, and its accessible name flips with it", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    await screen.findByRole("dialog", { name: "Print tray" });

    const dockButton = screen.getByRole("button", { name: "Dock tray" });
    await user.click(dockButton);

    expect(useTrayDrawerStore.getState().docked).toBe(true);
    expect(screen.getByRole("button", { name: "Undock tray" })).toBeInTheDocument();
  });

  it("docked + open swaps in a complementary landmark -- no scrim, no aria-modal, no dialog role", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    useTrayDrawerStore.setState({ docked: true });
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    const panel = await screen.findByRole("complementary", { name: "Print tray" });

    expect(panel).not.toHaveAttribute("aria-modal");
    expect(document.querySelector('[aria-hidden][class*="bg-scrim/70"]')).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Print tray" })).not.toBeInTheDocument();
  });

  it("undocked + open keeps today's dialog semantics and scrim, unchanged", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    const panel = await screen.findByRole("dialog", { name: "Print tray" });

    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(document.querySelector('[aria-hidden][class*="bg-scrim/70"]')).not.toBeNull();
  });

  it("close still works while docked, without stealing focus onto the close button", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    useTrayDrawerStore.setState({ docked: true });
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    const trigger = await screen.findByRole("button", { name: /^Tray · 1/ });
    await user.click(trigger);
    await screen.findByRole("complementary", { name: "Print tray" });

    // Docked mode skips the focus-steal contract entirely (see
    // GlobalTrayDrawer.tsx's own docstring) -- the close button never gets
    // programmatic focus the way it does when undocked.
    expect(screen.getByRole("button", { name: "Close print tray" })).not.toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Close print tray" }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Print tray" })).not.toBeInTheDocument());
    expect(useTrayDrawerStore.getState().open).toBe(false);
    // `docked` itself is untouched by closing -- remembered for next open
    // (stores/trayDrawer.ts's own persisted preference).
    expect(useTrayDrawerStore.getState().docked).toBe(true);
  });

  it("Escape does nothing while docked -- no Escape-to-close", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    useTrayDrawerStore.setState({ docked: true });
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    await screen.findByRole("complementary", { name: "Print tray" });

    await user.keyboard("{Escape}");
    expect(screen.getByRole("complementary", { name: "Print tray" })).toBeInTheDocument();
    expect(useTrayDrawerStore.getState().open).toBe(true);
  });

  it("carries the unconditional xl:static in-flow-column class contract while docked AND open, regardless of the preview deck's own state", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    useTrayDrawerStore.setState({ docked: true });
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    await screen.findByRole("complementary", { name: "Print tray" });

    const panel = screen.getByTestId("global-tray-drawer-panel");
    expect(panel.className).toContain("xl:static");
    expect(panel.className).toContain("xl:inset-auto");
    expect(panel.className).toContain("xl:w-[26rem]");
    expect(panel.className).toContain("xl:border-l");
    expect(panel.className).toContain("xl:min-h-0");
    // NOT xl:shrink-0 (viewport-bound-frame fix): this panel has no
    // explicit height of its own, so it must be allowed to shrink to the
    // dock rail's actual (viewport-bound) height, letting its own base
    // `overflow-y-auto` scroll a tall tray internally instead of
    // overflowing the rail and growing the page past the viewport.
    expect(panel.className).not.toContain("xl:shrink-0");
    // The tray panel no longer knows or cares about the preview deck's own
    // docked/open state (Task 5 restructure moved the deck to a root-level
    // sibling, its own full-width bottom band) -- there is no state where
    // `xl:max-h-[50%]` should appear anymore.
    expect(panel.className).not.toContain("xl:max-h-[50%]");
    // Docked mode drops the slide transition entirely -- nothing to
    // animate once it's back in normal flow.
    expect(panel.className).not.toContain("transition-transform");

    // Docking the preview deck too must NOT change the tray panel's own
    // class string -- confirms the two panels are fully decoupled now.
    usePrintPreviewStore.setState({ docked: true, open: true });
    expect(panel.className).not.toContain("xl:max-h-[50%]");
  });

  it("a closed docked panel is hidden exactly like an undocked one -- no xl: override leaks through while closed", () => {
    useTrayDrawerStore.setState({ docked: true });
    renderWithProviders(<GlobalTrayDrawer />);

    const panel = screen.getByTestId("global-tray-drawer-panel");
    expect(panel).not.toHaveAttribute("role");
    expect(panel.className).toContain("invisible");
    expect(panel.className).toContain("translate-x-full");
    expect(panel.className).not.toContain("xl:static");
  });

  it("a docked tray does not close itself when 'Preview' opens the chain preview drawer -- only an UNDOCKED tray does that", async () => {
    seedTrayItems(2);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ label_count: 2 }))));
    useTrayDrawerStore.setState({ docked: true });
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 2/ }));
    await screen.findByRole("complementary", { name: "Print tray" });

    await user.click(screen.getByRole("button", { name: "Preview" }));

    expect(usePrintPreviewStore.getState().open).toBe(true);
    // Unlike the undocked case (PrintPreviewDeck.test.tsx's own
    // "opening the chain preview... closes the GlobalTrayDrawer slide-over"
    // test), a docked tray stays open -- see TrayPanel.tsx's own
    // `closeTrayDrawer` prop doc and GlobalTrayDrawer.tsx's own docstring
    // for why `closeTrayDrawer` is only ever passed while undocked.
    expect(useTrayDrawerStore.getState().open).toBe(true);
    expect(screen.getByRole("complementary", { name: "Print tray" })).toBeInTheDocument();
  });
});
