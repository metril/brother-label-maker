import { describe, expect, it } from "vitest";
import { extractErrorDetail, parsePydanticValidationError } from "./client";

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

  // Review fix-up: a body-level `@model_validator` ValueError that NO
  // route ever catches (e.g. Sequence's own total-labels cap check,
  // backend/render/serialize.py -- raised while FastAPI is still parsing
  // POST /api/render/expand's request body, so it arrives as shape 2
  // above, never routed through error_message()) used to leak pydantic's
  // own "Value error, " prefix verbatim, since only the STRING-dump path
  // (parsePydanticValidationError) stripped it.
  it("strips pydantic's 'Value error, ' prefix from shape 2 (array) issues too, not just the string-dump shape", () => {
    expect(
      extractErrorDetail(
        {
          detail: [
            {
              loc: ["body", "serialization"],
              msg: "Value error, total labels 1500 (500 values x 3 copies) exceeds the 1000 maximum",
              type: "value_error",
            },
          ],
        },
        "fallback",
      ),
    ).toBe("serialization: total labels 1500 (500 values x 3 copies) exceeds the 1000 maximum");
  });

  it("turns a raw pydantic ValidationError dump (error_message()'s str(exc) for a ValidationError that slipped past client-side checks) into a readable message instead of the bracket/URL-laden original", () => {
    // Captured verbatim from a live 422 (POST /api/render/preview,
    // breaker_box with pitch_mm=5 against a minimum of 10).
    const raw =
      "1 validation error for BreakerBoxParams\npitch_mm\n  Input should be " +
      "greater than or equal to 10 [type=greater_than_equal, input_value=5, " +
      "input_type=int]\n    For further information visit " +
      "https://errors.pydantic.dev/2.13/v/greater_than_equal";

    expect(extractErrorDetail({ detail: raw }, "fallback")).toBe(
      "pitch_mm: Input should be greater than or equal to 10",
    );
  });

  it("joins multiple pydantic errors with '; ', in order, and strips a 'Value error, ' validator prefix", () => {
    const raw =
      "3 validation errors for BreakerBoxParams\n" +
      "pitch_mm\n  Input should be greater than or equal to 10 [type=greater_than_equal, input_value=5, input_type=int]\n    For further information visit https://errors.pydantic.dev/2.13/v/greater_than_equal\n" +
      "breakers.0.poles\n  Input should be less than or equal to 4 [type=less_than_equal, input_value=9, input_type=int]\n    For further information visit https://errors.pydantic.dev/2.13/v/less_than_equal\n" +
      "start_value\n  Input should be less than or equal to 999 [type=less_than_equal, input_value=1000, input_type=int]\n    For further information visit https://errors.pydantic.dev/2.13/v/less_than_equal";

    expect(parsePydanticValidationError(raw)).toBe(
      "pitch_mm: Input should be greater than or equal to 10; " +
        "breakers.0.poles: Input should be less than or equal to 4; " +
        "start_value: Input should be less than or equal to 999",
    );
  });

  it("survives a validator message that itself contains brackets (e.g. 'must be in [6, 128]') without truncating at the wrong bracket", () => {
    const raw =
      "1 validation error for TextLabelParams\nfont_size_px\n  Value error, " +
      "font_size_px must be in [6, 128], got 500 [type=value_error, " +
      "input_value=500, input_type=int]\n    For further information visit " +
      "https://errors.pydantic.dev/2.13/v/value_error";

    expect(parsePydanticValidationError(raw)).toBe("font_size_px: font_size_px must be in [6, 128], got 500");
  });

  it("returns null (not a pydantic dump) for an already-readable string, so extractErrorDetail passes it through unchanged", () => {
    expect(parsePydanticValidationError("all labels in a print job must share the same tape")).toBeNull();
    expect(extractErrorDetail({ detail: "all labels in a print job must share the same tape" }, "fallback")).toBe(
      "all labels in a print job must share the same tape",
    );
  });
});
