import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";

describe("App", () => {
  it("renders the shell and the designer page without crashing", async () => {
    render(<App />);

    expect(screen.getByText("Label Studio")).toBeInTheDocument();
    expect(screen.getByText("Designer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print" })).toBeInTheDocument();

    // Initial queries (msw-mocked) resolve without throwing.
    expect(await screen.findByText("24mm")).toBeInTheDocument();
  });
});
