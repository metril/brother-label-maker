import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { ChainedPreviewDialog } from "./ChainedPreviewDialog";
import { useTrayStore } from "../stores/tray";
import { TINY_PNG_B64 } from "../test/msw/handlers";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import type { ChainMode, LabelDefinition, PrintOptions } from "../api/types";

const LABELS: LabelDefinition[] = [
  { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: ["A"] } },
];
const OPTIONS: PrintOptions = { chain_mode: "cut_each", margin_mm: 2.0, auto_cut: true };

/** ChainedPreviewDialog is a fully controlled component (open/onClose/
 * closeButtonRef all owned by its caller, TrayPanel in the real app) -- a
 * tiny harness stands in for TrayPanel here so these tests can drive
 * open/close without pulling in the whole tray. */
function Harness({ initialChainMode = "cut_each" as ChainMode }: { initialChainMode?: ChainMode }) {
  const [open, setOpen] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <ChainedPreviewDialog
        open={open}
        onClose={() => setOpen(false)}
        closeButtonRef={closeButtonRef}
        labels={LABELS}
        options={OPTIONS}
        serialization={null}
        isRenderable={(labels) => labels.length > 0}
        initialChainMode={initialChainMode}
      />
    </>
  );
}

describe("ChainedPreviewDialog", () => {
  it("opens with the composite PNG, the correct segment count, and the stats row", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const dialog = await screen.findByRole("dialog", { name: "Chain preview" });

    const img = await within(dialog).findByAltText("Chained job preview");
    expect(img).toHaveAttribute("src", `data:image/png;base64,${TINY_PNG_B64}`);

    // The default printPreviewHandler returns exactly 2 segments.
    expect(within(dialog).getByTestId("segment-chip-0")).toHaveTextContent("1");
    expect(within(dialog).getByTestId("segment-chip-1")).toHaveTextContent("2");
    expect(within(dialog).queryByTestId("segment-chip-2")).not.toBeInTheDocument();

    expect(within(dialog).getByTestId("preview-total-mm")).toHaveTextContent("60.0 mm");
    expect(within(dialog).getByText(/UNVERIFIED estimate/)).toBeInTheDocument();
  });

  it("switching the mode tab refetches with the new chain_mode and does NOT touch the tray store's chainMode", async () => {
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
    await screen.findByRole("dialog", { name: "Chain preview" });

    await waitFor(() => expect(capturedModes).toEqual(["cut_each"]));

    await user.click(screen.getByRole("radio", { name: "Chain" }));

    await waitFor(() => expect(capturedModes).toEqual(["cut_each", "chain_ff"]));
    expect(useTrayStore.getState().chainMode).toBe(storeBefore);
  });

  it("changing zoom changes the strip's on-screen width", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open" }));
    const dialog = await screen.findByRole("dialog", { name: "Chain preview" });
    const img = await within(dialog).findByAltText("Chained job preview");

    await waitFor(() => expect(img.style.width).not.toBe(""));
    const widthAt4x = img.style.width;

    await user.click(within(dialog).getByRole("radio", { name: "8×" }));
    expect(img.style.width).not.toBe(widthAt4x);
  });
});
