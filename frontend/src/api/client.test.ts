import { describe, expect, it } from "vitest";
import { extractErrorDetail } from "./client";

describe("extractErrorDetail", () => {
  it("extracts a readable message from both 422 detail shapes FastAPI can send", () => {
    // Shape 1: our own handlers' HTTPException(422, detail=<string>)
    // (router_labels.py / router_print.py's error_message()).
    expect(
      extractErrorDetail(
        { detail: "unknown label type 'barcode'; valid: ['text']" },
        "fallback",
      ),
    ).toBe("unknown label type 'barcode'; valid: ['text']");

    // Shape 2: FastAPI's own automatic pydantic request-validation 422s --
    // detail is an array of {loc, msg, type} issues, not a string.
    expect(
      extractErrorDetail(
        {
          detail: [
            { loc: ["body", "definition", "tape", "width_mm"], msg: "field required", type: "missing" },
          ],
        },
        "fallback",
      ),
    ).toBe("definition.tape.width_mm: field required");

    // Neither shape present -- falls back instead of dumping raw JSON.
    expect(extractErrorDetail(null, "fallback")).toBe("fallback");
    expect(extractErrorDetail({}, "fallback")).toBe("fallback");
  });
});
