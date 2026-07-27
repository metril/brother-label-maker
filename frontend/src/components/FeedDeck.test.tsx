import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FeedDeck } from "./FeedDeck";
import type { RenderWarning, Tape, TapeInfo } from "../api/types";

const TAPE: Tape = { width_mm: 24, family: "tze" };
const TAPE_INFO: TapeInfo = { nominal_mm: 24, family: "tze", print_dots: 128, print_mm: 18.1, max_length_mm: 1000 };
const PNG = "data:image/png;base64,AAAA";

function baseProps() {
  return {
    tape: TAPE,
    tapeInfo: TAPE_INFO,
    hasContent: true,
    png: PNG,
    warnings: [] as RenderWarning[],
    isFetching: false,
    error: null,
  };
}

describe("FeedDeck", () => {
  it("shows the printable-band caption (printable mm of nominal mm) and no feed-waste caption for a label at/above the minimum feed", () => {
    render(<FeedDeck {...baseProps()} lengthMm={40} minFeedMm={24.5} />);

    expect(screen.getByText("18.1 mm printable of 24 mm", { selector: "span" })).toBeInTheDocument();
    expect(screen.queryByText(/feed waste/)).not.toBeInTheDocument();
    expect(screen.getByText("40.0 mm")).toBeInTheDocument();
  });

  it("shows a minimum-feed-waste caption only when length_mm is under the floor, with the correct remaining mm", () => {
    render(<FeedDeck {...baseProps()} lengthMm={10} minFeedMm={24.5} />);
    expect(screen.getByText("+14.5 mm feed waste")).toBeInTheDocument();
  });

  it("renders warning chips distinctly by severity (amber for warning, muted for info)", () => {
    const warnings: RenderWarning[] = [
      { code: "text_cramped", severity: "warning", message: "cramped msg", object_id: null },
      { code: "short_label", severity: "info", message: "info msg", object_id: null },
    ];
    render(<FeedDeck {...baseProps()} lengthMm={40} minFeedMm={24.5} warnings={warnings} />);

    expect(screen.getByText("cramped msg", { selector: "span" }).className).toContain("amber");
    expect(screen.getByText("info msg", { selector: "span" }).className).not.toContain("amber");
  });

  it("a warning chip with an object_id is clickable and calls onFocusObject with that id; one without object_id is not a button", async () => {
    const user = userEvent.setup();
    const onFocusObject = vi.fn();
    const warnings: RenderWarning[] = [
      { code: "text_truncated", severity: "warning", message: "block 2: text truncated", object_id: "block-2" },
      { code: "text_cramped", severity: "warning", message: "no target here", object_id: null },
    ];
    render(<FeedDeck {...baseProps()} lengthMm={40} minFeedMm={24.5} warnings={warnings} onFocusObject={onFocusObject} />);

    await user.click(screen.getByRole("button", { name: "block 2: text truncated" }));
    expect(onFocusObject).toHaveBeenCalledWith("block-2");
    expect(screen.getByText("no target here", { selector: "span" }).tagName).toBe("SPAN");
  });
});
