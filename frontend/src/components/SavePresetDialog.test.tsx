import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { SavePresetDialog } from "./SavePresetDialog";
import { renderWithProviders } from "../test/utils";
import { server } from "../test/msw/server";

function renderDialog(overrides: Partial<Parameters<typeof SavePresetDialog>[0]> = {}) {
  return renderWithProviders(
    <SavePresetDialog
      labelType="text"
      labelTypeTitle="Text"
      params={{ lines: ["PORT 1"] }}
      tape={{ width_mm: 24, family: "tze" }}
      disabled={false}
      {...overrides}
    />,
  );
}

describe("SavePresetDialog", () => {
  it("is disabled when the current design isn't submittable", () => {
    renderDialog({ disabled: true });
    expect(screen.getByRole("button", { name: "+ Save as preset" })).toBeDisabled();
  });

  it("opens as a dialog with focus management (JobTray mobile-sheet pattern) and posts a params-only definition + tape fields", async () => {
    const user = userEvent.setup();
    let capturedBody: Record<string, unknown> | undefined;
    server.use(
      http.post("/api/presets", async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: "preset-1",
            name: capturedBody.name,
            label_type: capturedBody.label_type,
            definition: capturedBody.definition,
            tape_width_mm: capturedBody.tape_width_mm,
            tape_family: capturedBody.tape_family,
            favorite: capturedBody.favorite,
            created_at: "2026-07-27T00:00:00.000000Z",
            updated_at: "2026-07-27T00:00:00.000000Z",
          },
          { status: 201 },
        );
      }),
    );
    renderDialog();

    const trigger = screen.getByRole("button", { name: "+ Save as preset" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Save as preset" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const closeButton = screen.getByRole("button", { name: "Close save preset dialog" });
    await waitFor(() => expect(closeButton).toHaveFocus());

    await user.type(screen.getByLabelText("Name"), "Rack uplink");
    await user.click(screen.getByRole("checkbox", { name: "Favorite" }));
    await user.click(screen.getByRole("button", { name: "Save preset" }));

    await waitFor(() =>
      expect(capturedBody).toEqual({
        name: "Rack uplink",
        label_type: "text",
        definition: { lines: ["PORT 1"] },
        tape_width_mm: 24,
        tape_family: "tze",
        favorite: true,
      }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent('Saved "Rack uplink" as a preset.');
    expect(screen.getByRole("link", { name: "View in Presets" })).toHaveAttribute("href", "/presets");

    // Closing (Done) restores focus to the trigger button.
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  // Task 4.3: the API has always supported an "any tape" preset
  // (tape_width_mm: null, PresetCard already renders/prints those), but
  // this dialog had no way to CREATE one. Unchecked by default (a pinned
  // tape is the common case) -- checking it sends `tape_width_mm: null`
  // while still sending `tape_family` (not nullable server-side).
  it('checking "Any tape" posts tape_width_mm: null while still sending tape_family', async () => {
    const user = userEvent.setup();
    let capturedBody: Record<string, unknown> | undefined;
    server.use(
      http.post("/api/presets", async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: "preset-1",
            name: capturedBody.name,
            label_type: capturedBody.label_type,
            definition: capturedBody.definition,
            tape_width_mm: capturedBody.tape_width_mm,
            tape_family: capturedBody.tape_family,
            favorite: capturedBody.favorite,
            created_at: "2026-07-27T00:00:00.000000Z",
            updated_at: "2026-07-27T00:00:00.000000Z",
          },
          { status: 201 },
        );
      }),
    );
    renderDialog();

    await user.click(screen.getByRole("button", { name: "+ Save as preset" }));
    await user.type(screen.getByLabelText("Name"), "Rack uplink");

    const anyTapeCheckbox = screen.getByRole("checkbox", { name: "Any tape (don't pin a width)" });
    expect(anyTapeCheckbox).not.toBeChecked();
    // Switching it on updates the dialog's own help copy too -- the same
    // "say what's about to happen" convention the rest of this dialog's
    // description line already follows.
    expect(screen.getByText(/Saves this text design at 24mm/)).toBeInTheDocument();
    await user.click(anyTapeCheckbox);
    expect(screen.getByText(/without pinning it to a tape width/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save preset" }));

    await waitFor(() =>
      expect(capturedBody).toEqual({
        name: "Rack uplink",
        label_type: "text",
        definition: { lines: ["PORT 1"] },
        tape_width_mm: null,
        tape_family: "tze",
        favorite: false,
      }),
    );
  });

  it("Escape closes the dialog without saving", async () => {
    const user = userEvent.setup();
    let posted = false;
    server.use(
      http.post("/api/presets", () => {
        posted = true;
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    renderDialog();

    await user.click(screen.getByRole("button", { name: "+ Save as preset" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posted).toBe(false);
  });
});
