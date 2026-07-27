# Label Studio frontend

React + TypeScript (strict) + Vite, Tailwind CSS v4, TanStack Query for
server state, Zustand for designer state. Talks to the FastAPI backend in
`../backend` over `/api/*` (proxied in dev, same-origin when the backend
serves this app's `dist/` build directly).

## Scripts

- `npm run dev` — Vite dev server on :5173, proxying `/api` (incl. the `/api/ws`
  websocket) to `http://localhost:8000`.
- `npm run build` — typecheck (`tsc -b`) then production build to `dist/`.
- `npm run test` — Vitest + React Testing Library + msw, single run.
- `npm run test:watch` — same, in watch mode.
- `npm run lint` — ESLint (flat config, typescript-eslint recommended).
- `npm run typecheck` — `tsc -b --noEmit`.

## Running against the real backend

```sh
cd ../backend && uv run uvicorn labelmaker.main:app --port 8000   # mock mode
cd ../frontend && npm run dev
```

`vite.config.ts` proxies `/api` (and the `/api/ws` websocket) to
`http://localhost:8000`. After `npm run build`, starting uvicorn from the
repo root auto-mounts `frontend/dist` as the SPA at `/` (see
`backend/src/labelmaker/main.py`'s `_resolve_static_dir`).
