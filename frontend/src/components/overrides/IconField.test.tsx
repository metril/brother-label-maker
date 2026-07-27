import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Icon } from "../../api/types";
import { renderWithQueryClient } from "../../test/utils";
import { IconField } from "./IconField";
import type { OverrideFieldProps } from "./types";

function Harness({ initial, onChangeSpy }: { initial: Icon | null; onChangeSpy?: (v: unknown) => void }) {
  const [value, setValue] = useState<Icon | null>(initial);
  const props: OverrideFieldProps = {
    fieldKey: "icon",
    schema: {},
    root: {},
    value,
    onChange: (v) => {
      onChangeSpy?.(v);
      setValue(v as Icon | null);
    },
    path: ["icon"],
    allParams: {},
    labelType: "text",
  };
  return <IconField {...props} />;
}

describe("IconField", () => {
  it("symbol picker: switching to Symbol and clicking a result inserts it as the icon value", async () => {
    const user = userEvent.setup();
    const onChangeSpy = vi.fn();
    renderWithQueryClient(<Harness initial={null} onChangeSpy={onChangeSpy} />);

    await user.click(screen.getByRole("radio", { name: "Symbol" }));
    await user.type(screen.getByLabelText("Search symbols"), "bolt");

    const bolt = await screen.findByRole("option", { name: "Bolt" });
    await user.click(bolt);

    expect(onChangeSpy).toHaveBeenCalledWith({ kind: "symbol", id: "bolt" });
  });

  it("image upload: selecting a file POSTs to /api/images and shows a thumbnail from the returned image_id", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<Harness initial={null} />);

    await user.click(screen.getByRole("radio", { name: "Image" }));
    const file = new File(["fake-bytes"], "logo.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Upload image"), file);

    const thumb = await screen.findByAltText("Uploaded icon");
    expect(thumb).toHaveAttribute("src", expect.stringContaining("/api/images/img-1"));
  });

  it("clear removes the image icon back to null", async () => {
    const user = userEvent.setup();
    const onChangeSpy = vi.fn();
    renderWithQueryClient(
      <Harness initial={{ kind: "image", image_id: "img-1", mode: "threshold", threshold: 128 }} onChangeSpy={onChangeSpy} />,
    );

    expect(screen.getByAltText("Uploaded icon")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear image" }));

    expect(onChangeSpy).toHaveBeenCalledWith(null);
    expect(screen.queryByAltText("Uploaded icon")).not.toBeInTheDocument();
  });
});
