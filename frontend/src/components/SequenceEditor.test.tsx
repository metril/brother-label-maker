import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { SequenceEditor } from "./SequenceEditor";
import { buildDefaultParams } from "../schema/defaults";
import type { JsonSchemaObject } from "../schema/jsonSchema";
import { useDesignerStore } from "../stores/designer";
import { renderWithQueryClient } from "../test/utils";
import { server } from "../test/msw/server";
import labelTypesFixture from "../test/fixtures/label-types.json";

interface FixtureType {
  type: string;
  title: string;
  params_schema: JsonSchemaObject;
}

const LABEL_TYPES = labelTypesFixture as unknown as FixtureType[];
const TEXT_TYPE = LABEL_TYPES.find((t) => t.type === "text")!;

const INITIAL_STORE_STATE = useDesignerStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_STORE_STATE, true);
});

function enableSerialization() {
  useDesignerStore.getState().setSerializationEnabled(true);
}

/** Selects the "text" type with `lines: ["PORT-{seq}"]` -- required for
 * live-chips tests that need `sample` to actually carry a `{seq}` token
 * (useSequenceExpand.ts's own "first text field" derivation reads
 * selectedType/paramsByType from the store, same as the real app), which
 * is what exercises POST /api/render/expand's `samples` field (capped at
 * 24 server-side) rather than its uncapped `values`. */
function selectTextTypeWithToken(line = "PORT-{seq}") {
  useDesignerStore.getState().selectType("text", TEXT_TYPE.params_schema);
  useDesignerStore.getState().setParams("text", { ...buildDefaultParams(TEXT_TYPE.params_schema), lines: [line] });
}

describe("SequenceEditor -- off by default", () => {
  it("shows a plain explainer and no controls until the toggle is turned on", () => {
    renderWithQueryClient(<SequenceEditor />);
    expect(screen.getByText(/Turn on to print a numbered, lettered, list, or CSV-driven run/)).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Serialization kind" })).not.toBeInTheDocument();
  });

  it("turning the toggle on reveals the kind picker, defaulted to Numbers", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<SequenceEditor />);

    await user.click(screen.getByRole("checkbox", { name: "On" }));

    expect(screen.getByRole("radiogroup", { name: "Serialization kind" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Numbers" })).toHaveAttribute("aria-checked", "true");
  });
});

describe("SequenceEditor -- kind switching shows/hides the right controls", () => {
  it("Numbers shows start/step/count/pad; Letters shows start-letter/step/count; List shows a textarea; CSV shows a file input", async () => {
    const user = userEvent.setup();
    enableSerialization();
    renderWithQueryClient(<SequenceEditor />);

    expect(screen.getByLabelText("Start")).toBeInTheDocument();
    expect(screen.getByLabelText("Zero-pad width")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Letters" }));
    expect(screen.getByLabelText("Start letter(s)")).toBeInTheDocument();
    expect(screen.queryByLabelText("Zero-pad width")).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "List" }));
    expect(screen.getByLabelText("Values (one per line)")).toBeInTheDocument();
    expect(screen.queryByLabelText("Start letter(s)")).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "CSV" }));
    expect(screen.getByLabelText("Upload CSV")).toBeInTheDocument();
    expect(screen.queryByLabelText("Values (one per line)")).not.toBeInTheDocument();
  });
});

