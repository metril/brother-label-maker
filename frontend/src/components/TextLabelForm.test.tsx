import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TextLabelForm } from "./TextLabelForm";
import { useDesignerStore } from "../stores/designer";

const INITIAL_STATE = useDesignerStore.getState();

beforeEach(() => {
  useDesignerStore.setState(INITIAL_STATE, true);
});

describe("TextLabelForm", () => {
  it("renders defaults: one empty line, no remove button, an add-line affordance", () => {
    render(<TextLabelForm />);

    expect(screen.getByLabelText("Line 1")).toHaveValue("");
    expect(screen.queryByLabelText("Remove line 1")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add line/i })).toBeInTheDocument();
  });

  it("adding/removing lines respects the 1-4 bounds", async () => {
    const user = userEvent.setup();
    render(<TextLabelForm />);
    const addLine = () => screen.getByRole("button", { name: /add line/i });

    await user.click(addLine());
    await user.click(addLine());
    await user.click(addLine());

    expect(screen.getByLabelText("Line 4")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add line/i })).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Remove line 4"));
    await user.click(screen.getByLabelText("Remove line 3"));
    await user.click(screen.getByLabelText("Remove line 2"));

    expect(screen.queryByLabelText("Line 2")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Remove line 1")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add line/i })).toBeInTheDocument();
  });

  it("switching font size to manual reveals the numeric px input", async () => {
    const user = userEvent.setup();
    render(<TextLabelForm />);

    expect(screen.queryByLabelText(/font size in pixels/i)).not.toBeInTheDocument();

    const [fontSizeManual] = screen.getAllByRole("radio", { name: "Manual" });
    await user.click(fontSizeManual!);

    expect(screen.getByLabelText(/font size in pixels/i)).toHaveValue(24);
  });
});
