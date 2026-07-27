import { createContext, useContext } from "react";

/** The DOM id (matches a RenderWarning's `object_id`, e.g. "block-2") that
 * should currently show a highlight ring -- set briefly by FeedDeck's
 * clickable warning chips (see Designer.tsx's handleFocusObject) so the
 * offending row in the form is unmistakable, not just scrolled-to. */
export const HighlightContext = createContext<string | null>(null);

export function useHighlighted(id: string): boolean {
  return useContext(HighlightContext) === id;
}
