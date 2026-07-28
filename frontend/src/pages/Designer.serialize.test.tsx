import { afterEach, describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Designer } from "./Designer";
import { useDesignerStore } from "../stores/designer";
import { useTrayStore } from "../stores/tray";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import { TINY_PNG_B64 } from "../test/msw/handlers";

// useDesignerStore/useTrayStore are module-level singletons (zustand) --
// reset after each test, same convention as Designer.test.tsx.
const INITIAL_STORE_STATE = useDesignerStore.getState();
const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_STORE_STATE, true);
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
});

/** The fixture's "text" type defaults to a single blank line -- give it
 * real, renderable content (with a `{seq}` token) so canSubmit(definition)
 * is true and the serialization machinery actually has something to work
 * with once the Serialize toggle goes on. */
async function typeLineWithToken(user: ReturnType<typeof userEvent.setup>) {
  const lines1 = await screen.findByLabelText("Lines 1");
  await user.type(lines1, "PORT-{seq}");
}

describe("Designer + serialization -- Print button label and request body", () => {
  it("serialization off: POSTs a print job with NO `serialization` key at all (regression: the plain path is untouched)", async () => {
    const user = userEvent.setup();
    let capturedBody: unknown;
    server.use(
      http.post("/api/print", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ job_id: "job-plain" }, { status: 202 });
      }),
    );

    renderWithProviders(<Designer />);
    await typeLineWithToken(user);

    // task 2.12: the empty-tray plain path now reads "Print 1 label" (an
    // explicit count) rather than a bare "Print".
    const printButton = await screen.findByRole("button", { name: "Print 1 label" });
    await waitFor(() => expect(printButton).not.toBeDisabled());
    await user.click(printButton);

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody).not.toHaveProperty("serialization");
  });

  it("turning serialization on and configuring a numeric run changes the Print button to 'Print N labels' and posts the serialization block", async () => {
    const user = userEvent.setup();
    let capturedBody: { serialization?: { kind: string; count: number } } | undefined;
    server.use(
      http.post("/api/print", async ({ request }) => {
        capturedBody = (await request.json()) as typeof capturedBody;
        return HttpResponse.json({ job_id: "job-serialized" }, { status: 202 });
      }),
    );

    renderWithProviders(<Designer />);
    await typeLineWithToken(user);

    await user.click(await screen.findByRole("checkbox", { name: "On" }));
    const count = await screen.findByLabelText("Count");
    await user.clear(count);
    await user.type(count, "24");

    const printButton = await screen.findByRole("button", { name: "Print 24 labels" }, { timeout: 3000 });
    await waitFor(() => expect(printButton).not.toBeDisabled());
    await user.click(printButton);

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody?.serialization?.kind).toBe("numeric");
    expect(capturedBody?.serialization?.count).toBe(24);
  });
});

describe("Designer + serialization -- over-cap blocks print", () => {
  it("a total over 1000 disables the Print CTA and shows the server's message inline", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Designer />);
    await typeLineWithToken(user);

    await user.click(await screen.findByRole("checkbox", { name: "On" }));
    const count = await screen.findByLabelText("Count");
    await user.clear(count);
    await user.type(count, "500");
    const copies = screen.getByLabelText("Copies per value");
    await user.clear(copies);
    await user.type(copies, "3");

    expect(await screen.findByText(/exceeds the 1000 maximum/, {}, { timeout: 3000 })).toBeInTheDocument();
    // Still on the plain-count "Print 1 label" (never resolved to a real,
    // serialized N), and disabled -- serialization is on, so the resolved-N
    // label doesn't apply, but a total the server rejects must never leave
    // Print clickable either.
    const printButton = screen.getByRole("button", { name: "Print 1 label" });
    expect(printButton).toBeDisabled();
  });
});

