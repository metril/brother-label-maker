import { describe, expect, it } from "vitest";
import css from "../index.css?raw";

/** Guard against a repeat of the SymbolBrowser.tsx bug (2026-08 Library
 * rework) where a tile's label sat in the text-color class for deck-300, a
 * token that was never actually declared anywhere in index.css (the
 * palette's numeric scale stops at deck-200/deck-400 -- see that file's own
 * `@theme` block). Tailwind's own build simply emits no rule for a class it
 * can't resolve against a declared `--color-*` custom property, so the
 * element silently fell back to inheriting an unrelated color -- no build
 * error, no lint error, no runtime error; the only symptom was a label that
 * was nearly invisible in one theme. Nothing else in this codebase's
 * toolchain catches a phantom token like that, so this test does: it scans
 * every `.ts`/`.tsx` file under `src/` for `text-deck-N`/`bg-deck-N`/
 * `border-deck-N`/`*-icon-well` class usages and asserts each one
 * references a token index.css's `@theme` block (or one of the three
 * runtime theme blocks -- see index.css's own module docstring) actually
 * declares.
 *
 * Sources are loaded via `import.meta.glob(..., { query: "?raw" })` rather
 * than `node:fs`: tsconfig.app.json's type surface is `vite/client` only
 * (no Node types), and the glob keeps this file inside that surface while
 * Vitest resolves it natively -- a static source-text scan either way, so
 * it runs fine under the project's default jsdom environment and shares
 * the same `test/setup.ts` as every other suite. */

const sources = import.meta.glob<string>("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

/** Matches Tailwind utility classes of the shape `text-deck-900`,
 * `bg-deck-400` (a leading `hover:`/`sm:`/etc. modifier, or a trailing
 * `/NN` opacity modifier, are both outside the `\b`-delimited match, so
 * they don't interfere) -- captures just the numeric suffix. Declared with
 * the `g` flag; callers must construct a FRESH `RegExp` per scan (via
 * `new RegExp(DECK_CLASS_RE)`) rather than reusing this const directly, or
 * `exec`'s own `lastIndex` state will leak across files. */
const DECK_CLASS_RE = /\b(?:text|bg|border)-deck-(\d+)\b/g;

/** Same idea for the one non-numeric semantic token this app themes
 * per-mode (see index.css's own docstring on why `--color-icon-well` is
 * special) -- no capture group needed, just presence. No `g` flag: this is
 * only ever used with `.test()`, which needs no `lastIndex` reset between
 * calls. */
const ICON_WELL_CLASS_RE = /\b(?:text|bg|border)-icon-well\b/;

function declaredDeckTokens(styles: string): Set<string> {
  const tokens = new Set<string>();
  const re = /--color-deck-(\d+)\s*:/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(styles))) tokens.add(m[1]!);
  return tokens;
}

describe("theme token guard", () => {
  const declaredDeck = declaredDeckTokens(css);
  const iconWellDeclared = /--color-icon-well\s*:/.test(css);

  it("every text-deck-N / bg-deck-N / border-deck-N class referenced anywhere in src/ names a token index.css's @theme block actually declares", () => {
    // Maps an undeclared numeric suffix to every file (glob-relative to
    // src/test/) that references it, so a failure names exactly what to fix
    // rather than just "something, somewhere" -- deliberately built as a
    // real assertion target (not just console output) so it survives in CI
    // logs.
    const undeclared = new Map<string, Set<string>>();

    for (const [file, content] of Object.entries(sources)) {
      const re = new RegExp(DECK_CLASS_RE);
      let m: RegExpExecArray | null;
      while ((m = re.exec(content))) {
        const token = m[1]!;
        if (declaredDeck.has(token)) continue;
        if (!undeclared.has(token)) undeclared.set(token, new Set());
        undeclared.get(token)!.add(file);
      }
    }

    const report = [...undeclared.entries()]
      .map(([token, fileSet]) => `deck-${token} (${[...fileSet].join(", ")})`)
      .join("; ");
    expect(report, report ? `undeclared deck-N tokens in use: ${report}` : undefined).toBe("");
  });

  it("icon-well is declared in index.css whenever any file under src/ references it as a class", () => {
    const referencingFiles = Object.entries(sources)
      .filter(([, content]) => ICON_WELL_CLASS_RE.test(content))
      .map(([file]) => file);

    if (referencingFiles.length > 0) {
      expect(iconWellDeclared).toBe(true);
    } else {
      // Nothing in src/ references it right now -- the assertion above
      // would be vacuous, so this just documents that this test still ran
      // and found the (expected) empty set, rather than silently no-op-ing.
      expect(referencingFiles).toEqual([]);
    }
  });
});
