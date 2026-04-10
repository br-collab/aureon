# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Project Aureon / The Grid 3 is a doctrine-governed pre-trade governance and execution-intelligence platform. It sits between portfolio intent and OMS/EMS systems as a **Decision System of Record (DSOR)** — agents advise, operators decide, nothing executes without governed approval.

Single operator (CAOM-001): one person holds all three authority tiers (Strategic, Tactical, Execution).

## Development Commands

```bash
# Local development (creates venv, installs deps, runs Flask on port 5001)
./scripts/start.sh

# Or manually:
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
AUREON_PORT=5001 python server.py

# Production (Railway auto-deploys on push to main)
# Uses: gunicorn --config gunicorn.conf.py --worker-class=gthread --workers=1 --threads=4 server:app
# Health check: GET /api/snapshot
```

There is no automated test suite. Validation is manual via Railway deployment.

## Architecture

### Doctrine Stack (top-down)

| Layer | Altitude | Role |
|---|---|---|
| **Neptune Spear** | 50,000 ft | Alpha origination — advisory only, never executes |
| **Mentat** | 30,000 ft | Decision intelligence, scenario support |
| **Kaladan** | 10,000 ft | Lifecycle orchestration, approval lineage, evidence |
| **Thifur-C2** | 1,000 ft | Command & Control coordination, lineage assembly |
| **Thifur Triplet** | 500 ft | R (deterministic), J (bounded autonomy), H (adaptive, declared not active) |
| **Verana L0** | Ground | Network registry, compliance, MCP server (5 resources + 4 tools), session control |

### Key Code Layout

- **`server.py`** — Monolith Flask backend (~266KB). All API routes, state management, background threads (market loop, doctrine stack). This is the entry point for everything.
- **`index.html`** — Full dashboard UI (~204KB). Portfolio, approvals, compliance, decision journal.
- **`aureon/`** — Extracted domain modules (refactored from server.py):
  - `config/` — CAOM, Neptune Spear spec, C2 doctrine, settings
  - `approval_service/` — Role-based approval gates, release control, decision normalization
  - `policy_engine/` — Pre-trade gate evaluation (market status, cash, concentration, drawdown, OFAC, macro stress, hours)
  - `evidence_service/` — Trade reports, compliance PDFs, audit packaging
  - `session/` — 6-step session open protocol (must auto-run at boot, never require manual curl)
  - `mcp/` — Verana L0 MCP server (JSON-RPC 2.0) + Neptune data pipe clients (Unusual Whales, Tradier, Alpaca, CBOE, EDGAR, Blockscout)
  - `persistence/` — JSON state save/load with corruption salvage
  - `core/models.py` — GovernedDecision dataclass
  - `integration_adapters/` — OMS, EMS, FIX stubs
  - `data/market_data.py` — Twelve Data (primary) + yfinance (fallback), 60s cache

### State Management

All runtime state lives in a centralized `aureon_state` dict protected by `threading.Lock`. Persisted as JSON:
- Local: `aureon_state_persist.json`
- Railway production: `/data/aureon_state_persist.json` (volume mount via `RAILWAY_VOLUME_MOUNT_PATH`)
- Save triggers after every HITL decision via background thread

### Background Threads

Started via `_start_background_threads()` in `server.py`. On Railway, triggered from `gunicorn.conf.py` `post_fork` hook (not at import time). Includes market price loop (5s tick), doctrine stack run, state persistence.

## Deployment

- **Backend**: Railway (Nixpacks build, Gunicorn). Auto-deploys on push to `main`.
- **Frontend**: Vercel (serves `index.html`). Auto-deploys on push to `main`.
- **Critical**: Always commit all imported/required files before pushing. Railway fails silently on missing untracked files.

## Environment Variables

Required in `.env` (local) or Railway service variables (production):
- `TWELVE_DATA_API_KEY` — market data
- `AUREON_EMAIL`, `AUREON_EMAIL_PW`, `AUREON_EMAIL_RECIPIENT` — Gmail SMTP reporting
- `ALPACA_API_KEY`, `ALPACA_API_SECRET` — paper trading
- `RAILWAY_VOLUME_MOUNT_PATH` — production state persistence directory

## Key API Routes

- `/api/snapshot` — Portfolio + compliance state (also health check)
- `/api/decisions` — Pending decisions with pre-trade gates
- `/api/decisions/<id>/pretrade` — Full gate evaluation
- `/api/compliance` — Alerts + compliance surfaces
- `/api/authority` — Authority log + approval lineage
- `/api/decision-journal` — HITL decisions + outcomes
- `/api/operational-journal` — DTG-stamped operational record
- `/mcp` — Model Context Protocol endpoint (JSON-RPC 2.0)

## Governance Invariants

These are non-negotiable design constraints:
- No execution without governed approval through the approval service
- Agents advise only — no autonomous execution
- All decisions carry immutable audit lineage with hash
- The 6-step session protocol must auto-complete at boot (CAOM-001)
- Thifur-H remains declared but not activated (pending SR 11-7 Tier 1 independent validation)
- Operational journal entries use military DTG format (YYYYMMDDHHMM)
