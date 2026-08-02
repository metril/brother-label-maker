import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Icon } from "../../api/types";
import { mockIntersectionObserverInstances } from "../../test/setup";
import { renderWithQueryClient } from "../../test/utils";
import symbolsFixture from "../../test/fixtures/symbols.json";
import { IconField } from "./IconField";
import type { OverrideFieldProps } from "./types";

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
    await user.type(screen.getByLabelText("Search symbols"), "bolt");

    const bolt = await screen.findByRole("option", { name: "Bolt" });
    await user.click(bolt);

    expect(onChangeSpy).toHaveBeenCalledWith({ kind: "symbol", id: "bolt" });
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

  it("category tabs filter the grid and the count line reflects the active category (fixture spans all three sources)", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<Harness initial={null} />);
    await user.click(screen.getByRole("radio", { name: "Symbol" }));

    // Unfiltered: the full 858-entry catalog (task's "no empty tabs" rule
    // -- "Safety" never shows up since the fixture has no entries in it).
    expect(screen.getByText("858 symbols")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Safety" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Electrical" }));
    expect(screen.getByText("53 symbols")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Bolt" })).toBeInTheDocument();
    // "Assignment Globe" is a general-category (material_*) entry -- absent
    // once filtered to Electrical, proving the tab actually filters rather
    // than just relabeling.
    expect(screen.queryByRole("option", { name: "Assignment Globe" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "All" }));
    expect(screen.getByText("858 symbols")).toBeInTheDocument();
  });

  it("search composes with the active category filter, and the count line updates with both", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<Harness initial={null} />);
    await user.click(screen.getByRole("radio", { name: "Symbol" }));

    await user.type(screen.getByLabelText("Search symbols"), "off");
    expect(screen.getByText("43 symbols")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Alarm Off" })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Network" }));
    expect(screen.getByText("7 symbols")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Wifi Off" })).toBeInTheDocument();
    // "Alarm Off" matched the search term but isn't Network-category --
    // composing the two filters, not just applying one or the other.
    expect(screen.queryByRole("option", { name: "Alarm Off" })).not.toBeInTheDocument();
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

    // symbols.json is sorted by id; entries 95/96 (0-indexed) straddle the
    // initial 96-item window boundary.
    const lastVisible = symbolsFixture[95]!;
    const firstBeyondWindow = symbolsFixture[96]!;
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
