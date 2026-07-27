import type { ChangeEvent } from "react";
import { MAX_LINES, MIN_LINES, useDesignerStore } from "../stores/designer";
import { useFonts } from "../hooks/useFonts";
import type { HAlign } from "../api/types";

const H_ALIGN_OPTIONS: { value: HAlign; label: string }[] = [
  { value: "left", label: "Left" },
  { value: "center", label: "Center" },
  { value: "right", label: "Right" },
];

const fieldLabel = "mb-1 block text-xs font-medium uppercase tracking-wide text-ink-400";
const textInput =
  "w-full rounded-md border border-ink-600 bg-ink-800 px-3 py-1.5 text-sm text-ink-100 placeholder:text-ink-500 focus:border-amber-500 focus:outline-none";

export function TextLabelForm() {
  const { data: fonts, isPending: fontsPending } = useFonts();
  const params = useDesignerStore((s) => s.params);
  const setLine = useDesignerStore((s) => s.setLine);
  const addLine = useDesignerStore((s) => s.addLine);
  const removeLine = useDesignerStore((s) => s.removeLine);
  const setFontFamily = useDesignerStore((s) => s.setFontFamily);
  const setBold = useDesignerStore((s) => s.setBold);
  const setFontSizeMode = useDesignerStore((s) => s.setFontSizeMode);
  const setFontSizePx = useDesignerStore((s) => s.setFontSizePx);
  const setHAlign = useDesignerStore((s) => s.setHAlign);
  const setLengthMode = useDesignerStore((s) => s.setLengthMode);
  const setLengthMm = useDesignerStore((s) => s.setLengthMm);
  const setPaddingMm = useDesignerStore((s) => s.setPaddingMm);

  const sizeMode: "auto" | "manual" = params.font_size_px === null ? "auto" : "manual";
  const lengthMode: "auto" | "manual" = params.length_mm === null ? "auto" : "manual";

  return (
    <form className="flex flex-col gap-5" onSubmit={(e) => e.preventDefault()}>
      <fieldset className="flex flex-col gap-2">
        <legend className={fieldLabel}>Lines ({params.lines.length}/{MAX_LINES})</legend>
        {params.lines.map((line, index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              type="text"
              value={line}
              placeholder={`Line ${index + 1}`}
              aria-label={`Line ${index + 1}`}
              maxLength={200}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setLine(index, e.target.value)}
              className={textInput}
            />
            {params.lines.length > MIN_LINES && (
              <button
                type="button"
                aria-label={`Remove line ${index + 1}`}
                onClick={() => removeLine(index)}
                className="shrink-0 rounded-md border border-ink-600 px-2 py-1.5 text-xs text-ink-300 hover:border-ink-500 hover:text-ink-100"
              >
                Remove
              </button>
            )}
          </div>
        ))}
        {params.lines.length < MAX_LINES && (
          <button
            type="button"
            onClick={addLine}
            className="self-start rounded-md border border-dashed border-ink-600 px-3 py-1 text-xs font-medium text-ink-300 hover:border-amber-500 hover:text-amber-300"
          >
            + Add line
          </button>
        )}
      </fieldset>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={fieldLabel} htmlFor="font-family">
            Font
          </label>
          {fontsPending || !fonts ? (
            <select
              id="font-family"
              disabled
              aria-label="Loading fonts"
              className={`${textInput} shimmer`}
            >
              <option>Loading…</option>
            </select>
          ) : (
            <select
              id="font-family"
              value={params.font_family}
              onChange={(e) => setFontFamily(e.target.value)}
              className={textInput}
            >
              {fonts.map((font) => (
                <option key={font.family} value={font.family}>
                  {font.display_name}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="flex items-end pb-1.5">
          <label className="flex items-center gap-2 text-sm text-ink-200">
            <input
              type="checkbox"
              checked={params.bold}
              onChange={(e) => setBold(e.target.checked)}
              className="h-4 w-4 rounded border-ink-600 bg-ink-800 accent-amber-500"
            />
            Bold
          </label>
        </div>
      </div>

      <div>
        <span className={fieldLabel}>Alignment</span>
        <div role="radiogroup" aria-label="Horizontal alignment" className="flex gap-2">
          {H_ALIGN_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={params.h_align === opt.value}
              onClick={() => setHAlign(opt.value)}
              className={`rounded-md border px-3 py-1 text-sm ${
                params.h_align === opt.value
                  ? "border-amber-500 bg-amber-950 text-amber-300"
                  : "border-ink-600 bg-ink-800 text-ink-200 hover:border-ink-500"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <span className={fieldLabel}>Font size</span>
        <div className="flex items-center gap-3">
          <div role="radiogroup" aria-label="Font size mode" className="flex gap-2">
            <button
              type="button"
              role="radio"
              aria-checked={sizeMode === "auto"}
              onClick={() => setFontSizeMode("auto")}
              className={`rounded-md border px-3 py-1 text-sm ${
                sizeMode === "auto"
                  ? "border-amber-500 bg-amber-950 text-amber-300"
                  : "border-ink-600 bg-ink-800 text-ink-200"
              }`}
            >
              Auto
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={sizeMode === "manual"}
              onClick={() => setFontSizeMode("manual")}
              className={`rounded-md border px-3 py-1 text-sm ${
                sizeMode === "manual"
                  ? "border-amber-500 bg-amber-950 text-amber-300"
                  : "border-ink-600 bg-ink-800 text-ink-200"
              }`}
            >
              Manual
            </button>
          </div>
          {sizeMode === "manual" && (
            <input
              type="number"
              aria-label="Font size in pixels"
              min={6}
              max={128}
              value={params.font_size_px ?? 24}
              onChange={(e) => setFontSizePx(Number(e.target.value))}
              className={`${textInput} w-24`}
            />
          )}
        </div>
      </div>

      <div>
        <span className={fieldLabel}>Label length</span>
        <div className="flex items-center gap-3">
          <div role="radiogroup" aria-label="Length mode" className="flex gap-2">
            <button
              type="button"
              role="radio"
              aria-checked={lengthMode === "auto"}
              onClick={() => setLengthMode("auto")}
              className={`rounded-md border px-3 py-1 text-sm ${
                lengthMode === "auto"
                  ? "border-amber-500 bg-amber-950 text-amber-300"
                  : "border-ink-600 bg-ink-800 text-ink-200"
              }`}
            >
              Auto
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={lengthMode === "manual"}
              onClick={() => setLengthMode("manual")}
              className={`rounded-md border px-3 py-1 text-sm ${
                lengthMode === "manual"
                  ? "border-amber-500 bg-amber-950 text-amber-300"
                  : "border-ink-600 bg-ink-800 text-ink-200"
              }`}
            >
              Manual
            </button>
          </div>
          {lengthMode === "manual" && (
            <input
              type="number"
              aria-label="Label length in millimeters"
              min={4.4}
              step={0.1}
              value={params.length_mm ?? 40}
              onChange={(e) => setLengthMm(Number(e.target.value))}
              className={`${textInput} w-24`}
            />
          )}
        </div>
      </div>

      <div>
        <label className={fieldLabel} htmlFor="padding-mm">
          Padding (mm)
        </label>
        <input
          id="padding-mm"
          type="number"
          min={0}
          step={0.5}
          value={params.padding_mm}
          onChange={(e) => setPaddingMm(Number(e.target.value))}
          className={`${textInput} w-24`}
        />
      </div>
    </form>
  );
}