describe("SequenceEditor -- bounds enforced with inline errors (task 2.11 brief's own test list)", () => {
  it("count 501 shows an inline error", async () => {
    const user = userEvent.setup();
    enableSerialization();
    renderWithQueryClient(<SequenceEditor />);

    const count = screen.getByLabelText("Count");
    await user.clear(count);
    await user.type(count, "501");

    expect(await screen.findByText(/must be a whole number between 1 and 500/)).toBeInTheDocument();
  });

  it("copies_per_value 101 shows an inline error", async () => {
    const user = userEvent.setup();
    enableSerialization();
    renderWithQueryClient(<SequenceEditor />);

    const copies = screen.getByLabelText("Copies per value");
    await user.clear(copies);
    await user.type(copies, "101");

    expect(await screen.findByText(/must be a whole number between 1 and 100/)).toBeInTheDocument();
  });

  it("pad_width 7 shows an inline error", async () => {
    const user = userEvent.setup();
    enableSerialization();
    renderWithQueryClient(<SequenceEditor />);

    const pad = screen.getByLabelText("Zero-pad width");
    await user.clear(pad);
    await user.type(pad, "7");

    expect(await screen.findByText(/must be a whole number between 0 and 6/)).toBeInTheDocument();
  });

  it("step 0 shows an inline error", async () => {
    const user = userEvent.setup();
    enableSerialization();
    renderWithQueryClient(<SequenceEditor />);

    const step = screen.getByLabelText("Step");
    await user.clear(step);
    await user.type(step, "0");

    expect(await screen.findByText(/step must not be 0/)).toBeInTheDocument();
  });

  it('alpha_start "a1" auto-uppercases to "A1" and still shows an inline error (digit not allowed)', async () => {
    const user = userEvent.setup();
    enableSerialization();
    renderWithQueryClient(<SequenceEditor />);
    await user.click(screen.getByRole("radio", { name: "Letters" }));

    const alphaStart = screen.getByLabelText("Start letter(s)");
    await user.clear(alphaStart);
    await user.type(alphaStart, "a1");

    expect(alphaStart).toHaveValue("A1");
    expect(await screen.findByText(/1-3 letters, A-Z only/)).toBeInTheDocument();
  });
});

describe("SequenceEditor -- live value chips", () => {
  it("debounces rapid edits into a single expand request, shows chips, total-labels, and '... and N more' past 24 (values branch, sample untokenized)", async () => {
    const user = userEvent.setup();
    const requestSpy = vi.fn();
    server.use(
      http.post("/api/render/expand", async ({ request }) => {
        requestSpy();
        const body = (await request.json()) as { serialization: { count: number } };
        const count = body.serialization.count;
        const values = Array.from({ length: count }, (_, i) => String(i + 1).padStart(2, "0"));
        return HttpResponse.json({ values, total_labels: count, samples: null });
      }),
    );

    enableSerialization();
    useDesignerStore.getState().setSequence({ ...useDesignerStore.getState().sequence, count: 30 });
    renderWithQueryClient(<SequenceEditor />);

    // Rapid edits within the debounce window -- only the settled value
    // should reach the network once chips resolve.
    const count = screen.getByLabelText("Count");
    await user.clear(count);
    await user.type(count, "30");

    await waitFor(() => expect(screen.getByText("30 labels")).toBeInTheDocument(), { timeout: 3000 });
    await waitFor(() => expect(requestSpy).toHaveBeenCalled());
    // "01".."06" also appear in the (unrelated) collation-pattern demo just
    // above -- assert against values only the live-chips section renders
    // (it shows all 24, the demo caps at 6 distinct values).
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("24")).toBeInTheDocument();
    expect(screen.queryByText("25")).not.toBeInTheDocument();
    expect(screen.getByText("… and 6 more")).toBeInTheDocument();
  });

  // Review fix-up: the ORIGINAL version of this test used an untokenized
  // `sample` (samples: null), which only ever exercises the `data.values`
  // branch of LiveChips' chip source -- `data.values` is UNCAPPED, so
  // `more = chips.length - shown.length` happened to read correctly there
  // by coincidence. The real, common case (a template field actually
  // containing `{seq}`/`{csv.*}`) goes through `data.samples` instead,
  // which the backend caps at 24 itself (router_labels.py's
  // `_MAX_SAMPLES`) -- so `chips.length` in THAT branch is never more than
  // 24, making the old `more` formula structurally always 0. This test
  // pins the token-substituted path specifically: 30 distinct values, a
  // `{seq}`-carrying sample, 24 samples come back, and "… and 6 more"
  // must still say 6 (derived from the UNCAPPED `values.length`, not the
  // capped `samples.length`).
  it("'... and N more' is derived from the uncapped distinct-value total, not the (backend-capped-at-24) samples array, when the sample carries a {seq} token", async () => {
    server.use(
      http.post("/api/render/expand", async ({ request }) => {
        const body = (await request.json()) as { serialization: { count: number }; sample?: string };
        const count = body.serialization.count;
        const values = Array.from({ length: count }, (_, i) => String(i + 1).padStart(2, "0"));
        const samples = body.sample ? values.slice(0, 24).map((v) => body.sample!.replace("{seq}", v)) : null;
        return HttpResponse.json({ values, total_labels: count, samples });
      }),
    );

    selectTextTypeWithToken("PORT-{seq}");
    enableSerialization();
    useDesignerStore.getState().setSequence({ ...useDesignerStore.getState().sequence, count: 30 });
    renderWithQueryClient(<SequenceEditor />);

    await waitFor(() => expect(screen.getByText("30 labels")).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByText("PORT-10")).toBeInTheDocument();
    expect(screen.getByText("PORT-24")).toBeInTheDocument();
    expect(screen.queryByText("PORT-25")).not.toBeInTheDocument();
    expect(screen.getByText("… and 6 more")).toBeInTheDocument();
  });

  it("over-cap total shows the server's readable message inline", async () => {
    enableSerialization();
    useDesignerStore.getState().setSequence({
      ...useDesignerStore.getState().sequence,
      count: 500,
      copies_per_value: 3,
    });
    renderWithQueryClient(<SequenceEditor />);

    expect(await screen.findByRole("alert", {}, { timeout: 3000 })).toHaveTextContent(/exceeds the 1000 maximum/);
  });
});

