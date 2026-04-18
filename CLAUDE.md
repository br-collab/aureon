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
- `/api/cato/gate` — Cato atomic settlement gate (PROCEED / HOLD / ESCALATE)
- `/api/cato/settlement-context` — Tokenized-settlement posture (favorable/monitor/elevated)
- `/api/cato/compare-rails` — Multi-chain rail cost comparison (FICC / ETH L1 / Base / Arbitrum / Solana / Fed L1)
- `/api/cato/multichain-gas` — Live per-chain gas/fee state + live CoinGecko prices
- `/api/cato/prices` — Live ETH / SOL USD prices cached from CoinGecko
- `/mcp` — Model Context Protocol endpoint (JSON-RPC 2.0)

## Cato — Verana L0 Tokenized Settlement Doctrine Gate

**Status:** v0.2.2 — paper trading, approaching institutional-testing readiness.
**Reference:** Duffie (2025) *"The Case for PORTS"* — Brookings Institution.

Cato is the Verana L0 pre-settlement doctrine gate. It takes live SOFR (FRED), OFR financial stress (FRED STLFSI4), multi-chain gas/fee state (Blockscout + Solana RPC), and live ETH/SOL prices (CoinGecko), and emits a deterministic `PROCEED / HOLD / ESCALATE` decision plus a `recommended_chain` for tokenized repo settlement.

### Dual implementation — keep them deterministically identical

Cato exists in **two forms** that must produce bit-for-bit identical decisions:

1. **External MCP server** — https://github.com/br-collab/Cato---FICC-MCP
   Node.js, 23 tools, `@modelcontextprotocol/sdk ^1.0.0`. Exposes Cato to LLM callers (Claude Desktop, Agent SDK apps) over JSON-RPC stdio. GitHub Actions CI asserts exactly 23 tools on every push.

2. **Aureon in-process Python twin** — `aureon/mcp/cato_client.py`
   Pure Python, no I/O. Called directly from `server.py` for the `/api/cato/*` endpoints. Data fetching (FRED, Blockscout, Solana RPC, CoinGecko) happens in `server.py` inside `_cato_refresh_inputs()` and flows into the twin via scalar parameters.

**The parity principle (hard rule):** any doctrine change — new threshold, new input, new decision branch — must land in **both** codebases in the same commit series. The deterministic identity is what lets regulators trust the gate regardless of caller. If you only update one side you break SR 11-7 model governance.

### Doctrine thresholds (v0.2.2)

| Input | Threshold | Effect |
|---|---|---|
| OFR STLFSI4 | `> 1.0` | **ESCALATE** — systemic stress, route to human authority |
| OFR STLFSI4 | `> 0.5` | **HOLD** — non-systemic broad stress, route to FICC traditional |
| ETH gas | `> 50 gwei` | **HOLD** — L1 congestion, route to FICC traditional |
| \|SOFR(t) − SOFR(t−1)\| × 100 | `> 10 bps` | **HOLD** — funding-market shock (v0.2.2, Sept 2019 backtest fix) |
| everything below | — | **PROCEED** — atomic settlement viable |

Chain selection (trade-size-agnostic) picks cheapest live rail:
1. Solana if fee < $0.01
2. Base if gas < 1 gwei
3. Ethereum L1 otherwise

Rail routing (notional-aware, in `compare_settlement_rails`):
1. If OFR > 0.5 → FICC (stress override, absolute)
2. If notional > $10M and ETH gas < 30 → Ethereum L1 (large notional wants L1 depth)
3. If Solana fee < $0.01 → Solana
4. If Base gas < 1 gwei → Base
5. If ETH gas > 50 → FICC (gas spike fallback)
6. Otherwise → Ethereum L1

### Live market data flow (every 60 seconds)

Inside `_cato_refresh_inputs()` in `server.py`:
1. Fetch SOFR from FRED (with fed_funds proxy fallback)
2. Read OFR STLFSI4 from the existing `_ofr_cache` (warmed by `market_loop`)
3. Fetch live ETH/SOL USD prices from CoinGecko public API
4. Build `chain_state` dict by fetching gas from Blockscout (eth/base/arbitrum) + Solana RPC `getRecentPrioritizationFees`, using the live SOL price for Solana's fee USD conversion
5. Write `sofr_rate`, `ofr_stress`, `chain_state`, `prices` into `_cato_input_cache` atomically

