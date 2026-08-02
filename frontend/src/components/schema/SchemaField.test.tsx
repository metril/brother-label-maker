import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { JsonSchemaObject } from "../../schema/jsonSchema";
import { SchemaField } from "./SchemaField";

/** Uncontrolled-from-the-caller's-perspective harness: SchemaField itself
 * is a controlled component (value/onChange props), so most interaction
 * tests need SOMETHING holding state between renders -- this is that,
 * kept in the test file rather than exported, since no real caller ever
 * uses SchemaField this directly (SchemaForm always owns the params
 * object -- see SchemaForm.test.tsx / AllTypes.test.tsx for that level). */
function Harness<T>({ schema, root, fieldKey, initial }: { schema: JsonSchemaObject; root?: JsonSchemaObject; fieldKey: string; initial: T }) {
  const [value, setValue] = useState<T>(initial);
  return (
    <SchemaField
      fieldKey={fieldKey}
      schema={schema}
      root={root ?? schema}
      value={value}
      onChange={(v) => setValue(v as T)}
      path={[fieldKey]}
      allParams={{}}
    />
  );
}

describe("SchemaField shapes", () => {
  it("string: renders a labeled text input with maxLength enforced, description becomes help text, typing calls onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const schema: JsonSchemaObject = {
      type: "string",
      description: "the value encoded in the code",
      maxLength: 500,
    };
    render(<SchemaField fieldKey="data" schema={schema} root={schema} value="" onChange={onChange} path={["data"]} allParams={{}} />);

    const input = screen.getByLabelText("Data");
    expect(input).toHaveAttribute("maxLength", "500");
    expect(screen.getByText("the value encoded in the code")).toBeInTheDocument();
    await user.type(input, "X");
    expect(onChange).toHaveBeenCalledWith("X");
  });

  it("number: carries the schema's own min/max as HTML bounds and shows an inline alert only when the current value violates them", () => {
    const schema: JsonSchemaObject = { type: "number", minimum: 5, maximum: 300 };
    const { rerender } = render(
      <SchemaField fieldKey="block_length_mm" schema={schema} root={schema} value={15} onChange={vi.fn()} path={["x"]} allParams={{}} />,
    );
    const input = screen.getByLabelText("Block length (mm)");
    expect(input).toHaveAttribute("min", "5");
    expect(input).toHaveAttribute("max", "300");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    rerender(
      <SchemaField fieldKey="block_length_mm" schema={schema} root={schema} value={400} onChange={vi.fn()} path={["x"]} allParams={{}} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("must be between 5 and 300");
  });

  it("number: clearing the field emits undefined (never a coerced 0) and shows 'enter a value', not a bounds message", async () => {
    const user = userEvent.setup();
    const schema: JsonSchemaObject = { type: "number", minimum: 5, maximum: 300 };
    render(<Harness schema={schema} fieldKey="block_length_mm" initial={15} />);

    const input = screen.getByLabelText("Block length (mm)");
    await user.clear(input);

    expect(input).toHaveValue(null); // the box is genuinely empty, not snapped back to 0/15
    expect(screen.getByRole("alert")).toHaveTextContent("enter a value");

    await user.type(input, "42");
    expect(input).toHaveValue(42);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("boolean: renders a real switch toggled by its own label", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const schema: JsonSchemaObject = { type: "boolean" };
    render(<SchemaField fieldKey="bold" schema={schema} root={schema} value={false} onChange={onChange} path={["bold"]} allParams={{}} />);

    const toggle = screen.getByLabelText("Bold");
    expect(toggle).toHaveAttribute("role", "switch");
    await user.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("enum with <=4 options renders a keyboard-navigable segmented radiogroup, not a dropdown", () => {
    const schema: JsonSchemaObject = { type: "string", enum: ["left", "center", "right"] };
    render(<SchemaField fieldKey="h_align" schema={schema} root={schema} value="center" onChange={vi.fn()} path={["h_align"]} allParams={{}} />);

    expect(screen.getByRole("radiogroup", { name: "H align" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Center" })).toHaveAttribute("aria-checked", "true");
  });

  it("enum with >4 options renders a native select instead (with a dropdown chevron affordance)", () => {
    const schema: JsonSchemaObject = { type: "string", enum: ["tic", "dash", "line", "bold", "frame", "none"] };
    render(<SchemaField fieldKey="separator" schema={schema} root={schema} value="line" onChange={vi.fn()} path={["separator"]} allParams={{}} />);

    const select = screen.getByLabelText("Separator");
    expect(select.tagName).toBe("SELECT");
    expect(select).toHaveStyle({ backgroundRepeat: "no-repeat" });
  });

  it("array-of-string: add respects maxItems, remove respects minItems, reorder swaps values, rows are labeled 1-indexed", async () => {
    const user = userEvent.setup();
    const schema: JsonSchemaObject = { type: "array", items: { type: "string" }, minItems: 1, maxItems: 2 };
    render(<Harness schema={schema} fieldKey="lines" initial={["A"]} />);

    expect(screen.getByLabelText("Lines 1")).toHaveValue("A");
    expect(screen.getByLabelText("Remove Lines 1")).toBeDisabled(); // at minItems

    await user.click(screen.getByLabelText("Add Lines row"));
    await user.type(screen.getByLabelText("Lines 2"), "B");
    expect(screen.getByLabelText("Add Lines row")).toBeDisabled(); // at maxItems

    await user.click(screen.getByLabelText("Move Lines 1 down"));
    expect(screen.getByLabelText("Lines 1")).toHaveValue("B");
    expect(screen.getByLabelText("Lines 2")).toHaveValue("A");

    await user.click(screen.getByLabelText("Remove Lines 2"));
    expect(screen.queryByLabelText("Lines 2")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Remove Lines 1")).toBeDisabled();
  });

  it("array-of-string: keyboard reorder moves focus WITH the row (stable keys), so repeated presses keep walking the same logical row instead of oscillating", async () => {
    const user = userEvent.setup();
    const schema: JsonSchemaObject = { type: "array", items: { type: "string" }, minItems: 1, maxItems: 5 };
    render(<Harness schema={schema} fieldKey="lines" initial={["A", "B", "C"]} />);

    const moveDownA = screen.getByLabelText("Move Lines 1 down");
    moveDownA.focus();
    await user.keyboard("{Enter}");

    // Row A (now at index 1) took its own DOM/focus WITH it -- the exact
    // same button element, its aria-label updated to match its new
    // position, still focused.
    expect(document.activeElement).toBe(screen.getByLabelText("Move Lines 2 down"));
    expect(screen.getByLabelText("Lines 1")).toHaveValue("B");
    expect(screen.getByLabelText("Lines 2")).toHaveValue("A");

    // Pressing the SAME (still-focused) button again must move row A a
    // second time -- the bug this regresses: keyed-by-index rows left
    // focus sitting at position 1 acting on whatever row happened to be
    // there, so a second press bounced back toward the original order
    // instead of continuing to move A.
    await user.keyboard("{Enter}");
    expect(screen.getByLabelText("Lines 1")).toHaveValue("B");
    expect(screen.getByLabelText("Lines 2")).toHaveValue("C");
    expect(screen.getByLabelText("Lines 3")).toHaveValue("A");
  });

  // Regression: ArrayOfNumbers used to swallow a cleared item entirely
  // (`if (next === undefined) return;`) -- the box went visibly empty
  // (NumberInput's own local text buffer, independent of the parent) while
  // the array handed back up to params still held the pre-clear number, so
  // nothing downstream (hasNumberOutOfRange, the preview request) ever saw
  // anything wrong. Latent in the generic fallback today since patch_panel's
  // `multipliers` uses its own MultipliersField override instead, but a
  // future array-of-number field would have hit it directly.
  it("array-of-number: clearing an item propagates undefined into the value instead of silently keeping the old number", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const schema: JsonSchemaObject = { type: "array", items: { type: "number", minimum: 0.1, maximum: 9.5 }, minItems: 1, maxItems: 3 };
    render(
      <SchemaField
        fieldKey="widths"
        schema={schema}
        root={schema}
        value={[1.5, 2]}
        onChange={onChange}
        path={["widths"]}
        allParams={{}}
      />,
    );

    await user.clear(screen.getByLabelText("Widths 1"));

    expect(onChange).toHaveBeenCalledWith([undefined, 2]);
  });

  it("array-of-object: rows recurse through SchemaField for their own nested fields (labels qualified by row, e.g. 'Breaker 1 Poles', so they don't collide across rows), get block-N DOM ids, and add/remove works", async () => {
    const user = userEvent.setup();
    const root: JsonSchemaObject = {
      type: "object",
      properties: {},
      $defs: {
        BreakerSpec: {
          type: "object",
          properties: {
            poles: { type: "integer", minimum: 1, maximum: 4, default: 1 },
            lines: { type: "array", items: { type: "string", maxLength: 30 }, maxItems: 2 },
          },
        },
      },
    };
    const schema: JsonSchemaObject = { type: "array", items: { $ref: "#/$defs/BreakerSpec" }, minItems: 1, maxItems: 50 };
    render(<Harness schema={schema} root={root} fieldKey="breakers" initial={[{ poles: 1, lines: [] }]} />);

    expect(document.getElementById("block-0")).toBeInTheDocument();
    expect(screen.getByLabelText("Breaker 1 Poles")).toHaveValue(1); // nested field, recursively rendered, row-qualified
    expect(screen.getByLabelText("Remove Breakers 1")).toBeDisabled();

    await user.click(screen.getByLabelText("Add Breakers row"));
    expect(document.getElementById("block-1")).toBeInTheDocument();
    expect(screen.getByLabelText("Breaker 1 Poles")).toBeInTheDocument();
    expect(screen.getByLabelText("Breaker 2 Poles")).toBeInTheDocument(); // unique per row, not a collision

    await user.click(screen.getByLabelText("Remove Breakers 2"));
    expect(document.getElementById("block-1")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Breaker 1 Poles")).toBeInTheDocument();
    expect(screen.queryByLabelText("Breaker 2 Poles")).not.toBeInTheDocument();
  });

  it("array-of-object: keyboard reorder moves focus (and the row's own data) WITH the row too", async () => {
    const user = userEvent.setup();
    const root: JsonSchemaObject = {
      type: "object",
      properties: {},
      $defs: { BreakerSpec: { type: "object", properties: { poles: { type: "integer", minimum: 1, maximum: 4, default: 1 } } } },
    };
    const schema: JsonSchemaObject = { type: "array", items: { $ref: "#/$defs/BreakerSpec" }, minItems: 1, maxItems: 5 };
    render(<Harness schema={schema} root={root} fieldKey="breakers" initial={[{ poles: 1 }, { poles: 2 }, { poles: 3 }]} />);

    const moveDown1 = screen.getByLabelText("Move Breakers 1 down");
    moveDown1.focus();
    await user.keyboard("{Enter}");

    expect(document.activeElement).toBe(screen.getByLabelText("Move Breakers 2 down"));
    expect(screen.getByLabelText("Breaker 1 Poles")).toHaveValue(2);
    expect(screen.getByLabelText("Breaker 2 Poles")).toHaveValue(1);
  });

  it("nullable field: starts Auto (control hidden), Manual reveals it seeded with a sensible value, Auto clears it back to null", async () => {
    const user = userEvent.setup();
    const schema: JsonSchemaObject = {
      anyOf: [{ type: "integer" }, { type: "null" }],
      default: null,
      description: "fixed font size in px; omit for auto-fit",
    };
    render(<Harness schema={schema} fieldKey="font_size_px" initial={null} />);

    expect(screen.getByText("fixed font size in px; omit for auto-fit")).toBeInTheDocument();
    expect(screen.queryByLabelText("Font size (px)")).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Manual" }));
    expect(screen.getByLabelText("Font size (px)")).toHaveValue(24);

    await user.click(screen.getByRole("radio", { name: "Auto" }));
    expect(screen.queryByLabelText("Font size (px)")).not.toBeInTheDocument();
  });

  // Regression: clearing a Manual nullable number field used to unmount the
  // control entirely. NumberInput emits `undefined` (never null) for a
  // cleared box; SchemaField's nullable branch treated `undefined` the same
  // as the field's own `null` ("Auto"), so `!isAuto` (gating FieldControl's
  // very presence) flipped to false mid-edit -- two backspaces on a seeded
  // Manual value yanked the input out from under the user's cursor, snapped
  // the toggle back to "Auto", and showed no error at all.
  it("nullable field: clearing a Manual value keeps the control mounted (does not snap back to Auto) and shows 'enter a value'", async () => {
    const user = userEvent.setup();
    const schema: JsonSchemaObject = {
      anyOf: [{ type: "integer" }, { type: "null" }],
      default: null,
      description: "fixed font size in px; omit for auto-fit",
    };
    render(<Harness schema={schema} fieldKey="font_size_px" initial={null} />);

    await user.click(screen.getByRole("radio", { name: "Manual" }));
    const input = screen.getByLabelText("Font size (px)");
    expect(input).toHaveValue(24);

    await user.clear(input);

    // Still mounted and still in Manual mode -- not unmounted, not reverted.
    expect(screen.getByLabelText("Font size (px)")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Manual" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Auto" })).toHaveAttribute("aria-checked", "false");
    expect(document.activeElement).toBe(screen.getByLabelText("Font size (px)")); // focus stayed put

    // Gates like the non-nullable number path: a real inline alert, not a
    // silent Auto fallback.
    expect(screen.getByRole("alert")).toHaveTextContent("enter a value");

    // The field is still genuinely editable -- backspace-and-retype works.
    await user.type(input, "18");
    expect(input).toHaveValue(18);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
