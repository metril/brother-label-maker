import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Library } from "./Library";
import { renderWithProviders } from "../test/utils";
import symbolsFixture from "../test/fixtures/symbols.json";

// Read off the fixture rather than hardcoded (the fixture grew from 858 to
// 8362 entries between commits e62516b and 566655d) -- this page's own
// count-line assertion just proves the browse grid is mounted at all
// (see the comment below), so the exact number is incidental to what this
// test verifies.
const ALL_COUNT_TEXT = `${symbolsFixture.length} symbols`;

describe("Library page", () => {
  it("renders the Symbols tab by default, with the browse grid from the symbols fixture", async () => {
    renderWithProviders(<Library />, { route: "/library" });

    expect(screen.getByRole("radiogroup", { name: "Library section" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Symbols" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Uploads" })).toHaveAttribute("aria-checked", "false");

    // components/symbols/SymbolBrowser.test.tsx already covers search/
    // category/windowing behavior in depth -- this just proves the browse
    // grid is actually the thing mounted here (test/msw/handlers.ts's
    // default symbolsHandler serves the full symbols fixture).
    expect(await screen.findByText(ALL_COUNT_TEXT)).toBeInTheDocument();
    expect(screen.getByRole("listbox", { name: "Symbol" })).toBeInTheDocument();
  });

  it("switching to the Uploads tab renders UploadsGallery's empty state", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Library />, { route: "/library" });

    await screen.findByText(ALL_COUNT_TEXT);

    await user.click(screen.getByRole("radio", { name: "Uploads" }));

    expect(screen.getByRole("radio", { name: "Uploads" })).toHaveAttribute("aria-checked", "true");
    // Default imagesListHandler returns an empty page -- UploadsGallery's own
    // empty-state copy (components/library/UploadsGallery.test.tsx covers
    // the rest of its behavior).
    expect(await screen.findByText(/No uploads yet/)).toBeInTheDocument();
    expect(screen.queryByRole("listbox", { name: "Symbol" })).not.toBeInTheDocument();
  });

  it("switching back to Symbols keeps the tab state local (no unmount surprises)", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Library />, { route: "/library" });

    await screen.findByText(ALL_COUNT_TEXT);
    await user.click(screen.getByRole("radio", { name: "Uploads" }));
    await screen.findByText(/No uploads yet/);

    await user.click(screen.getByRole("radio", { name: "Symbols" }));

    expect(await screen.findByText(ALL_COUNT_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(/No uploads yet/)).not.toBeInTheDocument();
  });
});
