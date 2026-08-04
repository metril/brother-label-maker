import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { GlobalTrayDrawer } from "./GlobalTrayDrawer";
import { usePrintPreviewStore } from "../stores/printPreview";
import { useCurrentDesignStore, type CurrentDesign } from "../stores/currentDesign";
import { useTrayDrawerStore } from "../stores/trayDrawer";
import { useTrayStore } from "../stores/tray";
import { DESKTOP_QUERY } from "../hooks/useIsDesktop";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { setMediaQueryMatches } from "../test/setup";
import { TINY_PNG_B64 } from "../test/msw/handlers";
import type { LabelDefinition, PrintEstimateResponse } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();
const INITIAL_TRAY_DRAWER_STATE = useTrayDrawerStore.getState();
const INITIAL_CHAIN_PREVIEW_STATE = usePrintPreviewStore.getState();

afterEach(() => {
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
  useCurrentDesignStore.setState({ current: null });
  // `open` is persisted via zustand's own `persist` middleware, so a test
  // that opens the panel must not leak that into the next one via the
  // in-memory store singleton (test/setup.ts's own `localStorage.clear()`
  // only covers the localStorage side of that, not this module's
  // already-hydrated state) -- same reasoning PrintPreviewDeck.test.tsx's
  // own afterEach already documents for stores/printPreview.ts.
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
  // GlobalTrayPanel stays permanently mounted (unlike the pre-split
  // component, which returned null outright, gating the panel too) -- see
  // GlobalTrayDrawer.tsx's own top-of-file docstring for why (an in-flight
  // print job's state must survive) -- so an empty tray with no current
  // design hides only the trigger BUTTON; the panel itself renders
  // present-but-hidden, the exact resting state PrintPreviewDeck's own
  // panel already has with nothing to preview.
  it("hides the trigger button, but keeps the panel mounted and hidden, when there's nothing queued", () => {
    renderWithProviders(<GlobalTrayDrawer />);
    expect(screen.queryByRole("button", { name: /^Tray/ })).not.toBeInTheDocument();

    const panel = screen.getByTestId("global-tray-drawer-panel");
    expect(panel).not.toHaveAttribute("role");
    expect(panel.className).toContain("invisible");
    expect(panel.className).toContain("translate-x-full");
  });

  it('keeps the trigger visible, with aria-expanded="true", when the panel is open, even with nothing queued', () => {
    // `open` is persisted (stores/trayDrawer.ts), so it can survive into an
    // empty-tray state (e.g. printing empties the tray while the panel is
    // still open) -- the trigger must stay reachable to close it from.
    useTrayDrawerStore.setState({ open: true });
    renderWithProviders(<GlobalTrayDrawer />);

    const trigger = screen.getByRole("button", { name: "Tray" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
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

  it("is a toggle: clicking the header button again while open closes the panel", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    const user = userEvent.setup();

    renderWithProviders(<GlobalTrayDrawer />);
    const trigger = await screen.findByRole("button", { name: /^Tray · 1/ });

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(screen.getByRole("button", { name: "Close print tray" })).toHaveFocus());

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("global-tray-drawer-panel")).not.toHaveAttribute("role");
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

/** At `xl` and up, an open tray always renders as an in-flow, non-modal
 * `role="complementary"` column; below `xl` it's always today's modal
 * overlay -- see GlobalTrayDrawer.tsx's own docstring. Driven by
 * `setMediaQueryMatches(DESKTOP_QUERY, ...)` (test/setup.ts) rather than
 * any store flag -- there is no more dock/undock choice, just the `open`
 * boolean stores/trayDrawer.ts already had. */
describe("GlobalTrayDrawer -- at-xl in-flow panel vs. below-xl modal overlay", () => {
  it("at xl + open swaps in a complementary landmark -- no scrim, no aria-modal, no dialog role", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    const panel = await screen.findByRole("complementary", { name: "Print tray" });

    expect(panel).not.toHaveAttribute("aria-modal");
    expect(document.querySelector('[aria-hidden][class*="bg-scrim/70"]')).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Print tray" })).not.toBeInTheDocument();
  });

  it("below xl + open keeps today's dialog semantics and scrim, unchanged", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    const panel = await screen.findByRole("dialog", { name: "Print tray" });

    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(document.querySelector('[aria-hidden][class*="bg-scrim/70"]')).not.toBeNull();
  });

  it("close still works at xl, without stealing focus onto the close button", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    const trigger = await screen.findByRole("button", { name: /^Tray · 1/ });
    await user.click(trigger);
    await screen.findByRole("complementary", { name: "Print tray" });

    // At `xl` the focus-steal contract is skipped entirely (see
    // GlobalTrayDrawer.tsx's own docstring) -- the close button never gets
    // programmatic focus the way it does below `xl`.
    expect(screen.getByRole("button", { name: "Close print tray" })).not.toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Close print tray" }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Print tray" })).not.toBeInTheDocument());
    expect(useTrayDrawerStore.getState().open).toBe(false);
  });

  // Focus-to-<body> fix: below `xl` the modal effect captures the trigger
  // itself, but at `xl` that effect is skipped entirely (it's a landmark,
  // not a modal) -- without the always-on capture/restore effect
  // (GlobalTrayDrawer.tsx's own docstring), the × button here found nothing
  // captured and silently dropped focus onto <body> instead of restoring it
  // to the header trigger.
  it("returns focus to the trigger when the close button is clicked at xl", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    const trigger = await screen.findByRole("button", { name: /^Tray · 1/ });
    await user.click(trigger);
    await screen.findByRole("complementary", { name: "Print tray" });

    await user.click(screen.getByRole("button", { name: "Close print tray" }));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("Escape does nothing at xl -- no Escape-to-close", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    await screen.findByRole("complementary", { name: "Print tray" });

    await user.keyboard("{Escape}");
    expect(screen.getByRole("complementary", { name: "Print tray" })).toBeInTheDocument();
    expect(useTrayDrawerStore.getState().open).toBe(true);
  });

  it("carries the xl:static in-flow-column class contract whenever open, regardless of viewport or the preview deck's own state", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    await screen.findByRole("dialog", { name: "Print tray" });

    const panel = screen.getByTestId("global-tray-drawer-panel");
    // The `xl:` class group is gated on `open` alone now, not on any
    // breakpoint/JS state -- it's present in the class string here even
    // though this test never opts into the desktop viewport (default
    // jsdom, below `xl`), left for the browser's own `xl:` media query to
    // actually switch on. See GlobalTrayDrawer.tsx's own docstring.
    expect(panel.className).toContain("xl:static");
    expect(panel.className).toContain("xl:inset-auto");
    expect(panel.className).toContain("xl:w-[26rem]");
    // xl:max-w-none (M-review fix): the base `max-w-sm` (24rem) otherwise
    // clamps the xl:-only width override above, so the desktop column
    // rendered 24rem instead of the intended 26rem.
    expect(panel.className).toContain("xl:max-w-none");
    expect(panel.className).toContain("xl:border-l");
    expect(panel.className).toContain("xl:min-h-0");
    // xl:overflow-hidden (fixed-panel fix): overrides the base
    // `overflow-y-auto` so the panel itself never scrolls at `xl` --
    // components/TrayPanel.tsx's own items list is the ONE region that
    // scrolls there (see the structural test below); the panel must fit its
    // available height instead of growing/scrolling as a whole.
    expect(panel.className).toContain("xl:overflow-hidden");
    // xl:gap-3 (height-budget squeeze): tightens the base `gap-4` between
    // this div's own header/TrayPanel children, at `xl` only -- part of the
    // same live-measured fix as TrayPanel.tsx's own compactions.
    expect(panel.className).toContain("xl:gap-3");
    // NOT xl:shrink-0 (viewport-bound-frame fix): this panel has no
    // explicit height of its own, so it must be allowed to shrink to
    // whatever its wrapping subtree's actual (viewport-bound) height is
    // instead of overflowing and growing the page past the viewport.
    expect(panel.className).not.toContain("xl:shrink-0");
    // The tray panel no longer knows or cares about the preview deck's own
    // open state (the two panels are fully decoupled, each mounted at its
    // own root-level spot) -- there is no state where `xl:max-h-[50%]`
    // should appear anymore.
    expect(panel.className).not.toContain("xl:max-h-[50%]");

    // Opening the preview deck too must NOT change the tray panel's own
    // class string -- confirms the two panels are fully decoupled now.
    usePrintPreviewStore.setState({ open: true });
    expect(panel.className).not.toContain("xl:max-h-[50%]");
  });

  // Fixed-panel requirement: at `xl`, the panel itself must fit its
  // available height with NO panel-level scrolling -- only
  // components/TrayPanel.tsx's own items list scrolls. This pins the actual
  // desktop viewport shape (unlike the test above, which only checks the
  // class string is present regardless of viewport).
  it("at xl + open: the panel carries xl:overflow-hidden and only the items list's own wrapper is the scrolling region", async () => {
    seedTrayItems(1);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody())));
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 1/ }));
    await screen.findByRole("complementary", { name: "Print tray" });

    const panel = screen.getByTestId("global-tray-drawer-panel");
    expect(panel.className).toContain("xl:overflow-hidden");

    // The items <ul> (implicit role "list") is wrapped in a div that's the
    // ONE flexible, scrolling region at `xl` -- everything else in the
    // panel (header, add-to-tray/Mode/Auto-cut/estimate/Preview/Print) is
    // `xl:shrink-0` instead.
    const itemsList = screen.getByRole("list");
    const scroller = itemsList.parentElement!;
    expect(scroller.className).toContain("xl:flex-1");
    expect(scroller.className).toContain("xl:min-h-0");
    expect(scroller.className).toContain("xl:overflow-y-auto");
  });

  it("a closed panel is hidden regardless of viewport -- no xl: override leaks through while closed", () => {
    setMediaQueryMatches(DESKTOP_QUERY, true);
    renderWithProviders(<GlobalTrayDrawer />);

    const panel = screen.getByTestId("global-tray-drawer-panel");
    expect(panel).not.toHaveAttribute("role");
    expect(panel.className).toContain("invisible");
    expect(panel.className).toContain("translate-x-full");
    expect(panel.className).not.toContain("xl:static");
  });

  it("an at-xl tray does not close itself when 'Preview' opens the chain preview panel -- only a below-xl tray does that", async () => {
    seedTrayItems(2);
    server.use(http.post("/api/print/estimate", () => HttpResponse.json(estimateBody({ label_count: 2 }))));
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<GlobalTrayDrawer />);

    await user.click(await screen.findByRole("button", { name: /^Tray · 2/ }));
    await screen.findByRole("complementary", { name: "Print tray" });

    await user.click(screen.getByRole("button", { name: "Preview" }));

    expect(usePrintPreviewStore.getState().open).toBe(true);
    // Unlike the below-xl case (PrintPreviewDeck.test.tsx's own
    // "opening the chain preview... closes the GlobalTrayDrawer overlay"
    // test), an at-xl tray stays open -- see TrayPanel.tsx's own
    // `closeTrayDrawer` prop doc and GlobalTrayDrawer.tsx's own docstring
    // for why `closeTrayDrawer` is only ever passed below `xl`.
    expect(useTrayDrawerStore.getState().open).toBe(true);
    expect(screen.getByRole("complementary", { name: "Print tray" })).toBeInTheDocument();
  });
});
