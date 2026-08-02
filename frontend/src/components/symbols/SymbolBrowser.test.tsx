import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockIntersectionObserverInstances } from "../../test/setup";
import { renderWithQueryClient } from "../../test/utils";
import symbolsFixture from "../../test/fixtures/symbols.json";
import { SymbolBrowser } from "./SymbolBrowser";

/** Mirrors SymbolBrowser's own category+search predicate (see that
 * component's `filtered` computation) so count-line and presence/absence
 * assertions below stay correct however big/composed the fixture is --
 * the fixture grew from 858 to 8362 entries (5 new icon sources) between
 * commits e62516b and 566655d, and hardcoded counts/identifiers went
 * stale along with it. */
function filterFixture(category: string, query: string) {
  const q = query.trim().toLowerCase();
  return symbolsFixture.filter((s) => {
    if (category !== "all" && s.category !== category) return false;
    if (!q) return true;
    return s.id.includes(q) || s.name.toLowerCase().includes(q) || s.tags.some((t) => t.includes(q));
  });
}

const ALL_COUNT_TEXT = `${symbolsFixture.length} symbols`;

describe("SymbolBrowser: browse mode", () => {
  it("renders the full catalog with a search box and category tabs, no selection chip", async () => {
    renderWithQueryClient(<SymbolBrowser mode="browse" />);

    expect(await screen.findByText(ALL_COUNT_TEXT)).toBeInTheDocument();
    expect(screen.getByLabelText("Search symbols")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "All" })).toBeInTheDocument();
    // "safety" used to have no entries in the (858-entry) fixture, so its
    // tab didn't show up (the "no empty tabs" rule) -- the regenerated
    // fixture's new sources (lucide_/tabler_/remix_/bootstrap_/fluent_)
    // carry safety-category icons, so it's populated like every other
    // category now.
    expect(screen.getByRole("radio", { name: "Safety" })).toBeInTheDocument();
    expect(screen.queryByText("Clear")).not.toBeInTheDocument();
  });

  it("search filters the grid and the count line updates", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    await user.type(screen.getByLabelText("Search symbols"), "off");
    const offMatches = filterFixture("all", "off");
    expect(screen.getByText(`${offMatches.length} symbols`)).toBeInTheDocument();
    // "Camera Video Off" (bootstrap_camera_video_off) -- unlike "Alarm Off"
    // pre-regeneration, its name is unique across the whole catalog (several
    // new sources duplicate names like "Wifi Off"/"Bolt" across id
    // prefixes) and it sorts early enough by id to land inside the initial
    // 96-item window.
    expect(await screen.findByRole("option", { name: "Camera Video Off" })).toBeInTheDocument();
  });

  it("category tabs filter the grid and compose with an active search", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    await user.click(screen.getByRole("radio", { name: "Electrical" }));
    const electrical = filterFixture("electrical", "");
    expect(screen.getByText(`${electrical.length} symbols`)).toBeInTheDocument();
    // "Electrical Services" is a uniquely-named electrical icon within the
    // initial window -- "Bolt" (the pre-regeneration example) now names
    // three separate icons (material/lucide/tabler sources), so it's no
    // longer safe to query by that name alone.
    expect(await screen.findByRole("option", { name: "Electrical Services" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Assignment Globe" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "All" }));
    await user.type(screen.getByLabelText("Search symbols"), "off");
    await user.click(screen.getByRole("radio", { name: "Network" }));
    const networkOff = filterFixture("network", "off");
    expect(screen.getByText(`${networkOff.length} symbols`)).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Cellular Off" })).toBeInTheDocument();
    // "Camera Video Off" matched the search term but isn't Network-category.
    expect(screen.queryByRole("option", { name: "Camera Video Off" })).not.toBeInTheDocument();
  });

  it("windowing: renders an initial slice of 96 and grows it when the IntersectionObserver sentinel fires", async () => {
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    expect(screen.getAllByRole("option")).toHaveLength(96);

    const observer = mockIntersectionObserverInstances.at(-1)!;
    observer.trigger();

    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(192));
  });

  it("keyboard nav past the rendered window's edge grows the window and lands focus on the right option", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText(ALL_COUNT_TEXT);

    // symbols.json is sorted by id; entries 95/96 (0-indexed) straddle the
    // initial 96-item window boundary.
    const lastVisible = symbolsFixture[95]!;
    const firstBeyondWindow = symbolsFixture[96]!;

    screen.getByRole("option", { name: lastVisible.name }).focus();
    await user.keyboard("{ArrowRight}");

    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole("option", { name: firstBeyondWindow.name }));
    });
    expect(screen.getAllByRole("option").length).toBeGreaterThan(96);
  });

  it("clicking an icon opens a detail panel with its name/id/category/tags/source/license, and clicking it again closes it", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    // symbolsFixture[0] ("add") is well inside the initial window and has a
    // known category/tags/source/license to assert against.
    const first = symbolsFixture[0]!;
    const option = await screen.findByRole("option", { name: first.name });

    await user.click(option);

    const panel = screen.getByRole("group", { name: `${first.name} details` });
    expect(within(panel).getByText(first.id)).toBeInTheDocument();
    expect(within(panel).getByText("Misc")).toBeInTheDocument();
    expect(within(panel).getByText(first.tags.join(", "))).toBeInTheDocument();
    expect(within(panel).getByText(`${first.source} · ${first.license}`)).toBeInTheDocument();
    expect(option).toHaveAttribute("aria-selected", "true");

    await user.click(option);
    expect(screen.queryByRole("group", { name: `${first.name} details` })).not.toBeInTheDocument();
    expect(option).toHaveAttribute("aria-selected", "false");
  });

  it("the detail panel's own Close button closes it, and opening a different icon swaps the panel", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    const first = symbolsFixture[0]!;
    const second = symbolsFixture[1]!;

    await user.click(await screen.findByRole("option", { name: first.name }));
    expect(screen.getByRole("group", { name: `${first.name} details` })).toBeInTheDocument();

    await user.click(await screen.findByRole("option", { name: second.name }));
    expect(screen.queryByRole("group", { name: `${first.name} details` })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: `${second.name} details` })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("group", { name: `${second.name} details` })).not.toBeInTheDocument();
  });
});

