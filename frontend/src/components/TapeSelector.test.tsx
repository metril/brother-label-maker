import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TapeSelector } from "./TapeSelector";

describe("TapeSelector", () => {
  it("renders exactly the six TZe widths from the backend geometry table", () => {
    render(<TapeSelector valueMm={24} onChange={vi.fn()} />);

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["3.5mm", "6mm", "9mm", "12mm", "18mm", "24mm"]);
    expect(screen.getByRole("button", { name: "24mm" })).toHaveAttribute("aria-pressed", "true");
  });
});
