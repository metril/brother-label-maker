import { useEffect, useState } from "react";

// Matches Tailwind's default `xl` breakpoint -- index.css defines no
// `--breakpoint-xl` override, so 1280px is authoritative; if a Tailwind
// override is ever added, this constant must follow it.
export const DESKTOP_QUERY = "(min-width: 1280px)";

/** Used for what CSS media queries can't express -- role/aria-modal/scrim/
 * focus/Escape modality of the tray + print-preview panels. */
export function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia?.(DESKTOP_QUERY).matches ?? false);

  useEffect(() => {
    const mql = window.matchMedia(DESKTOP_QUERY);
    const listener = () => setIsDesktop(mql.matches);
    mql.addEventListener("change", listener);
    listener();
    return () => mql.removeEventListener("change", listener);
  }, []);

  return isDesktop;
}