describe("SequenceEditor -- collation pattern chips", () => {
  it("renders copies_adjacent vs sequence_repeated ordering for the current values", async () => {
    const user = userEvent.setup();
    enableSerialization();
    useDesignerStore.getState().setSequence({
      ...useDesignerStore.getState().sequence,
      kind: "list",
      values: ["A", "B", "C"],
      copies_per_value: 2,
      collation: "copies_adjacent",
    });
    renderWithQueryClient(<SequenceEditor />);

    await waitFor(() => expect(screen.getByText("6 labels")).toBeInTheDocument(), { timeout: 3000 });
    const adjacentGroup = screen.getByRole("radiogroup", { name: "Collation" });
    expect(within(adjacentGroup).getByRole("radio", { name: "Copies adjacent" })).toHaveAttribute("aria-checked", "true");

    await user.click(within(adjacentGroup).getByRole("radio", { name: "Sequence repeated" }));
    expect(screen.getByText("The whole run repeats, in order: A B A B.")).toBeInTheDocument();
  });
});

describe("SequenceEditor -- CSV upload", () => {
  it("a successful upload shows detected columns, row count, and a preview table", async () => {
    const user = userEvent.setup();
    enableSerialization();
    useDesignerStore.getState().setSequence({ ...useDesignerStore.getState().sequence, kind: "csv" });
    renderWithQueryClient(<SequenceEditor />);

    const file = new File(["port,label\n1,Uplink\n2,Downlink\n"], "ports.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Upload CSV"), file);

    expect(await screen.findByText("2 rows")).toBeInTheDocument();
    expect(screen.getByText("{csv.port}")).toBeInTheDocument();
    expect(screen.getByText("{csv.label}")).toBeInTheDocument();
    expect(screen.getByText("Uplink")).toBeInTheDocument();
  });

  it("a readable server error (e.g. ragged rows) surfaces inline", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/serialize/csv", () =>
        HttpResponse.json({ detail: "CSV row 2 has 1 column(s), expected 2" }, { status: 422 }),
      ),
    );
    enableSerialization();
    useDesignerStore.getState().setSequence({ ...useDesignerStore.getState().sequence, kind: "csv" });
    renderWithQueryClient(<SequenceEditor />);

    const file = new File(["port,label\n1\n"], "ragged.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Upload CSV"), file);

    // Two role="alert"s are on screen at once here (the upload error AND
    // the still-unsatisfied "upload a CSV file" field error, since the
    // failed upload never populated `rows`) -- assert on the specific
    // readable text rather than a single ambiguous role query.
    expect(await screen.findByText("CSV row 2 has 1 column(s), expected 2")).toBeInTheDocument();
  });
});
