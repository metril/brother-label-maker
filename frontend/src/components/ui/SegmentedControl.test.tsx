import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SegmentedControl } from "./SegmentedControl";

const OPTIONS = [
  { value: "a", label: "A" },
  { value: "b", label: "B" },
  { value: "c", label: "C" },
  { value: "d", label: "D" },
] as const;

type OptionValue = (typeof OPTIONS)[number]["value"];

/** A stateful harness -- SegmentedControl is a controlled component
 * (value/onChange props), so observing a keyboard nav actually taking
 * effect across a render needs something holding the state between
 * renders, same pattern as ui/Switch.test.tsx's own Harness. Four options
 * (not two) so a 3+-press arrow-key walk (M9's own repro) has somewhere to
 * go. */
function Harness({ initial = "a" as OptionValue }: { initial?: OptionValue }) {
  const [value, setValue] = useState<OptionValue>(initial);
  return <SegmentedControl ariaLabel="Letters" options={[...OPTIONS]} value={value} onChange={setValue} />;
}

describe("SegmentedControl", () => {
  it("renders a radiogroup with each option as a radio, aria-checked reflecting `value`", () => {
    render(<Harness />);
    expect(screen.getByRole("radiogroup", { name: "Letters" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "A" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "B" })).toHaveAttribute("aria-checked", "false");
  });

  it("clicking an option selects it", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("radio", { name: "C" }));
    expect(screen.getByRole("radio", { name: "C" })).toHaveAttribute("aria-checked", "true");
  });

  it("ArrowRight moves BOTH the selection and DOM focus forward, across 3+ presses -- roving tabindex means focus must follow selection or later presses go stale (M9)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    screen.getByRole("radio", { name: "A" }).focus();

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "B" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "B" })).toHaveFocus();

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "C" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "C" })).toHaveFocus();

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "D" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "D" })).toHaveFocus();
  });

  it("ArrowLeft wraps from the first option to the last, moving focus with it (unchanged wrap semantics)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    screen.getByRole("radio", { name: "A" }).focus();

    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("radio", { name: "D" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "D" })).toHaveFocus();
  });

  it("ArrowDown/ArrowUp behave the same as ArrowRight/ArrowLeft, per the ARIA radiogroup pattern", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    screen.getByRole("radio", { name: "A" }).focus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("radio", { name: "B" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "B" })).toHaveFocus();

    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("radio", { name: "A" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "A" })).toHaveFocus();
  });

  it("End jumps to the last option and Home jumps back to the first, both moving focus there", async () => {
    const user = userEvent.setup();
    render(<Harness initial="b" />);
    screen.getByRole("radio", { name: "B" }).focus();

    await user.keyboard("{End}");
    expect(screen.getByRole("radio", { name: "D" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "D" })).toHaveFocus();

    await user.keyboard("{Home}");
    expect(screen.getByRole("radio", { name: "A" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "A" })).toHaveFocus();
  });
});
