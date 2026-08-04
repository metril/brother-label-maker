import { afterEach, describe, expect, it } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { PrintPreviewDeck } from "./PrintPreviewDeck";
import { GlobalTrayDrawer } from "./GlobalTrayDrawer";
import { DESKTOP_QUERY } from "../hooks/useIsDesktop";
import { usePrintPreviewStore } from "../stores/printPreview";
import { useTrayDrawerStore } from "../stores/trayDrawer";
import { useTrayStore } from "../stores/tray";
import { TINY_PNG_B64 } from "../test/msw/handlers";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { setMediaQueryMatches } from "../test/setup";
import type { LabelDefinition } from "../api/types";

const INITIAL_TRAY_STATE = useTrayStore.getState();
const INITIAL_CHAIN_PREVIEW_STATE = usePrintPreviewStore.getState();
const INITIAL_TRAY_DRAWER_STATE = useTrayDrawerStore.getState();

afterEach(() => {
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
  // Full reset (not just `open`) -- `open`/`selectedIndex` are shared
  // module-level state (the latter session-only, the former persisted via
  // zustand's own `persist` middleware), so a test that touches either must
  // not leak into the next one via the in-memory store singleton (test/
  // setup.ts's own `localStorage.clear()` only covers the localStorage side
  // of `open`, not this module's already-hydrated state).
  usePrintPreviewStore.setState(INITIAL_CHAIN_PREVIEW_STATE, true);
  // Same reasoning as usePrintPreviewStore above -- the mutual-exclusion
  // tests below touch this store's `open` directly.
  useTrayDrawerStore.setState(INITIAL_TRAY_DRAWER_STATE, true);
});

function def(text: string): LabelDefinition {
  return { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: [text] } };
}

function seedTrayItems(n: number) {
  for (let i = 0; i < n; i++) {
    useTrayStore.getState().addItem({ definition: def(`ITEM-${i}`), png: null, lengthMm: 20 + i, label: `Text — ITEM-${i}` });
  }
}

/** PrintPreviewDeck reads its own `open` flag off stores/printPreview.ts
 * (shared, module-level -- see that store's own docstring) rather than
 * local/prop-driven state, so a tiny harness stands in for whichever real
 * TrayPanel instance would normally call `openDrawer()` -- same role the
 * old ChainedPreviewDialog.test.tsx's own Harness played for that dialog's
 * `open` prop, just sourced from the store instead of component state. */
function Harness() {
  const openDrawer = usePrintPreviewStore((s) => s.openDrawer);
  return (
    <>
      <button type="button" onClick={openDrawer}>
        Open
      </button>
      <PrintPreviewDeck />
    </>
  );
}