// Review fix-up: `activeSerialization` used to gate on `sequenceExpand.
// data` (the last CONFIRMED, debounced-by-useSequenceExpand result) while
// sending the LIVE `sequence` -- editing a confirmed-valid run into an
// out-of-bounds one kept sending the now-invalid live sequence to preview/
// estimate for one cycle, because the stale confirmed data hadn't cleared
// yet (captured live via chrome-devtools as real 422s + a raw error flash
// on the deck). Pins the fix: gate and value must both derive from the
// SAME live `sequence` snapshot, so a request already known (client-side)
// to be invalid is never sent, even transiently mid-edit.
describe("Designer + serialization -- no stale/mismatched serialization ever reaches preview or estimate (I2 regression)", () => {
  it("pushing Count out of bounds after a confirmed run never sends that invalid count to /api/render/preview or /api/print/estimate", async () => {
    const user = userEvent.setup();
    const previewSerializations: ({ count?: number } | null)[] = [];
    const estimateSerializations: ({ count?: number } | null)[] = [];
    server.use(
      http.post("/api/render/preview", async ({ request }) => {
        const body = (await request.json()) as { serialization?: { count?: number } };
        previewSerializations.push(body.serialization ?? null);
        return HttpResponse.json({
          png_b64: TINY_PNG_B64,
          png_width_px: 200,
          png_height_px: 96,
          length_mm: 25.4,
          min_feed_mm: 24.5,
          warnings: [],
          total_labels: body.serialization ? (body.serialization.count ?? null) : null,
          sequence_value: body.serialization ? "01" : null,
        });
      }),
      http.post("/api/print/estimate", async ({ request }) => {
        const body = (await request.json()) as { serialization?: { count?: number } };
        estimateSerializations.push(body.serialization ?? null);
        return HttpResponse.json({
          label_count: body.serialization ? (body.serialization.count ?? 1) : 1,
          label_lengths_mm: [25.4],
          content_mm: 25.4,
          feed_overhead_mm: 10,
          total_mm: 35.4,
          per_label_mm: 35.4,
          notes: [],
        });
      }),
    );

    renderWithProviders(<Designer />);
    await typeLineWithToken(user);

    await user.click(await screen.findByRole("checkbox", { name: "On" }));
    const count = await screen.findByLabelText("Count");
    await user.clear(count);
    await user.type(count, "24");

    // Let one confirmed, valid request land first.
    await waitFor(() => expect(previewSerializations.some((s) => s !== null)).toBe(true), { timeout: 3000 });

    // Now push Count out of its own 1-500 bound (a REAL, wire-serializable
    // invalid number -- not an emptied field, which JSON.stringify would
    // just drop and so couldn't distinguish "fixed" from "buggy" here).
    await user.clear(count);
    await user.type(count, "601");

    // Give BOTH usePreview's/usePrintEstimate's own 300ms debounce AND
    // useSequenceExpand's independent 300ms debounce time to fully settle.
    await new Promise((resolve) => setTimeout(resolve, 700));

    for (const serialization of [...previewSerializations, ...estimateSerializations]) {
      if (serialization === null) continue;
      expect(serialization.count).toBeDefined();
      expect(serialization.count as number).toBeGreaterThanOrEqual(1);
      expect(serialization.count as number).toBeLessThanOrEqual(500);
    }
  });
});

describe("Designer + serialization -- preview index stepper", () => {
  it("clamps to range, drives the preview request's index, and shows sequence_value", async () => {
    const user = userEvent.setup();
    const seenIndices: number[] = [];
    server.use(
      http.post("/api/render/preview", async ({ request }) => {
        const body = (await request.json()) as { serialization?: unknown; index?: number };
        const index = body.serialization ? (body.index ?? 0) : 0;
        seenIndices.push(index);
        return HttpResponse.json({
          png_b64: TINY_PNG_B64,
          png_width_px: 200,
          png_height_px: 96,
          length_mm: 25.4,
          min_feed_mm: 24.5,
          warnings: [],
          total_labels: body.serialization ? 3 : null,
          sequence_value: body.serialization ? String(index + 1).padStart(2, "0") : null,
        });
      }),
    );

    renderWithProviders(<Designer />);
    await typeLineWithToken(user);

    await user.click(await screen.findByRole("checkbox", { name: "On" }));
    const count = await screen.findByLabelText("Count");
    await user.clear(count);
    await user.type(count, "3");

    // The stepper appears once the run has resolved (total_labels known,
    // from /api/render/expand); the sequence_value chip lands slightly
    // later, off the SEPARATE (also debounced) /api/render/preview call.
    await waitFor(() => expect(screen.getByText("1 / 3")).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByLabelText("Previous label")).toBeDisabled();
    await waitFor(() => expect(screen.getByText("01")).toBeInTheDocument(), { timeout: 3000 });

    await user.click(screen.getByLabelText("Next label"));
    await waitFor(() => expect(screen.getByText("2 / 3")).toBeInTheDocument(), { timeout: 3000 });
    await waitFor(() => expect(screen.getByText("02")).toBeInTheDocument(), { timeout: 3000 });

    // Clamp at the top end.
    await user.click(screen.getByLabelText("Next label"));
    await waitFor(() => expect(screen.getByText("3 / 3")).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByLabelText("Next label")).toBeDisabled();

    await waitFor(() => expect(seenIndices).toContain(2), { timeout: 3000 });
  });
});
