import { SegmentedControl } from "./SegmentedControl";
import { useTheme } from "../../hooks/useTheme";
import type { Theme } from "../../hooks/useTheme";

const THEME_OPTIONS: { value: Theme; label: string }[] = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "system", label: "System" },
];

/** The full 3-state theme control (Settings' own "Appearance" section) --
 * built on the shared SegmentedControl (role="radiogroup", arrow-key
 * navigable, for free) rather than a bespoke widget, exactly like every
 * other short-enum picker in this app (chain mode, icon mode). AppShell.tsx
 * keeps its OWN compact icon-button version for the header (cycling
 * dark -> light -> system rather than showing all three at once, to fit the
 * 360px floor) -- both read/write through the same hooks/useTheme.ts, so
 * changing one updates the other immediately. */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return <SegmentedControl ariaLabel="Theme" options={THEME_OPTIONS} value={theme} onChange={setTheme} />;
}
