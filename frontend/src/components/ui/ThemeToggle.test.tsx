import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  it("exposes a radiogroup with Dark/Light/System, Dark selected by default (no stored preference)", () => {
    render(<ThemeToggle />);
    const group = screen.getByRole("radiogroup", { name: "Theme" });

    expect(within(group).getByRole("radio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");
    expect(within(group).getByRole("radio", { name: "Light" })).toHaveAttribute("aria-checked", "false");
    expect(within(group).getByRole("radio", { name: "System" })).toHaveAttribute("aria-checked", "false");
  });

  it("selecting Light persists lm-theme and sets <html data-theme=\"light\">", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("radio", { name: "Light" }));

    expect(localStorage.getItem("lm-theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(screen.getByRole("radio", { name: "Light" })).toHaveAttribute("aria-checked", "true");
  });

  it("selecting System persists lm-theme and REMOVES the data-theme attribute (the CSS media query governs instead)", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("radio", { name: "System" }));

    expect(localStorage.getItem("lm-theme")).toBe("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(screen.getByRole("radio", { name: "System" })).toHaveAttribute("aria-checked", "true");
  });

  it("two mounted instances (e.g. AppShell's header control + Settings' own copy) stay in sync", async () => {
    const user = userEvent.setup();
    render(
      <>
        <ThemeToggle />
        <ThemeToggle />
      </>,
    );
    const [firstGroup, secondGroup] = screen.getAllByRole("radiogroup", { name: "Theme" });

    await user.click(within(firstGroup!).getByRole("radio", { name: "Light" }));

    expect(within(secondGroup!).getByRole("radio", { name: "Light" })).toHaveAttribute("aria-checked", "true");
  });

  it("arrow keys move between options (SegmentedControl's own roving radiogroup behavior)", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);

    const darkOption = screen.getByRole("radio", { name: "Dark" });
    darkOption.focus();
    await user.keyboard("{ArrowRight}");

    expect(screen.getByRole("radio", { name: "Light" })).toHaveAttribute("aria-checked", "true");
  });
});
