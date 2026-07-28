import { useRef, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TokenInsertButtons } from "./TokenInsertButtons";
import { useDesignerStore } from "../../stores/designer";
import { TextInput } from "../ui/inputs";

const INITIAL_STORE_STATE = useDesignerStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_STORE_STATE, true);
});

function Harness({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial);
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div>
      <TextInput ref={inputRef} value={value} onChange={setValue} ariaLabel="Line 1" />
      <TokenInsertButtons inputRef={inputRef} value={value} onChange={setValue} fieldLabel="Line 1" />
    </div>
  );
}

describe("TokenInsertButtons", () => {
  it("renders nothing while serialization is off", () => {
    render(<Harness initial="" />);
    expect(screen.queryByRole("button", { name: /Insert \{seq\}/ })).not.toBeInTheDocument();
  });

  it("offers only {seq} for non-CSV kinds, once serialization is on", () => {
    useDesignerStore.getState().setSerializationEnabled(true);
    render(<Harness initial="" />);

    expect(screen.getByRole("button", { name: "Insert {seq} into Line 1" })).toBeInTheDocument();
    expect(screen.queryByText(/csv\./)).not.toBeInTheDocument();
  });

  it("offers {seq} plus one {csv.<col>} button per detected column in CSV mode", () => {
    useDesignerStore.getState().setSerializationEnabled(true);
    useDesignerStore.getState().setSequence({
      ...useDesignerStore.getState().sequence,
      kind: "csv",
      rows: [{ port: "1", label: "Uplink" }],
    });
    render(<Harness initial="" />);

    expect(screen.getByRole("button", { name: "Insert {seq} into Line 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Insert {csv.port} into Line 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Insert {csv.label} into Line 1" })).toBeInTheDocument();
  });

  it("clicking a token button inserts it AT THE CURSOR, not just appended to the end", async () => {
    const user = userEvent.setup();
    useDesignerStore.getState().setSerializationEnabled(true);
    render(<Harness initial="PORT-" />);

    const input = screen.getByLabelText("Line 1") as HTMLInputElement;
    input.focus();
    input.setSelectionRange(5, 5); // cursor right after "PORT-"

    await user.click(screen.getByRole("button", { name: "Insert {seq} into Line 1" }));

    expect(input).toHaveValue("PORT-{seq}");
  });

  it("inserting mid-string splices the token in without disturbing the rest of the text", async () => {
    const user = userEvent.setup();
    useDesignerStore.getState().setSerializationEnabled(true);
    render(<Harness initial="AB" />);

    const input = screen.getByLabelText("Line 1") as HTMLInputElement;
    input.focus();
    input.setSelectionRange(1, 1); // cursor between "A" and "B"

    await user.click(screen.getByRole("button", { name: "Insert {seq} into Line 1" }));

    expect(input).toHaveValue("A{seq}B");
  });
});
