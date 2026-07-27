#!/usr/bin/env node
// Regenerates src/test/fixtures/{label-types,tapes,fonts,symbols}.json from
// a LIVE backend -- these fixtures are the real params_schema JSON Schema
// pydantic produces for the 9 label types (task 2.10's schema-driven form
// renderer is tested against this, not a hand-written approximation of it).
//
// Usage: start the backend first (mock mode is fine -- these endpoints
// don't touch the printer), then:
//
//   cd backend && uv run uvicorn labelmaker.main:app --port 8000 &
//   cd frontend && npm run fixtures
//
// Re-run whenever a label type's Params model changes shape.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = join(__dirname, "..", "src", "test", "fixtures");
const BASE_URL = process.env.LABELMAKER_API_BASE ?? "http://localhost:8000/api";

const ENDPOINTS = {
  "label-types.json": "/label-types",
  "tapes.json": "/tapes",
  "fonts.json": "/fonts",
  "symbols.json": "/symbols",
};

mkdirSync(OUT_DIR, { recursive: true });

for (const [filename, path] of Object.entries(ENDPOINTS)) {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url);
  if (!res.ok) {
    console.error(`[gen-fixtures] GET ${url} -> ${res.status}`);
    process.exit(1);
  }
  const body = await res.json();
  writeFileSync(join(OUT_DIR, filename), `${JSON.stringify(body, null, 2)}\n`);
  console.log(`[gen-fixtures] wrote ${filename} (from ${url})`);
}
