import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import App from "./App";

describe("App", () => {
  it("renders the shell and the designer page without crashing", async () => {
    render(<App />);

    expect(screen.getByText("Label Studio")).toBeInTheDocument();

    // Initial queries (msw-mocked, real fixtured label-types schema) resolve
    // without throwing -- the Designer panel's own heading names the active
    // type ("Text", the first type registered by the backend).
    expect(await screen.findByRole("heading", { name: "Text" })).toBeInTheDocument();
    // task 2.12: an empty tray's Print button reads "Print 1 label" (an
    // explicit count, unambiguous against the tray's own "N labels (tray)"
    // wording) rather than a bare "Print".
    expect(screen.getByRole("button", { name: "Print 1 label" })).toBeInTheDocument();

    // Scoped to the printer status badge specifically, since "24mm" could
    // otherwise also match a TapeSelector button in the designer form.
    const statusBadge = screen.getByRole("status", { name: "Printer status" });
    expect(await within(statusBadge).findByText("connected · 24mm TZe · laminated")).toBeInTheDocument();
  });
});
