import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, imagePngUrl, postImage } from "../../api/client";
import type { Icon } from "../../api/types";
import { SegmentedControl } from "../ui/SegmentedControl";
import { Pending } from "../ui/Pending";
import { NumberInput } from "../ui/inputs";
import { errorText, fieldLabelText, helpText, segmentedButtonClass } from "../ui/styles";
import { SymbolBrowser } from "../symbols/SymbolBrowser";
import type { OverrideFieldProps } from "./types";

type IconMode = "none" | "symbol" | "image";

/** "text" type's `icon` field (task 2.7's leading-art discriminated union)
 * -- not schema-walked generically (a discriminator union is one shape too
 * bespoke to earn a generic renderer for a single field across one type),
 * a bespoke picker instead: symbol grid (searchable by tag, from GET
 * /api/symbols) or image upload (POST /api/images) with a thumbnail and a
 * clear affordance, per the task brief. */
export function IconField({ value, onChange }: OverrideFieldProps) {
  const icon = (value ?? null) as Icon | null;
  // While `icon` is null, which picker to SHOW is UI-only state -- switching
  // to the "Symbol" or "Image" tab must never itself write a half-formed
  // Icon (e.g. `{kind: "symbol", id: ""}`) into params, since that's a
  // value the backend would 422 on if a preview/print fired before the user
  // actually picked something. Once `icon` is non-null, its own `.kind` is
  // authoritative (a real, valid value) and this local state stops mattering.
  const [pendingMode, setPendingMode] = useState<IconMode>("none");
  const mode: IconMode = icon ? icon.kind : pendingMode;

  function setMode(next: IconMode) {
    if (next === "none") onChange(null);
    setPendingMode(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <span className={`${fieldLabelText} mb-1 block`}>Icon</span>
      <SegmentedControl
        ariaLabel="Icon mode"
        value={mode}
        options={[
          { value: "none", label: "None" },
          { value: "symbol", label: "Symbol" },
          { value: "image", label: "Image" },
        ]}
        onChange={setMode}
      />
      <p className={helpText}>
        Optional leading art at the left of the text, sized to the full print height.
      </p>
      {mode === "symbol" && (
        <SymbolPicker
          selectedId={icon?.kind === "symbol" ? icon.id : null}
          onSelect={(id) => onChange({ kind: "symbol", id } satisfies Icon)}
          onClear={() => onChange(null)}
        />
      )}
      {mode === "image" && (
        <ImagePicker
          icon={icon?.kind === "image" ? icon : null}
          onChange={(next) => onChange(next)}
          onClear={() => onChange(null)}
        />
      )}
    </div>
  );
}

interface SymbolPickerProps {
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Clears the icon back to `null` -- the selected chip's own affordance
   * for deselecting without leaving the "Symbol" tab (parallels
   * ImagePicker's "Clear image" button below). */
  onClear: () => void;
}

/** Thin wrapper around the shared symbols/SymbolBrowser grid in "select"
 * mode -- the windowing/search/category machinery (and, soon, a
 * browse-only Library page) lives there now; this just adapts its
 * selectedId/onSelect/onClear contract to IconField's own Icon value. */
function SymbolPicker({ selectedId, onSelect, onClear }: SymbolPickerProps) {
  return <SymbolBrowser mode="select" selectedId={selectedId} onSelect={onSelect} onClear={onClear} />;
}

interface ImagePickerProps {
  icon: Extract<Icon, { kind: "image" }> | null;
  onChange: (icon: Icon) => void;
  onClear: () => void;
}

function ImagePicker({ icon, onChange, onClear }: ImagePickerProps) {
  const upload = useMutation({
    mutationFn: postImage,
    onSuccess: (result) => onChange({ kind: "image", image_id: result.image_id, mode: "threshold", threshold: 128 }),
  });

  if (!icon) {
    return (
      <div className="flex flex-col gap-1.5">
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          aria-label="Upload image"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
            e.target.value = "";
          }}
          className="text-[12px] text-deck-400 file:mr-3 file:rounded-md file:border file:border-deck-600 file:bg-deck-800 file:px-3 file:py-1.5 file:text-deck-200"
        />
        {upload.isPending && <Pending />}
        {upload.isError && (
          <p role="alert" className={errorText}>
            {upload.error instanceof ApiError ? upload.error.message : "image upload failed"}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3">
      <img
        src={imagePngUrl(icon.image_id)}
        alt="Uploaded icon"
        className="h-16 w-16 shrink-0 rounded-md border border-deck-600 bg-icon-well object-contain p-1"
      />
      <div className="flex flex-1 flex-col gap-2">
        <div role="radiogroup" aria-label="Image mode" className="flex gap-1.5">
          {(["threshold", "dither"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={icon.mode === m}
              onClick={() => onChange({ ...icon, mode: m })}
              className={segmentedButtonClass(icon.mode === m)}
            >
              {m === "threshold" ? "Threshold" : "Dither"}
            </button>
          ))}
        </div>
        {icon.mode === "threshold" && (
          <label className="flex items-center gap-2 text-[12px] text-deck-400">
            Threshold
            <NumberInput
              value={icon.threshold}
              min={0}
              max={255}
              step={1}
              ariaLabel="Threshold"
              // A cleared/invalid threshold has no top-level schema-driven
              // safety net (icon's discriminated union is opaque to
              // hasNumberOutOfRange, see numberValidity.ts's own docstring)
              // -- no-op instead of ever writing a NaN-ish threshold into
              // params; the field's own local text buffer (NumberInput)
              // still shows whatever the user is mid-typing.
              onChange={(v) => {
                if (v === undefined) return;
                onChange({ ...icon, threshold: Math.round(v) });
              }}
              className="w-20 rounded-md border border-deck-600 bg-deck-800 px-2 py-1 font-mono text-[13px] text-deck-200"
            />
          </label>
        )}
        <button type="button" onClick={onClear} className="self-start text-[12px] text-deck-400 underline hover:text-deck-200">
          Clear image
        </button>
      </div>
    </div>
  );
}