All `/api/cato/*` handlers read from `_cato_input_cache` and never make a network call in the request path.

### Supported rails

| Rail | Speed | Cost at normal state | Status |
|---|---|---|---|
| FICC traditional | T+1 | ~0.5 bps + SOFR cost-of-capital (SOFR 3.6% × notional × 1/360) | Live |
| Ethereum L1 | ~12s | ~$0.08 / settlement at 0.5 gwei, $2,300 ETH | Live |
| Base (Ethereum L2) | ~2s | ~$0.001 / settlement at 0.01 gwei | Live |
| Arbitrum (Ethereum L2) | ~2s | ~$0.1 / settlement at 0.6 gwei | Live |
| Solana | ~400ms | ~$0.0004 / settlement at 5000 lamports, $84 SOL | Live |
| Fed L1 / PORTS | Instant | TBD | **Pending — GENIUS Act** |

### Historical backtest — SR 11-7 Tier 1 validation artifact

`scripts/cato_backtest.py` replays Cato against March 2020 COVID, September 2019 repo spike, and March 2023 SVB. Results in `scripts/cato_backtest_results.md`:

| Event | v0.2.1 (before fix) | v0.2.2 (current) | Peak OFR | Peak SOFR Δ | Verdict |
|---|---|---|---|---|---|
| March 2020 COVID | 100% (20/20) | **100% (20/20)** | 5.657 | 84 bps | ✅ caught |
| September 2019 repo spike | 0% (0/5) | **80% (4/5)** | -0.155 | 282 bps | ✅ caught after v0.2.2 fix |
| March 2023 SVB | 45.5% (5/11) | 45.5% (5/11) | 1.097 | 25 bps | ⚠️ calibration limit |

**v0.2.2 closed the September 2019 gap** by restoring the SOFR 1-day delta trigger that was silently dropped in the v0.2.0 refactor. Peak SOFR 1-day move was 282 bps (crisis-level) while OFR FSI was *negative* during the event — a pure funding-market liquidity crunch that broad financial-stress indices don't capture. Cato now flags these in real time.

**March 2023 SVB is a documented calibration limitation**, not a bug. Peak OFR STLFSI4 was 1.097 (only barely above the 1.0 ESCALATE threshold, and only for one day). Peak SOFR delta was 25 bps (only exceeded the 10 bps threshold on one day, which was already tripping ESCALATE on OFR). SVB was a slow-moving regional-banking credit event that didn't produce the signal shapes Cato v0.2.2 watches for. To catch events of this class would require additional doctrine inputs (HY OAS delta, VIX percentile, or bank equity performance) — explicitly deferred to avoid over-calibrating to slow-moving credit moves. Documented in `scripts/cato_backtest_results.md`.

Run the backtest with:

```bash
FRED_API_KEY=<key> python3 scripts/cato_backtest.py
```

### Invariants

- External MCP server and in-process Python twin must stay at the same doctrine version and produce identical decisions for identical inputs.
- The gate is **advisory only** — it emits a decision, it does not execute. Operator authority (CAOM-001) still gates every trade.
- `fed_l1` slot is always present in `chain_state` as a documented placeholder. Never remove it. When PORTS ships, the chain_state shape stays the same; only the `status` field flips from `not_yet_issued` to `live`.
- Live prices are fetched on a 60s background cadence. Request path never hits CoinGecko, FRED, Blockscout, or Solana RPC directly. Any endpoint that makes a network call in the request handler is a bug.

## Active trackers
See `TRACKERS.md` for tech debt, architectural findings, and operational concerns with explicit trigger conditions. Review before starting any new phase.

## Governance Invariants

These are non-negotiable design constraints:
- No execution without governed approval through the approval service
- Agents advise only — no autonomous execution
- All decisions carry immutable audit lineage with hash
- The 6-step session protocol must auto-complete at boot (CAOM-001)
- Thifur-H remains declared but not activated (pending SR 11-7 Tier 1 independent validation)
- Operational journal entries use military DTG format (YYYYMMDDHHMM)
