#!/usr/bin/env node
// Copies the bundled UI TTFs from backend/assets/fonts/ into
// frontend/public/fonts/, so Vite serves them as static files at
// /fonts/<name>.ttf for the @font-face rules in src/index.css -- per the
// design doc: "do NOT fetch fonts from the API at runtime."
//
// Six files, not four: the design doc's own weight callouts (Roboto
// Condensed 400/700, Inter 400/600, JetBrains Mono 400/500) need a Regular
// AND a Bold file per family to back them (index.css declares the Bold face
// over a widened weight range -- e.g. 600-700 for Inter -- so Tailwind's
// font-semibold/font-bold both resolve to the one real bold file instead of
// a synthesized fake bold). DejaVu Sans (also bundled, for label rendering)
// is intentionally NOT copied -- the UI chrome never uses it.
//
// Run via `npm run fonts` (wired into predev/prebuild so it can't drift --
// see package.json). Safe to run repeatedly; only touches frontend/public/fonts/.

import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(__dirname, "..", "..", "backend", "assets", "fonts");
const DEST_DIR = join(__dirname, "..", "public", "fonts");

const FILES = [
  "RobotoCondensed-Regular.ttf",
  "RobotoCondensed-Bold.ttf",
  "Inter-Regular.ttf",
  "Inter-Bold.ttf",
  "JetBrainsMono-Regular.ttf",
  "JetBrainsMono-Bold.ttf",
];

if (!existsSync(SRC_DIR)) {
  console.error(
    `[copy-fonts] source directory not found: ${SRC_DIR}\n` +
      "Expected backend/assets/fonts alongside frontend/ -- run this from a full checkout.",
  );
  process.exit(1);
}

mkdirSync(DEST_DIR, { recursive: true });

for (const file of FILES) {
  const src = join(SRC_DIR, file);
  if (!existsSync(src)) {
    console.error(`[copy-fonts] missing bundled font: ${src}`);
    process.exit(1);
  }
  copyFileSync(src, join(DEST_DIR, file));
}

console.log(`[copy-fonts] copied ${FILES.length} font files to ${DEST_DIR}`);