describe("SymbolBrowser: select mode", () => {
  function Harness({ onSelectSpy, onClearSpy }: { onSelectSpy?: (id: string) => void; onClearSpy?: () => void }) {
    const [selectedId, setSelectedId] = useState<string | null>(null);
    return (
      <SymbolBrowser
        mode="select"
        selectedId={selectedId}
        onSelect={(id) => {
          onSelectSpy?.(id);
          setSelectedId(id);
        }}
        onClear={() => {
          onClearSpy?.();
          setSelectedId(null);
        }}
      />
    );
  }

  it("clicking an option reports it via onSelect and shows the selected chip (no detail panel)", async () => {
    const user = userEvent.setup();
    const onSelectSpy = vi.fn();
    renderWithQueryClient(<Harness onSelectSpy={onSelectSpy} />);

    // "electrical services" (unlike "bolt", pre-regeneration) matches
    // exactly one icon in the 8362-entry fixture -- several new sources
    // add their own "Bolt"-named icons, which would make a single-result
    // query ambiguous.
    await user.type(await screen.findByLabelText("Search symbols"), "electrical services");
    const match = await screen.findByRole("option", { name: "Electrical Services" });
    await user.click(match);

    expect(onSelectSpy).toHaveBeenCalledWith("electrical_services");
    expect(screen.getByText("Electrical Services")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Electrical Services details" })).not.toBeInTheDocument();
  });

  it("the selected chip's Clear button deselects via onClear", async () => {
    const user = userEvent.setup();
    const onClearSpy = vi.fn();
    renderWithQueryClient(<Harness onClearSpy={onClearSpy} />);

    await user.type(await screen.findByLabelText("Search symbols"), "electrical services");
    await user.click(await screen.findByRole("option", { name: "Electrical Services" }));
    await user.click(screen.getByRole("button", { name: "Clear" }));

    expect(onClearSpy).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
  });
});
