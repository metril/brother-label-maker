// Shared className fragments for the design system (task 2.10) -- warm
// graphite palette, Roboto Condensed for headings/nav/eyebrows, Inter for
// body/labels, JetBrains Mono for every measurement/machine value. See
// .superpowers/sdd/we-re-going-to-build-eager-cloud/frontend-design-system.md.

export const eyebrow = "font-condensed uppercase tracking-[0.12em] text-[11px] text-deck-400";

export const panel = "rounded-xl border border-deck-800 bg-deck-900/60 p-5";
export const panelHeading = `${eyebrow} mb-4`;

/** The active label type's own name (e.g. "Text", "Barcode") -- the single
 * most important piece of context on the page, so it gets the type scale's
 * top step (28px) instead of blending in with eyebrow-sized section labels
 * like "Parameters"/"Job". Condensed + tight leading per the design doc's
 * "Headings are condensed and tight" rule. */
export const typeHeading = "font-condensed text-[28px] font-bold uppercase leading-tight tracking-wide text-deck-100";

export const fieldLabelText = "block text-[13px] font-medium text-deck-200";
export const helpText = "mt-1 text-[12px] leading-snug text-deck-400";
export const errorText = "mt-1 text-[12px] text-rust-500";

export const inputBase =
  "w-full rounded-md border border-deck-600 bg-deck-800 px-3 py-1.5 text-[14px] text-deck-200 placeholder:text-deck-400 disabled:cursor-not-allowed disabled:opacity-60";

export const numberInputClass = `${inputBase} font-mono`;
export const textInputClass = inputBase;
export const selectClass = `${inputBase} appearance-none`;

export function segmentedButtonClass(selected: boolean): string {
  return `rounded-md border px-3 py-1.5 text-[13px] font-medium transition-colors ${
    selected
      ? "border-amber-500 bg-amber-500/15 text-amber-300"
      : "border-deck-600 bg-deck-800 text-deck-200 hover:border-deck-400 hover:text-deck-200"
  }`;
}

export const indexBadge =
  "flex h-6 w-6 shrink-0 items-center justify-center rounded font-mono text-[11px] text-deck-400";

export const iconButtonClass =
  "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-deck-600 bg-deck-800 text-deck-200 hover:border-deck-400 hover:text-deck-100 disabled:cursor-not-allowed disabled:opacity-40";

export const dashedAddButtonClass =
  "self-start rounded-md border border-dashed border-deck-600 px-3 py-1 text-[12px] font-medium text-deck-200 hover:border-amber-500 hover:text-amber-300";

export const primaryButtonClass =
  "rounded-md border border-amber-500 bg-amber-500 px-5 py-2 text-[14px] font-semibold text-deck-950 transition-colors hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60";
