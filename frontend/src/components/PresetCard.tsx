import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError, deletePreset, postPresetPrint, putPreset } from "../api/client";
import { useDialogController } from "../hooks/useDialogController";
import { useJobEvent } from "../hooks/useJobEvents";
import { useLabelTypes } from "../hooks/useLabelTypes";
import { formatAbsoluteTime, formatRelativeTime } from "../lib/time";
import { humanizeEnumValue } from "../schema/humanize";
import { statusFromEvent } from "../lib/jobStatus";
import { useDesignerStore } from "../stores/designer";
import { useTrayStore } from "../stores/tray";
import { ConfirmDialog } from "./ConfirmDialog";
import { StatusChip } from "./StatusChip";
import { Dialog } from "./ui/Dialog";
import { TextInput } from "./ui/inputs";
import { errorText, fieldLabelText, iconButtonClass, primaryButtonClass } from "./ui/styles";
import type { Preset } from "../api/types";

interface PresetCardProps {
  preset: Preset;
  typeTitle: string;
}

/** One saved preset (task 2.13's Presets page): name/favorite, its type +
 * tape, when it last changed, and the four actions the brief calls for
 * (Duplicate is explicitly optional there and skipped here to keep this
 * component's already-wide surface in check). Self-contained -- reads/
 * writes the designer + tray stores and owns its own rename/delete dialogs
 * and print mutation directly, the same "mounting it is the entire
 * integration cost" convention SequenceCsvUpload.tsx/IconField.tsx use. */
