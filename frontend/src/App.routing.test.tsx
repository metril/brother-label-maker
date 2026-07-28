import { afterEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { useDesignerStore } from "./stores/designer";
import { useTrayStore } from "./stores/tray";

// stores/designer.ts + stores/tray.ts are module-level zustand singletons --
// reset between tests so navigating/typing in one test can't leak state
// into the next (same convention as pages/Designer.test.tsx).
const INITIAL_DESIGNER_STATE = useDesignerStore.getState();
const INITIAL_TRAY_STATE = useTrayStore.getState();

afterEach(() => {
  useDesignerStore.setState(INITIAL_DESIGNER_STATE, true);
  useTrayStore.setState(INITIAL_TRAY_STATE, true);
});

describe("App routing (task 2.13)", () => {
  it("the primary nav links navigate between Design/Presets/History and mark the active route with aria-current", async () => {
    const user = userEvent.setup();
    render(<App />);

    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(await within(nav).findByRole("link", { name: "Design" })).toHaveAttribute("aria-current", "page");

    // The Home placeholder is a disabled, non-interactive stand-in for a
    // future landing page (Phase 3) -- never a link at all.
    expect(within(nav).queryByRole("link", { name: "Home" })).not.toBeInTheDocument();
    expect(within(nav).getByText("Home")).toHaveAttribute("aria-disabled", "true");

    await user.click(within(nav).getByRole("link", { name: "Presets" }));
    expect(await screen.findByRole("heading", { name: "Presets" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Presets" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Design" })).not.toHaveAttribute("aria-current");

    await user.click(within(nav).getByRole("link", { name: "History" }));
    expect(await screen.findByRole("heading", { name: "History" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "History" })).toHaveAttribute("aria-current", "page");

    await user.click(within(nav).getByRole("link", { name: "Design" }));
    expect(await screen.findByRole("heading", { name: "Text" })).toBeInTheDocument();
  });

  it("Designer state (the module-level store) survives a round trip through Presets/History", async () => {
    const user = userEvent.setup();
    render(<App />);

    const linesInput = await screen.findByLabelText("Lines 1");
    await user.type(linesInput, "PORT 12");
    await waitFor(() => expect(useDesignerStore.getState().paramsByType.text?.lines).toEqual(["PORT 12"]));

    const nav = screen.getByRole("navigation", { name: "Sections" });
    await user.click(within(nav).getByRole("link", { name: "History" }));
    expect(await screen.findByRole("heading", { name: "History" })).toBeInTheDocument();

    await user.click(within(nav).getByRole("link", { name: "Design" }));
    expect(await screen.findByLabelText("Lines 1")).toHaveValue("PORT 12");
  });
});
