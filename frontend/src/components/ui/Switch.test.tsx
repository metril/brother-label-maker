import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Switch } from "./Switch";

/** A stateful harness for the interaction tests below -- Switch itself is a
 * controlled component (checked/onChange props), so anything that needs to
 * observe a toggle actually taking effect across a render needs something
 * holding the state between renders, same pattern as schema/SchemaField.
 * test.tsx's own Harness. */
function Harness({ initial = false }: { initial?: boolean }) {
  const [checked, setChecked] = useState(initial);
  return <Switch id="notify-switch" checked={checked} onChange={setChecked} label="Notify" />;
}

describe("Switch", () => {
  it("renders role=switch, reachable by its visible label, with aria-checked reflecting the checked prop", () => {
    const { rerender } = render(<Switch id="s" checked={false} onChange={vi.fn()} label="Notify" />);
    const toggle = screen.getByRole("switch", { name: "Notify" });
    expect(toggle).toHaveAttribute("aria-checked", "false");

    rerender(<Switch id="s" checked={true} onChange={vi.fn()} label="Notify" />);
    expect(screen.getByRole("switch", { name: "Notify" })).toHaveAttribute("aria-checked", "true");
  });

  it("clicking the control calls onChange with the toggled (opposite) value", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Switch id="s" checked={false} onChange={onChange} label="Notify" />);

    await user.click(screen.getByRole("switch", { name: "Notify" }));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("clicking the visible label text toggles it too (label wraps the control, per ui/inputs.tsx's Checkbox precedent)", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByText("Notify"));
    expect(screen.getByRole("switch", { name: "Notify" })).toHaveAttribute("aria-checked", "true");
  });

  it("Space and Enter both toggle it via the keyboard (native button activation, no extra key handling needed)", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const toggle = screen.getByRole("switch", { name: "Notify" });
    toggle.focus();

    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-checked", "true");

    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("disabled ignores clicks and keyboard activation, and is not reachable by Tab", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Switch id="s" checked={false} onChange={onChange} label="Notify" disabled />);

    const toggle = screen.getByRole("switch", { name: "Notify" });
    expect(toggle).toBeDisabled();

    await user.click(toggle);
    expect(onChange).not.toHaveBeenCalled();

    await user.tab();
    expect(document.activeElement).not.toBe(toggle);
  });
});
