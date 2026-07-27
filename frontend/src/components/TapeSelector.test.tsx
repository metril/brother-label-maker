import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { TapeSelector } from "./TapeSelector";
import { renderWithQueryClient } from "../test/utils";
import { server } from "../test/msw/server";

describe("TapeSelector", () => {
  it("renders exactly the six TZe widths from GET /api/tapes, filtered out of the full 15-tape catalog", async () => {
    renderWithQueryClient(<TapeSelector valueMm={24} onChange={vi.fn()} />);

    // Wait for the LOADED state specifically -- the loading skeleton is
    // also a <button role="button">, so a bare findAllByRole("button")
    // would resolve on the first render (the skeleton) instead of waiting.
    await screen.findByRole("button", { name: "24mm" });

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["3.5mm", "6mm", "9mm", "12mm", "18mm", "24mm"]);
    expect(screen.getByRole("button", { name: "24mm" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows a disabled skeleton selector while /api/tapes is loading", async () => {
    server.use(
      http.get("/api/tapes", async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return HttpResponse.json([]);
      }),
    );

    renderWithQueryClient(<TapeSelector valueMm={24} onChange={vi.fn()} />);

    const loadingButton = screen.getByRole("button", { name: /loading tape widths/i });
    expect(loadingButton).toBeDisabled();
  });
});
