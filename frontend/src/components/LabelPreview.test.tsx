import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LabelPreview } from "./LabelPreview";

describe("LabelPreview", () => {
  it("shows the physical length from length_mm (never derived from scaled px) and renders warning chips", () => {
    // UNIT TRAP guard: this component's props have no width_px/height_px at
    // all (see LabelPreview.tsx's BAND_PX_PER_MM doc) -- lengthMm is the
    // ONLY source for the physical readout. A `scale`-naive px->mm
    // derivation (e.g. widthPx / DOTS_PER_MM without dividing out the
    // preview endpoint's `scale` multiplier) would read roughly double the
    // real length for a scale-2 render; passing the brief's own worked
    // example (54.2mm) and asserting it renders verbatim locks in that the
    // readout is the backend's physical truth, not a client-side guess.
    render(
      <LabelPreview
        tapeWidthMm={24}
        hasContent
        png="data:image/png;base64,AAAA"
        lengthMm={54.2}
        warnings={["auto font size hit the minimum size; text may be cramped"]}
        isFetching={false}
        error={null}
      />,
    );

    expect(screen.getByText("54.2 mm")).toBeInTheDocument();
    expect(
      screen.getByText("auto font size hit the minimum size; text may be cramped"),
    ).toBeInTheDocument();
  });
});