describe("PrintPreviewDeck", () => {
  it("opens with the composite PNG, the correct segment count, and the stats row", async () => {
    seedTrayItems(2);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });

    const img = await within(drawer).findByAltText("Print preview strip");
    expect(img).toHaveAttribute("src", `data:image/png;base64,${TINY_PNG_B64}`);

    // The default printPreviewHandler returns exactly 2 segments.
    expect(within(drawer).getByTestId("segment-chip-0")).toHaveTextContent("1");
    expect(within(drawer).getByTestId("segment-chip-1")).toHaveTextContent("2");
    expect(within(drawer).queryByTestId("segment-chip-2")).not.toBeInTheDocument();

    expect(within(drawer).getByTestId("preview-total-mm")).toHaveTextContent("60.0 mm");
    // The UNVERIFIED disclaimer now lives behind the notes disclosure
    // (collapsed by default, rendered via the `hidden` attribute rather
    // than unmounted -- see PrintPreviewDeck.tsx's own comment on why: the
    // "Notes" button's aria-controls must always point at a real element)
    // -- see the dedicated "notes disclosure" describe block below for the
    // expand/collapse contract itself.
    expect(within(drawer).getByText(/UNVERIFIED estimate/)).not.toBeVisible();
  });

  it("switching chain mode from the Tray refetches the preview with the new chain_mode, and the deck's read-only label reflects it", async () => {
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

    renderWithProviders(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });

    await waitFor(() => expect(capturedModes).toEqual(["cut_each"]));
    expect(within(drawer).getByTestId("deck-mode-label")).toHaveTextContent("Cut each");

    // The deck has no mode control of its own (mode unification) -- the
    // ONLY way to change it is via the Tray's own store, the same store
    // TrayPanel.tsx's own radiogroup writes to.
    useTrayStore.setState({ chainMode: "chain_ff" });

    await waitFor(() => expect(capturedModes).toEqual(["cut_each", "chain_ff"]));
    expect(within(drawer).getByTestId("deck-mode-label")).toHaveTextContent("Cut at end");
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
    const img = await within(drawer).findByAltText("Print preview strip");

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
    const img = await within(drawer).findByAltText("Print preview strip");

    // The tray items' tape is 24mm/tze (see `def`); the tapes fixture's
    // matching row has print_mm: 18.1. At the deck's opening zoom
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

  it("shows 'Nothing queued to print.' when the tray is empty, and fires no preview request at all (the current-design fallback was removed)", async () => {
    let requestCount = 0;
    server.use(
      http.post("/api/print/preview", () => {
        requestCount++;
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
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    expect(within(drawer).getByText("Nothing queued to print.")).toBeInTheDocument();
    expect(within(drawer).getByText("Add labels to the tray to preview the job.")).toBeInTheDocument();
    expect(requestCount).toBe(0);
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
    await within(drawer).findByAltText("Print preview strip");

    expect(within(drawer).getByRole("alert")).toHaveTextContent("label 1: text may be cramped at this tape width");
    // Warnings stay unconditionally visible even though the notes/
    // disclaimer disclosure is collapsed by default (see PrintPreviewDeck's
    // own Group C docstring) -- a warning must never hide behind a click.
    expect(within(drawer).getByRole("button", { name: "Notes" })).toHaveAttribute("aria-expanded", "false");
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

  it("opening the print preview from TrayPanel's own button closes the GlobalTrayDrawer slide-over, and restores focus there on close", async () => {
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
        <PrintPreviewDeck />
      </>,
    );

    const trayTrigger = await screen.findByRole("button", { name: /^Tray · 2/ });
    await user.click(trayTrigger);
    await screen.findByRole("dialog", { name: "Print tray" });

    await user.click(screen.getByRole("button", { name: "Preview" }));

    // Both slide-overs occupy the right edge -- opening the print preview
    // deck closes the tray drawer rather than stacking on top of it (see
    // TrayPanel.tsx's own `closeTrayDrawer` prop doc).
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Print tray" })).not.toBeInTheDocument());
    const previewDeck = await screen.findByRole("dialog", { name: "Print preview" });
    expect(previewDeck).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Close print preview" })).toHaveFocus());

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Print preview" })).not.toBeInTheDocument());
    // Focus returns to GlobalTrayDrawer's own trigger -- the button that
    // was focused (by `closeTrayDrawer`'s own `dialog.close()`) the instant
    // the print preview deck opened, not the (now hidden) "Preview" button
    // nested inside the tray drawer's own panel.
    await waitFor(() => expect(trayTrigger).toHaveFocus());
  });
});

/** Stacked-modal fix: two `aria-modal` overlays (the tray drawer and this
 * deck) must never coexist below `xl`. TrayPanel's own "Preview" button
 * already prevents one path (covered by the test just above -- opening the
 * deck from that button closes the tray first) -- these cover the other
 * two paths a click-time guard alone can't reach: rehydrating with BOTH
 * stores' `open` persisted true, and shrinking the window below `xl` while
 * both happened to be open at `xl` (where coexisting is fine, see
 * PrintPreviewDeck.tsx's own docstring). Both are handled by this deck's
 * own reconciliation effect, which always wins in favor of the deck -- see
 * that effect's own comment for why it's deliberately one-directional. */
describe("PrintPreviewDeck -- mutual exclusion with the tray drawer below `xl`", () => {
  it("both stores persisted open + a fresh mount below xl: the deck stays open, the tray closes itself", async () => {
    seedTrayItems(1);
    useTrayDrawerStore.setState({ open: true });
    usePrintPreviewStore.setState({ open: true });

    renderWithProviders(
      <>
        <GlobalTrayDrawer />
        <PrintPreviewDeck />
      </>,
    );

    await screen.findByRole("dialog", { name: "Print preview" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Print tray" })).not.toBeInTheDocument());
    expect(useTrayDrawerStore.getState().open).toBe(false);
    expect(usePrintPreviewStore.getState().open).toBe(true);
  });

  it("shrinking below xl while both panels are open at xl closes the tray, keeps the deck open", async () => {
    seedTrayItems(1);
    setMediaQueryMatches(DESKTOP_QUERY, true);
    useTrayDrawerStore.setState({ open: true });
    usePrintPreviewStore.setState({ open: true });

    renderWithProviders(
      <>
        <GlobalTrayDrawer />
        <PrintPreviewDeck />
      </>,
    );

    await screen.findByRole("complementary", { name: "Print preview" });
    await screen.findByRole("complementary", { name: "Print tray" });

    act(() => setMediaQueryMatches(DESKTOP_QUERY, false));

    await waitFor(() => expect(useTrayDrawerStore.getState().open).toBe(false));
    expect(usePrintPreviewStore.getState().open).toBe(true);
  });

  it("opening the tray from the header while the deck overlay is open (below xl) closes the deck", async () => {
    seedTrayItems(1);
    usePrintPreviewStore.setState({ open: true });
    const user = userEvent.setup();

    renderWithProviders(
      <>
        <GlobalTrayDrawer />
        <PrintPreviewDeck />
      </>,
    );

    await screen.findByRole("dialog", { name: "Print preview" });
    const trayTrigger = await screen.findByRole("button", { name: /^Tray · 1/ });
    await user.click(trayTrigger);

    await screen.findByRole("dialog", { name: "Print tray" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Print preview" })).not.toBeInTheDocument());
    expect(usePrintPreviewStore.getState().open).toBe(false);
  });
});

/** Part 2: cycling through the queued labels inside the preview -- the
 * default printPreviewHandler fixture (test/msw/handlers.ts) returns a
 * deterministic 2-segment response, enough for the basic cycler/highlight
 * assertions; a few tests below override with server.use(...) for a
 * 3-segment response (mirrors/echoes the posted label count) where the
 * default's fixed 2 wouldn't exercise the interesting middle-of-the-list
 * step, or a mismatched tray/segment count to hit the "Label N" fallback. */
describe("PrintPreviewDeck -- cycling through queued labels", () => {
  it("renders a cycler above the strip once segments.length >= 2 (default 2-segment fixture), names from tray items, clamped at both ends", async () => {
    seedTrayItems(2);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");

    const status = within(drawer).getByTestId("segment-cycler-status");
    const previous = within(drawer).getByRole("button", { name: "Previous label" });
    const next = within(drawer).getByRole("button", { name: "Next label" });

    // Starts at the first segment -- Previous is clamped/disabled already.
    expect(status).toHaveTextContent("1 of 2 — Text — ITEM-0");
    expect(previous).toBeDisabled();
    expect(next).toBeEnabled();

    await user.click(next);
    expect(status).toHaveTextContent("2 of 2 — Text — ITEM-1");
    expect(previous).toBeEnabled();
    expect(next).toBeDisabled();

    // Clamped at the end -- clicking Next again (were it not disabled)
    // must not walk past the last segment or wrap back to the first.
    await user.click(next);
    expect(status).toHaveTextContent("2 of 2 — Text — ITEM-1");
  });

  it("moves the selected-segment highlight's inline left/width style along with the cycler", async () => {
    seedTrayItems(2);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");

    // Default fixture: segment 0 is [0, 25]mm, segment 1 is [25, 50]mm; the
    // deck opens at DEFAULT_PX_PER_MM (4) -- 0/100px, then 100/100px.
    const highlight = within(drawer).getByTestId("segment-highlight");
    expect(highlight.style.left).toBe("0px");
    expect(highlight.style.width).toBe("100px");

    await user.click(within(drawer).getByRole("button", { name: "Next label" }));

    expect(highlight.style.left).toBe("100px");
    expect(highlight.style.width).toBe("100px");
  });

  it("renders neither a cycler nor a highlight with exactly 1 segment", async () => {
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
          warnings: [],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");

    expect(within(drawer).queryByRole("button", { name: "Previous label" })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "Next label" })).not.toBeInTheDocument();
    expect(within(drawer).queryByTestId("segment-cycler")).not.toBeInTheDocument();
    expect(within(drawer).queryByTestId("segment-highlight")).not.toBeInTheDocument();
  });

  it("cycles through all three names on a 3-item tray/3-segment response", async () => {
    seedTrayItems(3);
    server.use(
      http.post("/api/print/preview", () =>
        HttpResponse.json({
          png_b64: TINY_PNG_B64,
          chain_mode: "cut_each",
          total_mm: 85,
          content_mm: 75,
          feed_overhead_mm: 10,
          per_label_mm: 25,
          notes: [],
          segments: [
            { index: 0, start_mm: 0, end_mm: 25, length_mm: 25 },
            { index: 1, start_mm: 25, end_mm: 50, length_mm: 25 },
            { index: 2, start_mm: 50, end_mm: 75, length_mm: 25 },
          ],
          warnings: [],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");

    const status = within(drawer).getByTestId("segment-cycler-status");
    const next = within(drawer).getByRole("button", { name: "Next label" });

    expect(status).toHaveTextContent("1 of 3 — Text — ITEM-0");
    await user.click(next);
    expect(status).toHaveTextContent("2 of 3 — Text — ITEM-1");
    await user.click(next);
    expect(status).toHaveTextContent("3 of 3 — Text — ITEM-2");
  });

  it("falls back to 'Label N' when the tray's item count doesn't match the returned segment count", async () => {
    seedTrayItems(2);
    server.use(
      http.post("/api/print/preview", () =>
        HttpResponse.json({
          png_b64: TINY_PNG_B64,
          chain_mode: "cut_each",
          total_mm: 85,
          content_mm: 75,
          feed_overhead_mm: 10,
          per_label_mm: 25,
          notes: [],
          // 3 segments vs. a 2-item tray -- a mismatch (e.g. a response
          // that raced a still-in-flight tray edit).
          segments: [
            { index: 0, start_mm: 0, end_mm: 25, length_mm: 25 },
            { index: 1, start_mm: 25, end_mm: 50, length_mm: 25 },
            { index: 2, start_mm: 50, end_mm: 75, length_mm: 25 },
          ],
          warnings: [],
        }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");

    expect(within(drawer).getByTestId("segment-cycler-status")).toHaveTextContent("1 of 3 — Label 1");
    await user.click(within(drawer).getByRole("button", { name: "Next label" }));
    expect(within(drawer).getByTestId("segment-cycler-status")).toHaveTextContent("2 of 3 — Label 2");
  });

  it("resets selectedIndex to 0 when the tray contents change while open", async () => {
    seedTrayItems(2);
    server.use(
      http.post("/api/print/preview", async ({ request }) => {
        const body = (await request.json()) as { labels?: unknown[] };
        const n = body.labels?.length ?? 0;
        return HttpResponse.json({
          png_b64: TINY_PNG_B64,
          chain_mode: "cut_each",
          total_mm: n * 25 + 10,
          content_mm: n * 25,
          feed_overhead_mm: 10,
          per_label_mm: 25,
          notes: [],
          segments: Array.from({ length: n }, (_, i) => ({
            index: i,
            start_mm: i * 25,
            end_mm: (i + 1) * 25,
            length_mm: 25,
          })),
          warnings: [],
        });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");

    await user.click(within(drawer).getByRole("button", { name: "Next label" }));
    await waitFor(() => expect(within(drawer).getByTestId("segment-cycler-status")).toHaveTextContent("2 of 2"));

    // Switching to a new (3-label) request means the query key itself
    // changes -- the preview goes briefly back to `null` (a fresh key, no
    // cache hit) before the new response lands, which unmounts/remounts
    // this whole subtree. Re-query inside `waitFor` on every poll rather
    // than reusing an earlier node reference, which would go stale the
    // instant that remount happens.
    useTrayStore.getState().addItem({ definition: def("ITEM-2"), png: null, lengthMm: 20, label: "Text — ITEM-2" });

    await waitFor(() =>
      expect(within(drawer).getByTestId("segment-cycler-status")).toHaveTextContent("1 of 3 — Text — ITEM-0"),
    );
  });

  it("resets selectedIndex to 0 when the drawer is reopened", async () => {
    seedTrayItems(2);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    let drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");
    await user.click(within(drawer).getByRole("button", { name: "Next label" }));
    await waitFor(() => expect(within(drawer).getByTestId("segment-cycler-status")).toHaveTextContent("2 of 2"));

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Print preview" })).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Open" }));
    drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");
    expect(within(drawer).getByTestId("segment-cycler-status")).toHaveTextContent("1 of 2");
  });
});

describe("PrintPreviewDeck -- responsive deck (xl in-flow band vs. below-xl modal overlay)", () => {
  it("at `xl`, an open deck swaps in a complementary landmark -- no scrim, no aria-modal, no dialog role", async () => {
    seedTrayItems(1);
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const panel = await screen.findByRole("complementary", { name: "Print preview" });

    expect(panel).not.toHaveAttribute("aria-modal");
    expect(document.querySelector('[aria-hidden][class*="bg-scrim/70"]')).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Print preview" })).not.toBeInTheDocument();
    // At `xl` the panel drops the slide transition entirely (this
    // component's own docstring) -- nothing to animate once it's back in
    // normal flow.
    expect(panel.className).not.toContain("transition-transform");
  });

  it("below `xl` (jsdom default), open keeps today's dialog semantics and scrim, unchanged", async () => {
    seedTrayItems(1);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const panel = await screen.findByRole("dialog", { name: "Print preview" });

    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(document.querySelector('[aria-hidden][class*="bg-scrim/70"]')).not.toBeNull();
  });

  it("close still works at `xl`, without stealing focus onto the close button", async () => {
    seedTrayItems(1);
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    const trigger = screen.getByRole("button", { name: "Open" });
    await user.click(trigger);
    await screen.findByRole("complementary", { name: "Print preview" });

    // At `xl` the panel skips the focus-steal contract entirely (see this
    // component's own docstring) -- the close button never gets
    // programmatic focus the way it does below `xl`.
    expect(screen.getByRole("button", { name: "Close print preview" })).not.toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Close print preview" }));
    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "Print preview" })).not.toBeInTheDocument(),
    );
    expect(usePrintPreviewStore.getState().open).toBe(false);
  });

  // Focus-to-<body> fix: below `xl` the modal effect captures the trigger
  // itself, but at `xl` that effect is skipped entirely (it's a landmark,
  // not a modal) -- without the always-on capture/restore effect
  // (PrintPreviewDeck.tsx's own docstring), the × button here found nothing
  // captured and silently dropped focus onto <body> instead of restoring it
  // to the trigger.
  it("returns focus to the trigger when the close button is clicked at `xl`", async () => {
    seedTrayItems(1);
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    const trigger = screen.getByRole("button", { name: "Open" });
    await user.click(trigger);
    await screen.findByRole("complementary", { name: "Print preview" });

    await user.click(screen.getByRole("button", { name: "Close print preview" }));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("Escape does nothing at `xl` -- no Escape-to-close", async () => {
    seedTrayItems(1);
    setMediaQueryMatches(DESKTOP_QUERY, true);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("complementary", { name: "Print preview" });

    await user.keyboard("{Escape}");
    expect(screen.getByRole("complementary", { name: "Print preview" })).toBeInTheDocument();
    expect(usePrintPreviewStore.getState().open).toBe(true);
  });

  it("carries the xl:static in-flow bottom-deck class contract whenever the deck is open, independent of viewport (docking removed)", async () => {
    seedTrayItems(1);
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    // jsdom default (below `xl`) -- role is "dialog", but the `xl:` class
    // contract itself is no longer gated on a `docked` flag, only on
    // `open`, so it's present in the class string regardless of viewport
    // (the actual breakpoint match is left to real CSS, which jsdom never
    // evaluates).
    await screen.findByRole("dialog", { name: "Print preview" });

    const panel = screen.getByTestId("print-preview-deck-panel");
    expect(panel.className).toContain("xl:static");
    expect(panel.className).toContain("xl:h-64");
    expect(panel.className).toContain("xl:w-full");
    // No sticky positioning anymore (Opus review fix) -- AppShell.tsx's own
    // frame is viewport-bound (`h-screen` root), so this panel only needs
    // to be a plain in-flow block to land at the viewport bottom on its own.
    expect(panel.className).not.toContain("xl:sticky");
    // The old right-hand-column contract is gone entirely -- this is a
    // full-width bottom deck now, not a 26rem-wide side column.
    expect(panel.className).not.toContain("xl:w-[26rem]");
  });

  it("a closed panel is hidden the same way regardless of viewport -- no xl: override leaks through while closed", () => {
    setMediaQueryMatches(DESKTOP_QUERY, true);
    renderWithProviders(<Harness />);

    const panel = screen.getByTestId("print-preview-deck-panel");
    expect(panel).not.toHaveAttribute("role");
    expect(panel.className).toContain("invisible");
    expect(panel.className).toContain("translate-x-full");
    expect(panel.className).not.toContain("xl:sticky");
    expect(panel.className).not.toContain("xl:static");
  });
});

describe("PrintPreviewDeck -- notes disclosure", () => {
  function serveWithNotes() {
    server.use(
      http.post("/api/print/preview", () =>
        HttpResponse.json({
          png_b64: TINY_PNG_B64,
          chain_mode: "cut_each",
          total_mm: 30,
          content_mm: 25,
          feed_overhead_mm: 5,
          per_label_mm: 30,
          notes: ["label 1: trimmed to fit the tape width"],
          segments: [{ index: 0, start_mm: 0, end_mm: 25, length_mm: 25 }],
          warnings: [],
        }),
      ),
    );
  }

  it("is collapsed by default -- the notes region is present (aria-controls has a real target) but hidden until expanded", async () => {
    seedTrayItems(1);
    serveWithNotes();
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");

    const notesButton = within(drawer).getByRole("button", { name: "Notes" });
    expect(notesButton).toHaveAttribute("aria-expanded", "false");
    // The region itself always renders now (dangling aria-controls IDREF
    // fix) -- collapsed means hidden via the `hidden` attribute, not absent
    // from the DOM.
    const notesRegion = drawer.querySelector("#print-preview-notes");
    expect(notesRegion).not.toBeNull();
    expect(notesRegion).toHaveAttribute("hidden");
    expect(document.getElementById(notesButton.getAttribute("aria-controls")!)).toBe(notesRegion);
    expect(within(drawer).getByText(/trimmed to fit the tape width/)).not.toBeVisible();
    expect(within(drawer).getByText(/UNVERIFIED estimate/)).not.toBeVisible();
  });

  it("clicking Notes reveals the notes list and the UNVERIFIED disclaimer", async () => {
    seedTrayItems(1);
    serveWithNotes();
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const drawer = await screen.findByRole("dialog", { name: "Print preview" });
    await within(drawer).findByAltText("Print preview strip");

    const notesButton = within(drawer).getByRole("button", { name: "Notes" });
    await user.click(notesButton);

    expect(notesButton).toHaveAttribute("aria-expanded", "true");
    expect(within(drawer).getByText(/trimmed to fit the tape width/)).toBeInTheDocument();
    expect(within(drawer).getByText(/UNVERIFIED estimate/)).toBeInTheDocument();
  });
});
