import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import App from "./App";

describe("App", () => {
  it("renders the shell and the designer page without crashing", async () => {
    render(<App />);

    expect(screen.getByText("Label Studio")).toBeInTheDocument();
    expect(screen.getByText("Designer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print" })).toBeInTheDocument();

    // Initial queries (msw-mocked) resolve without throwing -- scoped to
    // the printer status badge specifically, since "24mm" could otherwise
    // also match a TapeSelector button in the designer form.
    const statusBadge = screen.getByRole("status", { name: "Printer status" });
    expect(await within(statusBadge).findByText("24mm")).toBeInTheDocument();
  });
});
