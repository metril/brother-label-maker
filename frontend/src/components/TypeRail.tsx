import { useRef } from "react";
import type { LabelTypeInfo } from "../api/types";
import { useLabelTypes } from "../hooks/useLabelTypes";
import { useDesignerStore } from "../stores/designer";
import { Pending } from "./ui/Pending";
import { eyebrow } from "./ui/styles";

const CATEGORY_ORDER = ["general", "network", "electrical"];
const CATEGORY_LABELS: Record<string, string> = {
  general: "General",
  network: "Network",
  electrical: "Electrical",
};

function groupByCategory(types: LabelTypeInfo[]): [string, LabelTypeInfo[]][] {
  const groups = new Map<string, LabelTypeInfo[]>();
  for (const type of types) {
    const list = groups.get(type.category) ?? [];
    list.push(type);
    groups.set(type.category, list);
  }
  const orderedKeys = [...CATEGORY_ORDER.filter((c) => groups.has(c)), ...[...groups.keys()].filter((c) => !CATEGORY_ORDER.includes(c))];
  return orderedKeys.map((key) => [key, groups.get(key)!]);
}

/** The design system's left rail: the 9 label types from GET /api/label-
 * types, grouped by category, driving useDesignerStore's selectedType. A
 * roving-tabindex listbox -- ArrowUp/ArrowDown move focus across the WHOLE
 * flattened list (category grouping is visual only), Enter/Space activates
 * a focused button natively (no extra keydown handling needed for that
 * part). Mobile: a horizontal scroller (design doc's layout note) instead
 * of a vertical column. */
export function TypeRail() {
  const { data: types, isPending } = useLabelTypes();
  const selectedType = useDesignerStore((s) => s.selectedType);
  const selectType = useDesignerStore((s) => s.selectType);
  const buttonRefs = useRef(new Map<string, HTMLButtonElement>());

  // Auto-selecting a first type on load is Designer's own job (it owns the
  // "nothing selected yet" bootstrap effect, see Designer.tsx) -- not
  // this rail's, so a test (or any future consumer) that renders Designer
  // standalone, without this rail mounted alongside it, still works.

  if (isPending || !types) {
    return (
      <nav aria-label="Label types" className="w-full shrink-0 border-b border-deck-800 p-3 lg:w-56 lg:border-b-0 lg:border-r">
        <Pending />
      </nav>
    );
  }

  const groups = groupByCategory(types);
  const activeType = selectedType ?? types[0]?.type ?? null;

  function focusByIndex(index: number) {
    const target = types![(index + types!.length) % types!.length];
    buttonRefs.current.get(target.type)?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent, index: number) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "ArrowRight" && event.key !== "ArrowLeft") {
      return;
    }
    event.preventDefault();
    const forward = event.key === "ArrowDown" || event.key === "ArrowRight";
    focusByIndex(index + (forward ? 1 : -1));
  }

  return (
    <nav
      aria-label="Label types"
      className="flex w-full shrink-0 flex-row gap-4 overflow-x-auto border-b border-deck-800 bg-deck-900/40 p-3 lg:w-56 lg:flex-col lg:gap-5 lg:overflow-x-visible lg:overflow-y-auto lg:border-b-0 lg:border-r"
    >
      {groups.map(([category, categoryTypes]) => (
        <div key={category} className="flex flex-row items-center gap-2 lg:flex-col lg:items-stretch lg:gap-1">
          <p className={`${eyebrow} hidden shrink-0 lg:block`}>{CATEGORY_LABELS[category] ?? category}</p>
          <div role="group" aria-label={`${CATEGORY_LABELS[category] ?? category} label types`} className="flex flex-row gap-1 lg:flex-col">
            {categoryTypes.map((type) => {
              const index = types.indexOf(type);
              const active = type.type === activeType;
              return (
                <button
                  key={type.type}
                  ref={(el) => {
                    if (el) buttonRefs.current.set(type.type, el);
                    else buttonRefs.current.delete(type.type);
                  }}
                  type="button"
                  aria-current={active ? "true" : undefined}
                  tabIndex={active ? 0 : -1}
                  onClick={() => selectType(type.type, type.params_schema)}
                  onKeyDown={(e) => handleKeyDown(e, index)}
                  className={`whitespace-nowrap rounded-md px-3 py-2 text-left font-condensed text-[14px] font-medium transition-colors ${
                    active ? "bg-amber-500/15 text-amber-300" : "text-deck-200 hover:bg-deck-800"
                  }`}
                >
                  {type.title}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}
