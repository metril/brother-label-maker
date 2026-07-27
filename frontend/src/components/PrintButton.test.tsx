import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { PrintButton } from "./PrintButton";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";
import type { LabelDefinition, PrintJob } from "../api/types";

const DEFINITION: LabelDefinition = {
  type: "text",
  tape: { width_mm: 24, family: "tze" },
  params: {
    lines: ["HELLO"],
    font_family: "Inter",
    bold: false,
    font_size_px: null,
    h_align: "center",
    length_mm: null,
    padding_mm: 2,
  },
};

function job(overrides: Partial<PrintJob>): PrintJob {
  return {
    id: "job-1",
    created_at: "2026-07-27T00:00:00.000000Z",
    status: "printing",
    error: null,
    definition: {},
    label_count: 1,
    chain_mode: "cut_each",
    strategy: null,
    tape_width_mm: 24,
    media_raw_byte: null,
    tape_used_mm: null,
    preview_png: null,
    ...overrides,
  };
}

describe("PrintButton", () => {
  it("POSTs a print job whose body contains the current definition", async () => {
    const user = userEvent.setup();
    let capturedBody: unknown;
    server.use(
      http.post("/api/print", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ job_id: "job-1" }, { status: 202 });
      }),
      http.get("/api/print/jobs/:jobId", () => HttpResponse.json(job({ status: "printing" }))),
    );

    renderWithProviders(<PrintButton definition={DEFINITION} />);
    await user.click(screen.getByRole("button", { name: "Print" }));

    await waitFor(() => expect(capturedBody).toBeDefined());
    expect(capturedBody).toEqual({
      labels: [DEFINITION],
      options: { chain_mode: "cut_each", margin_mm: 2, auto_cut: true },
    });
  });

  it("shows the success state once the job is polled as done", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-done" }, { status: 202 })),
      http.get("/api/print/jobs/:jobId", () => HttpResponse.json(job({ id: "job-done", status: "done" }))),
    );

    renderWithProviders(<PrintButton definition={DEFINITION} />);
    await user.click(screen.getByRole("button", { name: "Print" }));

    await waitFor(() => expect(screen.getByRole("button")).toHaveTextContent("Printed"));
  });

  it("shows the job's error text inline when it fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/print", () => HttpResponse.json({ job_id: "job-failed" }, { status: 202 })),
      http.get("/api/print/jobs/:jobId", () =>
        HttpResponse.json(
          job({ id: "job-failed", status: "failed", error: "printer out of tape" }),
        ),
      ),
    );

    renderWithProviders(<PrintButton definition={DEFINITION} />);
    await user.click(screen.getByRole("button", { name: "Print" }));

    expect(await screen.findByText("printer out of tape")).toBeInTheDocument();
  });
});