export function PresetCard({ preset, typeTitle }: PresetCardProps) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: labelTypes } = useLabelTypes();

  const selectType = useDesignerStore((s) => s.selectType);
  const setParams = useDesignerStore((s) => s.setParams);
  const setTapeWidthMm = useDesignerStore((s) => s.setTapeWidthMm);
  const setTapeFamily = useDesignerStore((s) => s.setTapeFamily);
  const currentTape = useDesignerStore((s) => s.tape);
  const chainMode = useTrayStore((s) => s.chainMode);
  const autoCut = useTrayStore((s) => s.autoCut);

  const renameDialog = useDialogController();
  const deleteDialog = useDialogController();
  const [renameValue, setRenameValue] = useState(preset.name);
  const [printJobId, setPrintJobId] = useState<string | null>(null);
  const printEvent = useJobEvent(printJobId);

  function invalidatePresets() {
    queryClient.invalidateQueries({ queryKey: ["presets"] });
  }

  const favoriteMutation = useMutation({
    mutationFn: () => putPreset(preset.id, { favorite: !preset.favorite }),
    onSuccess: invalidatePresets,
  });

  const renameMutation = useMutation({
    mutationFn: (name: string) => putPreset(preset.id, { name }),
    onSuccess: () => {
      invalidatePresets();
      renameDialog.close();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deletePreset(preset.id),
    onSuccess: () => {
      invalidatePresets();
      deleteDialog.close();
    },
  });

  // Review-anticipated fix-up: "for an 'any tape' preset, send the
  // designer's current tape in the body" (brief) -- POST .../print falls
  // back to the preset's OWN tape_width_mm/tape_family only when the body
  // supplies none, and 422s if BOTH are absent (see router_presets.py's
  // print_preset docstring), so a null tape_width_mm preset needs an
  // explicit `tape` here or printing it would always fail.
  const printMutation = useMutation({
    mutationFn: () =>
      postPresetPrint(preset.id, {
        options: { chain_mode: chainMode, margin_mm: 2.0, auto_cut: autoCut },
        tape: preset.tape_width_mm == null ? currentTape : undefined,
      }),
    onSuccess: (data) => setPrintJobId(data.job_id),
  });

  function handleLoad() {
    const typeInfo = labelTypes?.find((t) => t.type === preset.label_type);
    if (typeInfo) {
      // Seeds defaults only the FIRST time this type is visited this
      // session (stores/designer.ts's own selectType) -- the setParams
      // call right after always overwrites with the preset's own saved
      // definition either way, so this is safe regardless of whether the
      // type was already visited.
      selectType(preset.label_type, typeInfo.params_schema);
    }
    setParams(preset.label_type, preset.definition);
    // "any tape" presets (tape_width_mm null) carry no tape opinion --
    // leave the designer's current tape selection alone rather than
    // forcing preset.tape_family onto an unrelated width.
    if (preset.tape_width_mm != null) {
      setTapeFamily(preset.tape_family);
      setTapeWidthMm(preset.tape_width_mm);
    }
    navigate("/");
  }

  const tapeLabel =
    preset.tape_width_mm != null ? `${preset.tape_width_mm}mm ${humanizeEnumValue(preset.tape_family)}` : "Any tape";
  const printStatus = printEvent ? statusFromEvent(printEvent.event) : null;

  return (
    <li className="flex flex-col gap-3 rounded-xl border border-deck-800 bg-deck-900/60 p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className="min-w-0 flex-1 truncate font-condensed text-[16px] font-semibold text-deck-200" title={preset.name}>
          {preset.name}
        </h3>
        <button
          type="button"
          aria-pressed={preset.favorite}
          aria-label={preset.favorite ? `Unmark ${preset.name} as favorite` : `Mark ${preset.name} as favorite`}
          onClick={() => favoriteMutation.mutate()}
          disabled={favoriteMutation.isPending}
          className={`shrink-0 text-[18px] leading-none disabled:opacity-50 ${preset.favorite ? "text-amber-300" : "text-deck-600 hover:text-deck-400"}`}
        >
          {preset.favorite ? "★" : "☆"}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded border border-deck-600 px-1.5 py-0.5 font-condensed text-[10px] uppercase tracking-wide text-deck-400">
          {typeTitle}
        </span>
        <span className="font-mono text-[11px] text-deck-400">{tapeLabel}</span>
      </div>

      <p className="font-mono text-[11px] text-deck-400" title={formatAbsoluteTime(preset.updated_at)}>
        Updated {formatRelativeTime(preset.updated_at)}
      </p>

      <div className="mt-1 flex flex-wrap items-center gap-3">
        <button type="button" onClick={handleLoad} className="text-[12px] font-medium text-amber-300 hover:underline">
          Load
        </button>
        <button
          type="button"
          onClick={() => printMutation.mutate()}
          disabled={printMutation.isPending}
          className="text-[12px] font-medium text-amber-300 hover:underline disabled:opacity-50"
        >
          Print
        </button>
        <button
          type="button"
          onClick={() => {
            setRenameValue(preset.name);
            renameDialog.open();
          }}
          className="text-[12px] font-medium text-deck-200 hover:underline"
        >
          Rename
        </button>
        <button type="button" onClick={deleteDialog.open} className="text-[12px] font-medium text-rust-500 hover:underline">
          Delete
        </button>
      </div>

      {printMutation.isError && (
        <p role="alert" className={errorText}>
          {printMutation.error instanceof ApiError ? printMutation.error.message : "print failed"}
        </p>
      )}
      {printStatus && <StatusChip status={printStatus} className="self-start" />}

      <Dialog open={renameDialog.isOpen} onClose={renameDialog.close} label={`Rename ${preset.name}`}>
        <div className="flex items-center justify-between gap-2">
          <span className="font-condensed text-[13px] uppercase tracking-wide text-deck-400">Rename preset</span>
          <button
            type="button"
            ref={renameDialog.closeButtonRef}
            onClick={renameDialog.close}
            aria-label="Close rename dialog"
            className={iconButtonClass}
          >
            ×
          </button>
        </div>
        <form
          className="mt-4 flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (renameValue.trim() === "") return;
            renameMutation.mutate(renameValue.trim());
          }}
        >
          <div>
            <label htmlFor={`rename-${preset.id}`} className={`${fieldLabelText} mb-1 block`}>
              Name
            </label>
            <TextInput id={`rename-${preset.id}`} value={renameValue} onChange={setRenameValue} maxLength={80} />
          </div>
          {renameMutation.isError && (
            <p role="alert" className={errorText}>
              {renameMutation.error instanceof ApiError ? renameMutation.error.message : "rename failed"}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={renameDialog.close}
              className="rounded-md border border-deck-600 bg-deck-800 px-4 py-2 text-[13px] font-medium text-deck-200 hover:border-deck-400"
            >
              Cancel
            </button>
            <button type="submit" disabled={renameValue.trim() === "" || renameMutation.isPending} className={primaryButtonClass}>
              {renameMutation.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </Dialog>

      <ConfirmDialog
        open={deleteDialog.isOpen}
        onClose={deleteDialog.close}
        closeButtonRef={deleteDialog.closeButtonRef}
        label={`Delete ${preset.name}?`}
        message={`Delete "${preset.name}"? This can't be undone.`}
        confirmLabel="Delete"
        isPending={deleteMutation.isPending}
        error={deleteMutation.isError ? (deleteMutation.error instanceof ApiError ? deleteMutation.error.message : "delete failed") : null}
        onConfirm={() => deleteMutation.mutate()}
      />
    </li>
  );
}
