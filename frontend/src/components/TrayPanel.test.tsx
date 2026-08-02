import { afterEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { http } from "msw";
import { TrayPanel } from "./TrayPanel";
import { useTrayStore } from "../stores/tray";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";

const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
});

/** components/GlobalTrayDrawer.tsx always passes `current={null}` (there's
 * no "current, unsaved design" away from the Designer page) -- these cover
 * the one shape GlobalTrayDrawer's own tests can't reach directly, since
 * that component hides itself entirely whenever the tray is empty (so a
 * `current === null` + empty-tray render never happens THROUGH it). Every
 * other `current === null` behavior (non-empty tray, printing, previews) is
 * already covered end-to-end via GlobalTrayDrawer.test.tsx. */
describe("TrayPanel -- current === null (away from the Designer page)", () => {
  it("an empty tray with no current design has nothing to print: Print is disabled, no crash, no serialization branch", async () => {
    server.use(http.post("/api/print/estimate", () => {
      throw new Error("must not be called: nothing renderable to estimate");
    }));

    renderWithProviders(<TrayPanel current={null} />);

    expect(await screen.findByText(/Nothing queued/)).toBeInTheDocument();
    expect(screen.getByText("Add content to estimate tape usage.")).toBeInTheDocument();
    // No "+ Add to tray" affordance either -- there's no current design to add.
    expect(screen.queryByRole("button", { name: "+ Add to tray" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print 0 labels" })).toBeDisabled();
  });
});
