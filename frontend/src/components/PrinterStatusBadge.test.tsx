import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { PrinterStatusBadge } from "./PrinterStatusBadge";
import { renderWithQueryClient } from "../test/utils";
import { server } from "../test/msw/server";

describe("PrinterStatusBadge", () => {
  it("shows connected + media width/family/lamination, plus a mock tag, when the printer is reachable", async () => {
    renderWithQueryClient(<PrinterStatusBadge />);

    expect(await screen.findByText("connected · 24mm TZe · laminated")).toBeInTheDocument();
    expect(screen.getByText("mock")).toBeInTheDocument();
  });

  it("shows the error string when the printer is disconnected", async () => {
    server.use(
      http.get("/api/printer/status", () =>
        HttpResponse.json({
          connected: false,
          printer_mode: "usb",
          status: null,
          error: "printer not found",
        }),
      ),
    );

    renderWithQueryClient(<PrinterStatusBadge />);

    expect(await screen.findByText("printer not found")).toBeInTheDocument();
  });
});
