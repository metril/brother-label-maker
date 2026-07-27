import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { TapeSelector } from "./TapeSelector";
import { renderWithQueryClient } from "../test/utils";
import { server } from "../test/msw/server";

describe("TapeSelector", () => {
  it("renders the six TZe widths for the tze family, filtered out of the full 15-tape catalog", async () => {
    renderWithQueryClient(<TapeSelector tape={{ width_mm: 24, family: "tze" }} onChange={vi.fn()} />);

    await screen.findByRole("button", { name: "24mm" });

    const widthGroup = screen.getByRole("group", { name: "Tape width" });
    const buttons = widthGroup.querySelectorAll("button");
    expect(Array.from(buttons).map((b) => b.textContent)).toEqual([
      "3.5mm",
      "6mm",
      "9mm",
      "12mm",
      "18mm",
      "24mm",
    ]);
    expect(screen.getByRole("button", { name: "24mm" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows a pending indicator while /api/tapes is loading", async () => {
    server.use(
      http.get("/api/tapes", async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return HttpResponse.json([]);
      }),
    );

    renderWithQueryClient(<TapeSelector tape={{ width_mm: 24, family: "tze" }} onChange={vi.fn()} />);

    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
  });

  it("switching family calls onChange with that family's own smallest width", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithQueryClient(<TapeSelector tape={{ width_mm: 24, family: "tze" }} onChange={onChange} />);

    await screen.findByRole("button", { name: "24mm" });
    await user.click(screen.getByRole("radio", { name: "HSe 2:1" }));

    expect(onChange).toHaveBeenCalledWith({ width_mm: 5.8, family: "hse_2_1" });
  });
});
