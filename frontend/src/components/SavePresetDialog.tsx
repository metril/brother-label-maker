import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, postPreset } from "../api/client";
import { useDialogController } from "../hooks/useDialogController";
import { Checkbox, TextInput } from "./ui/inputs";
import { Dialog } from "./ui/Dialog";
import { dashedAddButtonClass, errorText, fieldLabelText, iconButtonClass, primaryButtonClass } from "./ui/styles";
import type { Tape } from "../api/types";

interface SavePresetDialogProps {
  labelType: string;
  labelTypeTitle: string;
  /** The active type's own params (stores/designer.ts's paramsByType) -- a
   * preset's `definition` is PARAMS ONLY, never a full LabelDefinition
   * (api/router_presets.py's own docstring). */
  params: Record<string, unknown>;
  tape: Tape;
  disabled: boolean;
}

/** "Save current design as preset" (task 2.13's brief): a small dialog
 * triggered from a button placed near the Job tray -- posts the CURRENT
 * type's own params as the preset's `definition`, plus the current tape's
 * width/family (a saved preset always pins the tape it was captured at;
 * clearing that back to "any tape" is an edit made later from the Presets
 * page, not something this dialog offers). Self-contained: owns its own
 * open/close state (useDialogController, the JobTray-mobile-sheet focus
 * pattern) and its own create-preset mutation -- mounting it in
 * Designer.tsx is the entire integration cost. */
export function SavePresetDialog({ labelType, labelTypeTitle, params, tape, disabled }: SavePresetDialogProps) {
  const dialog = useDialogController();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [favorite, setFavorite] = useState(false);

  const save = useMutation({
    mutationFn: () =>
      postPreset({
        name: name.trim(),
        label_type: labelType,
        definition: params,
        tape_width_mm: tape.width_mm,
        tape_family: tape.family,
        favorite,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["presets"] });
    },
  });

  function openDialog() {
    setName("");
    setFavorite(false);
    save.reset();
    dialog.open();
  }

  function handleClose() {
    save.reset();
    dialog.close();
  }

  return (
    <>
      <button type="button" onClick={openDialog} disabled={disabled} className={dashedAddButtonClass}>
        + Save as preset
      </button>
      <Dialog open={dialog.isOpen} onClose={handleClose} label="Save as preset">
        <div className="flex items-center justify-between gap-2">
          <span className="font-condensed text-[13px] uppercase tracking-wide text-deck-400">Save as preset</span>
          <button
            type="button"
            ref={dialog.closeButtonRef}
            onClick={handleClose}
            aria-label="Close save preset dialog"
            className={iconButtonClass}
          >
            ×
          </button>
        </div>

        {save.isSuccess ? (
          <div className="mt-4 flex flex-col gap-3">
            <p role="status" className="text-[13px] text-sage-400">
              Saved &quot;{save.data.name}&quot; as a preset.
            </p>
            <Link to="/presets" onClick={handleClose} className="text-[13px] font-medium text-amber-300 underline hover:text-amber-500">
              View in Presets
            </Link>
            <button type="button" onClick={handleClose} className="self-start text-[12px] text-deck-400 hover:text-deck-200">
              Done
            </button>
          </div>
        ) : (
          <form
            className="mt-4 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim() === "") return;
              save.mutate();
            }}
          >
            <p className="text-[12px] text-deck-400">
              Saves this {labelTypeTitle.toLowerCase()} design at {tape.width_mm}mm so you can reuse it without rebuilding it.
            </p>
            <div>
              <label htmlFor="preset-name" className={`${fieldLabelText} mb-1 block`}>
                Name
              </label>
              <TextInput id="preset-name" value={name} onChange={setName} placeholder="e.g. Rack uplink label" maxLength={80} />
            </div>
            <Checkbox id="preset-favorite" checked={favorite} onChange={setFavorite} label="Favorite" />
            {save.isError && (
              <p role="alert" className={errorText}>
                {save.error instanceof ApiError ? save.error.message : "could not save preset"}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={handleClose}
                className="rounded-md border border-deck-600 bg-deck-800 px-4 py-2 text-[13px] font-medium text-deck-200 hover:border-deck-400"
              >
                Cancel
              </button>
              <button type="submit" disabled={name.trim() === "" || save.isPending} className={primaryButtonClass}>
                {save.isPending ? "Saving…" : "Save preset"}
              </button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}
