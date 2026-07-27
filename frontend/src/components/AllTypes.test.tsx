import { describe, expect, it } from "vitest";
import { cleanup } from "@testing-library/react";
import { SchemaForm } from "./schema/SchemaForm";
import { buildDefaultParams } from "../schema/defaults";
import type { JsonSchemaObject } from "../schema/jsonSchema";
import { renderWithQueryClient } from "../test/utils";
import labelTypesFixture from "../test/fixtures/label-types.json";

interface FixtureType {
  type: string;
  title: string;
  params_schema: JsonSchemaObject;
}

const LABEL_TYPES = labelTypesFixture as unknown as FixtureType[];

// "All 9 types render a form from their real schema without crashing" --
// task 2.10 brief. Fixtured straight from the live backend (see
// scripts/gen-fixtures.mjs), not hand-approximated -- if a Params model
// changes shape without regenerating the fixture, this stays green against
// stale data (a real drift risk) but a mismatched fixture is exactly what
// a live-check re-run (see the task report) catches independently.
describe("SchemaForm renders every real label type without crashing", () => {
  it("all 9 types (default params, straight from their own schema) render without throwing", () => {
    expect(LABEL_TYPES.length).toBe(9);

    for (const labelType of LABEL_TYPES) {
      const params = buildDefaultParams(labelType.params_schema);
      let container: HTMLElement;
      try {
        ({ container } = renderWithQueryClient(
          <SchemaForm labelType={labelType.type} schema={labelType.params_schema} params={params} onChange={() => {}} />,
        ));
      } catch (err) {
        throw new Error(`label type "${labelType.type}" (${labelType.title}) failed to render: ${err}`, { cause: err });
      }
      expect(container.querySelectorAll("input, select, button").length).toBeGreaterThan(0);
      cleanup();
    }
  });
});
