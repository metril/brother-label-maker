import { useState } from "react";
import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { renderWithQueryClient } from "../../test/utils";
import { server } from "../../test/msw/server";
import { FontFamilyField } from "./FontFamilyField";
import type { OverrideFieldProps } from "./types";

function Harness({ initial, onChangeSpy }: { initial: unknown; onChangeSpy?: (v: unknown) => void }) {
  const [value, setValue] = useState<unknown>(initial);
  const props: OverrideFieldProps = {
    fieldKey: "font_family",
    schema: {},
    root: {},
    value,
    onChange: (v) => {
      onChangeSpy?.(v);
      setValue(v);
    },
    path: ["font_family"],
    allParams: {},
    labelType: "text",
  };
  return <FontFamilyField {...props} />;
}

describe("FontFamilyField", () => {
  it("renders the bundled font catalog from GET /api/fonts as select options", async () => {
    renderWithQueryClient(<Harness initial="Inter" />);

    const select = await screen.findByLabelText("Font family");
    expect(select).toHaveValue("Inter");
    expect(screen.getAllByRole("option").length).toBeGreaterThan(0);
  });

  // Task 4.3: a failed GET /api/fonts used to leave this on the `···`
  // pending indicator forever (`isPending` goes false on error, but `data`
  // stays undefined and the old `isPending || !fonts` guard conflated the
  // two) -- no error text, no way to try again short of a full reload.
  it("shows a role=alert message with a Retry button when /api/fonts fails, and recovers on retry", async () => {
    let attempt = 0;
    server.use(
      http.get("/api/fonts", () => {
        attempt += 1;
        if (attempt === 1) return HttpResponse.json({ detail: "boom" }, { status: 500 });
        return HttpResponse.json([{ family: "Inter", display_name: "Inter" }]);
      }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<Harness initial="Inter" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load fonts.");
    expect(screen.queryByLabelText("Font family")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByLabelText("Font family")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
