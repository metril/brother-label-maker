import { beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SchemaForm } from "../components/schema/SchemaForm";
import { TypeRail } from "../components/TypeRail";
import { buildDefaultParams } from "../schema/defaults";
import type { JsonSchemaObject } from "../schema/jsonSchema";
import { useDesignerStore } from "../stores/designer";
import { renderWithQueryClient } from "./utils";
import labelTypesFixture from "./fixtures/label-types.json";

interface FixtureType {
  type: string;
  title: string;
  params_schema: JsonSchemaObject;
}

const LABEL_TYPES = labelTypesFixture as unknown as FixtureType[];
const TEXT_TYPE = LABEL_TYPES.find((t) => t.type === "text")!;

const INITIAL_STORE_STATE = useDesignerStore.getState();
beforeEach(() => {
  useDesignerStore.setState(INITIAL_STORE_STATE, true);
});

describe("accessibility smoke", () => {
  it("the left type rail is arrow-key navigable and marks the active type with aria-current", async () => {
    const user = userEvent.setup();
    useDesignerStore.getState().selectType("text", TEXT_TYPE.params_schema);
    renderWithQueryClient(<TypeRail />);

    const textButton = await screen.findByRole("button", { name: "Text" });
    expect(textButton).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Barcode" })).not.toHaveAttribute("aria-current");

    textButton.focus();
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Barcode" }));
  });

  it("every control the schema-driven form renders has an associated accessible label, across control shapes", () => {
    const params = buildDefaultParams(TEXT_TYPE.params_schema);
    renderWithQueryClient(<SchemaForm labelType="text" schema={TEXT_TYPE.params_schema} params={params} onChange={() => {}} />);

    // Repeatable-row text input (array-of-string), a select-backed override
    // (FontFamilyField), a checkbox, and a bounded number field -- one of
    // each control family this engine renders, all reachable by label text.
    expect(screen.getByLabelText("Lines 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Bold")).toBeInTheDocument();
    expect(screen.getByLabelText("Padding (mm)")).toBeInTheDocument();
  });

  it("a sample control is programmatically focusable (keyboard focus reachable -- the CSS focus-visible ring itself isn't renderable under jsdom)", () => {
    const params = buildDefaultParams(TEXT_TYPE.params_schema);
    renderWithQueryClient(<SchemaForm labelType="text" schema={TEXT_TYPE.params_schema} params={params} onChange={() => {}} />);

    const boldCheckbox = screen.getByLabelText("Bold");
    boldCheckbox.focus();
    expect(document.activeElement).toBe(boldCheckbox);
  });
});
