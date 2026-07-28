import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PrintButton } from "./PrintButton";
import type { UsePrintJobResult } from "../hooks/usePrintJob";
import type { LabelDefinition, PrintOptions } from "../api/types";

const OPTIONS: PrintOptions = { chain_mode: "cut_each", margin_mm: 2, auto_cut: true };

function def(text: string): LabelDefinition {
  return { type: "text", tape: { width_mm: 24, family: "tze" }, params: { lines: [text] } };
}

function fakeJob(overrides: Partial<UsePrintJobResult> = {}): UsePrintJobResult {
  return {
    phase: "idle",
    jobId: null,
    progress: null,
    errorText: null,
    submittedCount: null,
    canCancel: false,
    isCanceling: false,
    cancelError: null,
    isSubmitting: false,
    submit: vi.fn(),
    cancel: vi.fn(),
    ...overrides,
  };
}

describe("PrintButton -- label semantics (task 2.12)", () => {
  it('shows "Print 1 label" for the plain empty-tray, non-serialized path', () => {
    render(<PrintButton job={fakeJob()} labels={[def("A")]} options={OPTIONS} />);
    expect(screen.getByRole("button", { name: "Print 1 label" })).toBeInTheDocument();
  });

  it('shows "Print N labels (tray)" once labels come from a non-empty tray', () => {
    render(<PrintButton job={fakeJob()} labels={[def("A"), def("B"), def("C")]} options={OPTIONS} isTray />);
    expect(screen.getByRole("button", { name: "Print 3 labels (tray)" })).toBeInTheDocument();
  });

  it('shows "Print N labels" (no "(tray)" suffix) for a confirmed serialized run', () => {
    render(
      <PrintButton
        job={fakeJob()}
        labels={[def("PORT-{seq}")]}
        options={OPTIONS}
        serialization={{ kind: "numeric", count: 24 }}
        totalLabels={24}
      />,
    );
    expect(screen.getByRole("button", { name: "Print 24 labels" })).toBeInTheDocument();
  });
});

describe("PrintButton -- submit wiring", () => {
  it("clicking Print calls job.submit with the exact labels/options/serialization body AND the live printed count", async () => {
    const user = userEvent.setup();
    const job = fakeJob();
    render(<PrintButton job={job} labels={[def("A")]} options={OPTIONS} />);

    await user.click(screen.getByRole("button", { name: "Print 1 label" }));

    expect(job.submit).toHaveBeenCalledWith(
      { labels: [def("A")], options: OPTIONS, serialization: undefined },
      1,
    );
  });

  it("a blockedMessage disables Print, shows the message, and never calls submit (task 2.12 carry-forward: serialization + non-empty tray)", async () => {
    const user = userEvent.setup();
    const job = fakeJob();
    render(
      <PrintButton
        job={job}
        labels={[def("A")]}
        options={OPTIONS}
        isTray
        blockedMessage="Turn off Serialize or clear the tray to print."
      />,
    );

    const button = screen.getByRole("button", { name: "Print 1 label (tray)" });
    expect(button).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Turn off Serialize or clear the tray to print.");

    await user.click(button);
    expect(job.submit).not.toHaveBeenCalled();
  });
});

describe("PrintButton -- progress, cancel, done, failed", () => {
  it("shows a Cancel button while queued/printing, enabled only when job.canCancel", () => {
    const { rerender } = render(
      <PrintButton job={fakeJob({ phase: "queued", canCancel: true })} labels={[def("A")]} options={OPTIONS} />,
    );
    expect(screen.getByRole("button", { name: "Cancel" })).not.toBeDisabled();

    rerender(<PrintButton job={fakeJob({ phase: "printing", canCancel: false })} labels={[def("A")]} options={OPTIONS} />);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    rerender(<PrintButton job={fakeJob({ phase: "idle" })} labels={[def("A")]} options={OPTIONS} />);
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("renders a progress bar reflecting job.progress's sent/total", () => {
    render(
      <PrintButton
        job={fakeJob({ phase: "printing", progress: { sent: 50, total: 200 } })}
        labels={[def("A")]}
        options={OPTIONS}
      />,
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  });

  it('on done, shows a success line and relabels the button "Print again"', () => {
    render(
      <PrintButton
        job={fakeJob({ phase: "done", submittedCount: 2 })}
        labels={[def("A"), def("B")]}
        options={OPTIONS}
        isTray
      />,
    );
    expect(screen.getByRole("button", { name: "Print again" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Printed 2 labels.");
  });

  // Review fix-up: confirmed live -- printed a 2-label tray, then duplicated
  // it to 64 items AFTER the job finished, and the (still-mounted) success
  // line silently rewrote itself from "Printed 2 labels." to "Printed 64
  // labels.", a role="status" region asserting a false fact about a
  // completed machine action. `job.submittedCount` (frozen by
  // hooks/usePrintJob.ts at submit() time) must win over whatever `labels`
  // happens to be on THIS render, however stale or fresh `job.phase` is.
  it("the done-state success line uses the FROZEN submittedCount, never re-derived from the current (possibly since-changed) labels prop", () => {
    render(
      <PrintButton
        job={fakeJob({ phase: "done", submittedCount: 2 })}
        labels={Array.from({ length: 64 }, (_, i) => def(`ITEM-${i}`))}
        options={OPTIONS}
        isTray
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Printed 2 labels.");
    expect(screen.queryByText(/64 labels/)).not.toBeInTheDocument();
  });

  it("on failed, shows the job's error text and keeps the button clickable (tray stays intact for a retry)", () => {
    render(<PrintButton job={fakeJob({ phase: "failed", errorText: "printer out of tape" })} labels={[def("A")]} options={OPTIONS} />);
    expect(screen.getByRole("alert")).toHaveTextContent("printer out of tape");
    expect(screen.getByRole("button", { name: "Print 1 label" })).not.toBeDisabled();
  });

  it("shows cancelError inline (e.g. a 409) without hiding the job's own phase UI", () => {
    render(
      <PrintButton
        job={fakeJob({ phase: "printing", canCancel: false, cancelError: "cannot cancel job in status 'printing'" })}
        labels={[def("A")]}
        options={OPTIONS}
      />,
    );
    expect(screen.getByText("cannot cancel job in status 'printing'")).toBeInTheDocument();
  });
});
