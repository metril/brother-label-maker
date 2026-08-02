import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Icon } from "../../api/types";
import { mockIntersectionObserverInstances } from "../../test/setup";
import { renderWithQueryClient } from "../../test/utils";
import { trimmedSymbolsFixture } from "../../test/msw/handlers";
import { IconField } from "./IconField";
import type { OverrideFieldProps } from "./types";

/** Mirrors SymbolBrowser's own category+search predicate (see that
 * component's `filtered` computation, and symbols/SymbolBrowser.test.tsx's
 * identical helper) so count-line and presence/absence assertions below
 * stay correct however big/composed the fixture is. Runs against
 * `trimmedSymbolsFixture` (H9, docs/code-review-2026-08.md) -- the same
 * slice test/msw/handlers.ts's default symbolsHandler actually serves --
 * not the raw 8362-entry fixture. */
function filterFixture(category: string, query: string) {
  const q = query.trim().toLowerCase();
  return trimmedSymbolsFixture.filter((s) => {
    if (category !== "all" && s.category !== category) return false;
    if (!q) return true;
    return s.id.includes(q) || s.name.toLowerCase().includes(q) || s.tags.some((t) => t.includes(q));
  });
}

/** Mirrors the count line's own singular/plural rendering (`{n} symbol{n
 * === 1 ? "" : "s"}`) -- the trimmed slice's per-bucket cap means a
 * category+search combination can genuinely narrow to exactly one match,
 * so a hardcoded " symbols" would go stale the moment that happens (see
 * the Network+"off" case below). */
function countText(n: number) {
  return `${n} symbol${n === 1 ? "" : "s"}`;
}

const ALL_COUNT_TEXT = countText(trimmedSymbolsFixture.length);

function Harness({ initial, onChangeSpy }: { initial: Icon | null; onChangeSpy?: (v: unknown) => void }) {
  const [value, setValue] = useState<Icon | null>(initial);
  const props: OverrideFieldProps = {
    fieldKey: "icon",
    schema: {},
    root: {},
    value,
    onChange: (v) => {
      onChangeSpy?.(v);
      setValue(v as Icon | null);
    },
    path: ["icon"],
    allParams: {},
    labelType: "text",
  };
  return <IconField {...props} />;
}

