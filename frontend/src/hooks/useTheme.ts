import { useEffect, useSyncExternalStore } from "react";

export type Theme = "dark" | "light" | "system";

const STORAGE_KEY = "lm-theme";

/** Every mounted `useTheme()` consumer's re-render callback -- there are, in
 * practice, up to two at once (AppShell's compact header control and
 * Settings' full ThemeToggle), and both must reflect the SAME theme the
 * instant either one changes it. A tiny external-store subscription
 * (`useSyncExternalStore`) does that without a React context provider or
 * prop-drilling `theme`/`setTheme` down from App.tsx -- `localStorage` is
 * the actual source of truth (read fresh on every snapshot, see
 * `readStoredTheme`), this Set only exists to know WHEN to re-read it. */
const listeners = new Set<() => void>();

/** `localStorage["lm-theme"]` -> the resolved `Theme` -- mirrors
 * `index.html`'s own pre-paint script exactly (see that file): absent, or
 * anything other than the two explicit values, means "dark". This app's
 * identity is dark; "system" is something a user opts INTO, not the
 * fallback for having never chosen -- an unconfigured browser on a
 * light-mode OS should not silently show the light theme. */
function readStoredTheme(): Theme {
  // localStorage.getItem throws (SecurityError) when site data is blocked
  // (third-party iframe contexts, a user's storage-blocking browser
  // setting, ...) -- there is no ErrorBoundary above this hook's consumers,
  // so an uncaught throw here white-screens the very first render (L15
  // review fix). Falls back to this app's own unconfigured-browser default
  // ("dark", same as the branch below) rather than propagating.
  let stored: string | null;
  try {
    stored = localStorage.getItem(STORAGE_KEY);
  } catch {
    return "dark";
  }
  return stored === "light" || stored === "system" ? stored : "dark";
}

/** Sets (or, for "system", removes) `<html data-theme>` -- index.css's
 * theme blocks key off this exact attribute/absence, see that file's own
 * doc comment for the three-state model. */
function applyTheme(theme: Theme): void {
  if (theme === "system") {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = theme;
  }
}

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
  };
}

function setTheme(next: Theme): void {
  // Same guard as readStoredTheme's own (L15): a blocked/full localStorage
  // throws on write too. Swallowed as a no-op -- the theme still applies
  // to <html> for this tab and this session, it just won't survive a
  // reload, which is strictly better than the setTheme call itself
  // throwing and leaving the UI that called it (ThemeToggle's onClick,
  // Settings' Appearance section) in a broken state.
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // no-op -- see comment above.
  }
  applyTheme(next);
  listeners.forEach((listener) => listener());
}

export interface UseThemeResult {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

/** The app's 3-state theme control (components/ui/ThemeToggle.tsx,
 * AppShell.tsx's compact header version, Settings.tsx's "Appearance"
 * section) reads/writes through this one hook -- `localStorage["lm-theme"]`
 * is the persisted value, `<html data-theme>` is what index.css's theme
 * blocks actually key off (see that file), and this hook keeps the two in
 * sync on every `setTheme` call. Every consumer shares one source of truth
 * (the module-level `listeners`/`localStorage` pair above), so flipping the
 * theme from Settings updates AppShell's own header control immediately,
 * with no prop drilling or context provider needed for something this
 * small. */
export function useTheme(): UseThemeResult {
  const theme = useSyncExternalStore(subscribe, readStoredTheme);

  // Belt-and-suspenders: index.html's own pre-paint <script> already applies
  // the stored theme to `<html>` before React even loads (see that file),
  // so in the real app this is a same-value no-op on first mount. It
  // matters for two cases that script can't cover: component tests (which
  // mount straight into jsdom, no index.html pre-paint script involved) and
  // this SAME browser tab's DOM staying correct even if something else ever
  // reads `theme` without going through `setTheme` first.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return { theme, setTheme };
}
