import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockIntersectionObserverInstances } from "../../test/setup";
import { renderWithQueryClient } from "../../test/utils";
import symbolsFixture from "../../test/fixtures/symbols.json";
import { SymbolBrowser } from "./SymbolBrowser";

describe("SymbolBrowser: browse mode", () => {
  it("renders the full catalog with a search box and category tabs, no selection chip", async () => {
    renderWithQueryClient(<SymbolBrowser mode="browse" />);

    expect(await screen.findByText("858 symbols")).toBeInTheDocument();
    expect(screen.getByLabelText("Search symbols")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "All" })).toBeInTheDocument();
    // "safety" has no entries in the fixture -- no empty tab (same rule
    // IconField.test.tsx's category-tabs test covers for select mode).
    expect(screen.queryByRole("radio", { name: "Safety" })).not.toBeInTheDocument();
    expect(screen.queryByText("Clear")).not.toBeInTheDocument();
  });

  it("search filters the grid and the count line updates", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText("858 symbols");

    await user.type(screen.getByLabelText("Search symbols"), "off");
    expect(screen.getByText("43 symbols")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Alarm Off" })).toBeInTheDocument();
  });

  it("category tabs filter the grid and compose with an active search", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText("858 symbols");

    await user.click(screen.getByRole("radio", { name: "Electrical" }));
    expect(screen.getByText("53 symbols")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Bolt" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Assignment Globe" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "All" }));
    await user.type(screen.getByLabelText("Search symbols"), "off");
    await user.click(screen.getByRole("radio", { name: "Network" }));
    expect(screen.getByText("7 symbols")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Wifi Off" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Alarm Off" })).not.toBeInTheDocument();
  });

  it("windowing: renders an initial slice of 96 and grows it when the IntersectionObserver sentinel fires", async () => {
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText("858 symbols");

    expect(screen.getAllByRole("option")).toHaveLength(96);

    const observer = mockIntersectionObserverInstances.at(-1)!;
    observer.trigger();

    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(192));
  });

  it("keyboard nav past the rendered window's edge grows the window and lands focus on the right option", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SymbolBrowser mode="browse" />);
    await screen.findByText("858 symbols");

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

    await user.type(await screen.findByLabelText("Search symbols"), "bolt");
    const bolt = await screen.findByRole("option", { name: "Bolt" });
    await user.click(bolt);

    expect(onSelectSpy).toHaveBeenCalledWith("bolt");
    expect(screen.getByText("Bolt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Bolt details" })).not.toBeInTheDocument();
  });

  it("the selected chip's Clear button deselects via onClear", async () => {
    const user = userEvent.setup();
    const onClearSpy = vi.fn();
    renderWithQueryClient(<Harness onClearSpy={onClearSpy} />);

    await user.type(await screen.findByLabelText("Search symbols"), "bolt");
    await user.click(await screen.findByRole("option", { name: "Bolt" }));
    await user.click(screen.getByRole("button", { name: "Clear" }));

    expect(onClearSpy).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
  });
});