describe("IconField", () => {
  it("symbol picker: switching to Symbol and clicking a result inserts it as the icon value", async () => {
    const user = userEvent.setup();
    const onChangeSpy = vi.fn();
    renderWithQueryClient(<Harness initial={null} onChangeSpy={onChangeSpy} />);

    await user.click(screen.getByRole("radio", { name: "Symbol" }));
    // "electrical services" (unlike "bolt", pre-regeneration) matches
    // exactly one icon in the trimmed slice -- several new sources add
    // their own "Bolt"-named icons, which would make a single-result query
    // ambiguous.
    await user.type(screen.getByLabelText("Search symbols"), "electrical services");

    const match = await screen.findByRole("option", { name: "Electrical Services" });
    await user.click(match);

    expect(onChangeSpy).toHaveBeenCalledWith({ kind: "symbol", id: "electrical_services" });
  });

  it("image upload: selecting a file POSTs to /api/images and shows a thumbnail from the returned image_id", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<Harness initial={null} />);

    await user.click(screen.getByRole("radio", { name: "Image" }));
    const file = new File(["fake-bytes"], "logo.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Upload image"), file);

    const thumb = await screen.findByAltText("Uploaded icon");
    expect(thumb).toHaveAttribute("src", expect.stringContaining("/api/images/img-1"));
  });

  it("clear removes the image icon back to null", async () => {
    const user = userEvent.setup();
    const onChangeSpy = vi.fn();
    renderWithQueryClient(
      <Harness initial={{ kind: "image", image_id: "img-1", mode: "threshold", threshold: 128 }} onChangeSpy={onChangeSpy} />,
    );

    expect(screen.getByAltText("Uploaded icon")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear image" }));

    expect(onChangeSpy).toHaveBeenCalledWith(null);
    expect(screen.queryByAltText("Uploaded icon")).not.toBeInTheDocument();
  });

  it("category tabs filter the grid and the count line reflects the active category (fixture spans all eight icon sources)", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<Harness initial={null} />);
    await user.click(screen.getByRole("radio", { name: "Symbol" }));

    // Unfiltered: the full fixture catalog. "Safety" used to have no
    // entries in the (858-entry) fixture, so its tab didn't show up (the
    // "no empty tabs" rule) -- the regenerated fixture's new sources
    // (lucide_/tabler_/remix_/bootstrap_/fluent_) carry safety-category
    // icons, so it's populated like every other category now.
    expect(screen.getByText(ALL_COUNT_TEXT)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Safety" })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Electrical" }));
    const electrical = filterFixture("electrical", "");
    expect(screen.getByText(countText(electrical.length))).toBeInTheDocument();
    // "Electrical Services" is a uniquely-named electrical icon within the
    // initial window -- "Bolt" (the pre-regeneration example) now names
    // three separate icons (material/lucide/tabler sources), so it's no
    // longer safe to query by that name alone.
    expect(await screen.findByRole("option", { name: "Electrical Services" })).toBeInTheDocument();
    // "AC Unit" is a uniquely-named general-category icon in the trimmed
    // slice -- absent once filtered to Electrical, proving the tab
    // actually filters rather than just relabeling.
    expect(screen.queryByRole("option", { name: "AC Unit" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "All" }));
    expect(screen.getByText(ALL_COUNT_TEXT)).toBeInTheDocument();
  });

  it("search composes with the active category filter, and the count line updates with both", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<Harness initial={null} />);
    await user.click(screen.getByRole("radio", { name: "Symbol" }));

    await user.type(screen.getByLabelText("Search symbols"), "off");
    const offMatches = filterFixture("all", "off");
    expect(screen.getByText(countText(offMatches.length))).toBeInTheDocument();
    // "Camera Video Off" (bootstrap_camera_video_off) -- its name is unique
    // across the trimmed slice and it sorts early enough by id to land
    // inside the initial 96-item window.
    expect(await screen.findByRole("option", { name: "Camera Video Off" })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Network" }));
    const networkOff = filterFixture("network", "off");
    expect(screen.getByText(countText(networkOff.length))).toBeInTheDocument();
    // "Bluetooth Off" (lucide_bluetooth_off) -- the trimmed slice's
    // per-bucket cap only keeps one network+"off" match, so this narrows to
    // exactly 1 (see `countText`'s own comment on why the count-line
    // assertion above can't hardcode "symbols").
    expect(await screen.findByRole("option", { name: "Bluetooth Off" })).toBeInTheDocument();
    // "Camera Video Off" matched the search term but isn't Network-category
    // -- composing the two filters, not just applying one or the other.
    expect(screen.queryByRole("option", { name: "Camera Video Off" })).not.toBeInTheDocument();
  });

  it("windowing: renders an initial slice of 96 and grows it when the IntersectionObserver sentinel fires", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<Harness initial={null} />);
    await user.click(screen.getByRole("radio", { name: "Symbol" }));

    expect(screen.getAllByRole("option")).toHaveLength(96);

    const observer = mockIntersectionObserverInstances.at(-1)!;
    observer.trigger();

    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(192));
  });

  it("keyboard nav past the rendered window's edge grows the window and lands focus on the right option", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<Harness initial={null} />);
    await user.click(screen.getByRole("radio", { name: "Symbol" }));

    // trimmedSymbolsFixture is a content-relative subset of symbols.json,
    // which is sorted by id -- filtering a sorted array preserves relative
    // order, so the trimmed slice is sorted by id too, and entries 95/96
    // (0-indexed) straddle the initial 96-item window boundary the same
    // way they would against the raw fixture.
    const lastVisible = trimmedSymbolsFixture[95]!;
    const firstBeyondWindow = trimmedSymbolsFixture[96]!;
    expect(screen.getAllByRole("option")).toHaveLength(96);

    const lastVisibleOption = screen.getByRole("option", { name: lastVisible.name });
    lastVisibleOption.focus();
    await user.keyboard("{ArrowRight}");

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole("option", { name: firstBeyondWindow.name }));
    });
    expect(screen.getAllByRole("option").length).toBeGreaterThan(96);
  });

  it("the selected chip stays visible when the current selection is excluded by the active filter, and its Clear button deselects", async () => {
    const user = userEvent.setup();
    const onChangeSpy = vi.fn();
    renderWithQueryClient(<Harness initial={{ kind: "symbol", id: "bolt" }} onChangeSpy={onChangeSpy} />);

    // "bolt" is electrical -- a search that only matches network entries
    // would otherwise filter it out of the grid entirely. The harness
    // starts already in "symbol" mode (a non-null symbol Icon), so there's
    // no radio click to await the data fetch behind first -- wait for the
    // search box itself instead.
    const searchInput = await screen.findByLabelText("Search symbols");
    await user.type(searchInput, "wifi");
    expect(screen.queryByRole("option", { name: "Bolt" })).not.toBeInTheDocument();
    expect(screen.getByText("Bolt")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(onChangeSpy).toHaveBeenCalledWith(null);
  });
});
