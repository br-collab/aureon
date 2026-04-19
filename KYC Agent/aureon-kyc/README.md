# AUREON-KYC

Institutional KYC compliance agent — React front end + Express proxy, single deployable service.

Part of the Aureon / The Grid 3 doctrine stack. Conducts structured Know Your Customer intake under SR 11-7 / FinCEN / BSA framing, with per-step audit logging and a closing compliance summary.

## Architecture

```
aureon-kyc/
├── index.html              Vite entry
├── src/
│   ├── main.jsx            React bootstrap
│   ├── App.jsx             KYC agent UI (calls /api/chat)
│   └── index.css
├── server.js               Express proxy + prod static server
├── vite.config.js          dev server proxies /api → :8787
├── package.json
└── .env.example
```

- **Front end** (`src/`) never sees the Anthropic API key. It calls `/api/chat` on the same origin.
- **Proxy** (`server.js`) holds `ANTHROPIC_API_KEY` server-side, forwards to `https://api.anthropic.com/v1/messages`, and in production serves the built `dist/` as static files from the same port.
- One service, one origin, no CORS in prod.

## Setup

Requires Node 18.17+.

```bash
cp .env.example .env          # paste your ANTHROPIC_API_KEY
npm install
```

## Dev

```bash
npm run dev
```

Runs Vite on `:5173` and the Express proxy on `:8787` concurrently. Vite proxies `/api/*` to the Express server, so visit **http://localhost:5173**.

Server auto-restarts via `node --watch` on save.

## Production build

```bash
npm run build                 # emits dist/
npm start                     # serves dist/ + /api/chat on PORT (default 8787)
```

Visit **http://localhost:8787**.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Server-side key for the Anthropic API. |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Default model used if the client doesn't specify one. |
| `ANTHROPIC_MAX_TOKENS` | `1000` | Default `max_tokens`. |
| `PORT` | `8787` | Port the Express server binds to. |
| `VITE_APP_NAME` | `AUREON-KYC` | Client-side name (currently informational). |

## API surface

- `GET /healthz` — `{ ok, model, hasKey }` for liveness / config sanity.
- `POST /api/chat` — Body: `{ messages, system?, model?, max_tokens? }`. Proxies to Anthropic with `anthropic-version: 2023-06-01`. Returns the upstream JSON verbatim.

The client sends `{ messages, system }`; the server fills in model + max_tokens from env.

## Deploying to Railway

1. Push this directory as its own service (or monorepo subpath).
2. Set `ANTHROPIC_API_KEY` in the service's variables.
3. Build: `npm install && npm run build`
4. Start: `npm start`
5. Railway injects `PORT` automatically; the server reads it.

Per Aureon deploy convention: **commit every file before pushing** — Railway fails silently on missing untracked files.

## Compliance scope

- Dark institutional UI (Ravelo Strategic Solutions / Aureon red-rule styling).
- Per-turn audit tags parsed from the model response and rendered inline plus in a step strip.
- Risk flags surface in the header and in the close-out summary.
- `Close + Audit` generates a formal KYC Audit Summary intended for regulatory review.

This is advisory tooling. Nothing here executes; all decisions remain with the operator under CAOM-001 authority.
