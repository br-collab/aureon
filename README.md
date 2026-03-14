# Project Aureon - The Grid 3

Doctrine-driven financial operating system prototype for portfolio governance, pre-trade control, settlement visibility, and human-approved execution.

---

## Overview

Project Aureon is a lightweight prototype that demonstrates how an institutional investment process can move through a clear governed workflow:

- market data is ingested from live or simulated sources
- doctrine rules evaluate portfolio state and pending actions
- human operators review and approve material decisions
- execution updates treasury, settlement, and compliance state together
- reporting artifacts are generated from the same auditable lifecycle record

The current prototype is intentionally lightweight: a Flask backend in `server.py`, a single-page frontend in `index.html`, no build step, and no database. Even with that minimal footprint, the system models live positions, pending decisions, doctrine gates, treasury state, settlement progression, macro regime overlays, systemic stress gating, and compliance-oriented reporting. Market pricing comes from Yahoo Finance when available and falls back to simulation when needed. Macro and rates context comes from FRED with deterministic fallback, while OFR-style systemic stress overlays feed both the dashboard and pre-trade doctrine.

---

## Core Concept

Project Aureon explores a different approach to portfolio operations.

Instead of treating governance, approval, execution, settlement, and reporting as separate systems, the prototype treats them as one continuous doctrine-driven lifecycle.

The central idea is:

`doctrine -> governed decision -> controlled execution -> auditable lifecycle`

This allows the platform to move from:

`portfolio state -> governed action -> execution record -> compliance artifact`

---

## Why This Project Exists

Many trading systems are strong at execution but weaker at expressing why a decision was allowed, who had authority, what rules were active, and how that decision should be explained afterward to compliance, audit, or leadership.

Project Aureon exists to demonstrate a different posture:

- governance is a first-class system behavior
- human approval is explicit, recorded, and attributable
- pre-trade controls are visible rather than hidden in backend logic
- settlement and treasury consequences are part of the same lifecycle
- compliance artifacts can be generated from the same execution record

---

## Features

- Four-layer doctrine stack spanning governance, intelligence, lifecycle control, and execution
- Pending trade queue with human approval workflow for material decisions
- Pre-trade routing checks with PASS/WARN/FAIL gate logic
- Post-trade confirmation and lifecycle-aware settlement tracking
- Multi-asset portfolio model covering equities, ETFs, FX, fixed income, commodities, and crypto
- Live and simulated pricing modes with fallback behavior
- Layered data architecture: Yahoo Finance for prices, FRED for macro/rates, OFR overlay for systemic stress
- Treasury and cash-availability monitoring
- Compliance trade reports with PDF generation and audit metadata
- Doctrine versioning and emergency halt controls
- Optional email reporting for pre-market, close, weekly, and post-trade communications
- FIX translation stub for OMS-overlay architecture exploration
- Thesis Intelligence Lab with upload support, inferred-risk scoring, and institutional mandate checks

---

## Architecture

High-level flow:

```text
+------------------+      +-------------------+      +-------------------+
|   Market Data    | ---> |    server.py      | ---> |    index.html     |
| Yahoo / FRED /   |      | Flask + doctrine  |      | Dashboard + modals|
| OFR / fallback   |      | + risk overlays   |      | + replay surfaces |
+------------------+      +-------------------+      +-------------------+
           |                           |                          |
           v                           v                          v
+------------------+      +-------------------+      +-------------------+
| Portfolio State  |      | Governance Logic  | ---> | Operator Review   |
| Cash + positions |      | Gates + decisions |      | Approval workflow |
+------------------+      +-------------------+      +-------------------+
           |                           |                          |
           v                           v                          v
+------------------+      +-------------------+      +-------------------+
| Treasury + T+0/1 |      | Compliance Output | ---> | Email / PDF / API |
| Settlement status|      | Reports + hashes  |      | Audit consumption |
+------------------+      +-------------------+      +-------------------+
```

Primary layers in the current prototype:

- `server.py`: Flask backend, shared state, doctrine logic, API routes, price updates, email scheduling
- `index.html`: single-file dashboard UI, modal workflows, polling logic, governance and reports views
- `fix_adapter.py`: FIX 4.4 translation stub for OMS handoff exploration
- `aureon_state_persist.json`: local persisted runtime state
- `setup_launch_agent.sh`: local helper for launch setup

### Data Architecture

- `Yahoo Finance / yfinance`: live and historical market prices for portfolio instruments
- `FRED`: rates, curve shape, VIX, and credit-spread proxies for macro regime scoring
- `OFR Financial Stress overlay`: systemic-stress context used in Compliance, Governance, Thesis scoring, and pre-trade doctrine
- `Deterministic fallback layers`: keep the platform functional when live external feeds are unavailable

---

## Example Workflow

1. The system loads portfolio state, doctrine state, and pricing inputs.
2. Thifur surfaces a pending decision when a rebalance or opportunity crosses threshold.
3. A human operator opens the pre-trade routing check and reviews doctrine gates.
4. If approval is granted and no FAIL condition blocks execution, the trade is executed.
5. Cash, positions, settlement lifecycle, and compliance artifacts are updated together.
6. The dashboard, email layer, and report endpoints reflect the new post-trade state.

---

## Quick Start

From the repository root:

```bash
pip install flask yfinance reportlab python-dotenv
python server.py
```

Open the dashboard at:

```text
http://localhost:5001
```

Environment variables in `.env`:

```text
AUREON_EMAIL=aureonfsos@gmail.com
AUREON_EMAIL_PW=your_app_password
```

Email is optional. The dashboard runs without it.

---

## Repository Structure

```text
The Grid 3/
  README.md
  server.py
  index.html
  fix_adapter.py
  setup_launch_agent.sh
  aureon_state_persist.json
  Thought notes/
```

Directory summary:

- `server.py`: backend orchestration, doctrine stack, trade lifecycle, API
- `index.html`: full frontend dashboard and operator workflows
- `fix_adapter.py`: integration stub for FIX message translation
- `setup_launch_agent.sh`: local environment helper
- `aureon_state_persist.json`: persisted system state snapshot

---

## Doctrine Model

### Four-Layer Doctrine Stack

| Layer | Name | Role | Runs |
|-------|------|------|------|
| **L0** | **Verana** | Network governance, session boundary enforcement, regulatory absorption | Startup + market loop |
| **L1** | **Mentat** | Strategic intelligence, doctrine truth, drawdown guard | Startup + pre-trade |
| **L1B** | **Risk Manager** | Independent portfolio risk governance for drawdown, concentration, liquidity, and VaR framing | Pre-trade + compliance |
| **L2** | **Kaladan** | Lifecycle orchestration, settlement routing, cash gate | Pre-trade + treasury |
| **L3** | **Thifur** | Agentic execution with specialized sub-agents | Continuous |

### Thifur Sub-Agents

| Agent | Style | Book |
|-------|-------|------|
| **THIFUR_R** | Rules-based | Fixed income (TLT, HYG, AGG) for capital preservation |
| **THIFUR_J** | Systematic / index | Equities (SPY, EEM) and commodities (GLD) for momentum |
| **THIFUR_H** | Human-approved agentic | Large discretionary trades above $400K notional that require Bill's approval before execution |

---

## API Surface

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/portfolio` | Live positions, prices, P&L, cash, allocations |
| `GET` | `/api/compliance` | Active alerts, drawdown, regulatory frameworks, macro and OFR overlay |
| `GET` | `/api/decisions` | Pending trade decisions awaiting human approval |
| `GET` | `/api/decisions/<id>/pretrade` | Pre-trade doctrine gate checks |
| `POST` | `/api/decisions/<id>` | Approve or reject a decision |
| `GET` | `/api/governance` | Doctrine version, authority log, stack result, audit hash |
| `GET` | `/api/macro` | Macro regime and OFR systemic-stress snapshot |
| `GET` | `/api/treasury` | Settlement pipeline, cash gate, rail status |
| `GET` | `/api/snapshot` | Lightweight health snapshot |
| `POST` | `/api/stack` | Trigger doctrine stack re-run |
| `POST` | `/api/email/test` | Send a test weekly P&L report |

### Port Reference

The server runs on **port 5001**.

```text
Dashboard  -> http://localhost:5001
Snapshot   -> http://localhost:5001/api/snapshot
Portfolio  -> http://localhost:5001/api/portfolio
Decisions  -> http://localhost:5001/api/decisions
```

---

## Operational Workflows

### Trade Approval Workflow

When Thifur-H surfaces a trade, it enters the pending queue and requires human authority before execution.

```text
1. PENDING DECISION appears in Live Trading tab
2. Operator opens pre-trade routing check
3. Seven doctrine gates resolve with PASS / WARN / FAIL
4. EXECUTE ORDER enables only if no FAIL condition blocks execution
5. Backend books the trade, deducts cash, and records the authority path
6. Macro regime and OFR systemic-stress context are stamped into the execution record
7. Post-trade confirmation and compliance artifacts are generated
```

Core gate set:

- Session Boundary (Verana L0)
- Liquidity Buffer (Risk Manager L1B)
- Drawdown Guard (Risk Manager L1B)
- Position Limit (Risk Manager L1B)
- Doctrine Integrity (Thifur L3)
- Systemic Stress (Verana L0 / OFR)
- OFAC Screening (Verana L0)

### Settlement Lifecycle

Aligned to an institutional OMS-style lifecycle. Settlement state is recalculated during treasury evaluation.

#### T+0 - Crypto (BTC, ETH, SOL)

```text
< 3 min   -> INSTRUCTED
< 8 min   -> MATCHED
< 20 min  -> CASH_SETTLED
> 20 min  -> FULLY_SETTLED
```

#### T+1 - Equities, FX, Fixed Income

SEC Rule 15c6-1 moved U.S. equities to T+1 effective **May 28, 2024**. Aureon applies T+1 treatment to equities, FX, and fixed income in this prototype.

```text
< 3 min         -> INSTRUCTED
< 10 min        -> MATCHED
same day+       -> CASH_SETTLED
next BD 17:30ET -> FULLY_SETTLED
```

Weekend logic: Friday trades settle on Monday. No settlement on Saturday or Sunday.

### Market Operations

#### Price Feed

```text
Priority 1 - Yahoo Finance (yfinance)
  Fetched every 60 seconds for all instruments.
  Cached to avoid over-polling.
  Micro-nudge applied between fetches so the UI stays live.

Priority 2 - Simulated random walk
  Activated when Yahoo Finance is unavailable.
  Volatility: crypto 0.8% / tick, equities 0.2%, FX 0.05%
```

Symbol mapping:

`BTC -> BTC-USD`, `ETH -> ETH-USD`, `SOL -> SOL-USD`, `EUR/USD -> EURUSD=X`, `GBP/USD -> GBPUSD=X`

#### Automated Emails

All scheduled times are in U.S. Eastern Time.

| Time | Days | Report |
|------|------|--------|
| 8:30 AM ET | Mon-Fri | Pre-Market Briefing |
| 4:15 PM ET | Mon-Fri | Market Close Report |
| 5:00 PM ET | Friday | Weekly P&L Report |

### Governance and Risk Reference

#### Pre-Trade Gate Thresholds

| Gate | PASS | WARN | FAIL |
|------|------|------|------|
| Session Boundary | Market open or crypto | Pre-market equity/FX | - |
| Cash Availability | Cash >= notional | Cash >= 90% of notional | Cash < 90% of notional |
| Drawdown Guard | Drawdown < 5% | 5-8% | > 8% |
| Position Limit | Position < 10% of portfolio | 10-15% | > 15% |
| Doctrine Integrity | Always PASS (simulated) | - | - |

#### Compliance Frameworks

Frameworks reflected in Doctrine v1.2:

- SR 11-7 - Model Risk Management
- OCC 2023-17 - Third-Party Risk
- BCBS 239 - Risk Data Aggregation
- MiFID II Art. 17 / RTS 6 - Algorithmic Trading
- DORA - Digital Operational Resilience
- EU AI Act - High-Risk AI Systems

---

## Commercial Model

Aureon is framed as a three-tier commercial product aligned to distinct institutional buyer profiles.

### Tier 1 - Governance Overlay

**Target:** Institutions with an existing OMS/EMS stack that want doctrine-driven governance above current execution infrastructure.

**Positioning:** Aureon does not replace the OMS. Approved decisions are translated into FIX 4.4 NewOrderSingle payloads by `fix_adapter.py` and handed off to the incumbent stack after clearing the doctrine layers.

**Included capabilities:**

- doctrine-stamped, hash-verified governance records
- emergency halt independent of the OMS
- immutable compliance trade report PDFs
- MiFID II Article 26 enrichment on execution records
- human authority auditability per decision

**Commercial model:** Per-AUM basis points or per-desk annual license.

### Tier 2 - Full Stack

**Target:** Greenfield trading desks, family offices, hedge fund launches, and proprietary groups without an incumbent OMS.

**Positioning:** The complete Aureon system deployed as the firm's primary operating layer for pre-trade review, execution control, treasury visibility, settlement tracking, and governance.

**Included capabilities:** Everything in Tier 1, plus:

- live market data integration
- multi-asset portfolio management
- settlement pipeline tracking
- treasury management
- doctrine gate animation and human approval workflow
- post-trade confirmation email plus compliance report artifacts
- L0 governance console with emergency halt and doctrine versioning

**Commercial model:** Annual platform license scaled by AUM or seat count.

### Tier 3 - Compliance Intelligence as a Service (CIaaS)

**Target:** Institutions that need machine-readable, doctrine-stamped compliance artifacts without adopting Aureon's full execution stack.

**Positioning:** Aureon's Kaladan L2 compliance report engine delivered as a standalone service returning signed PDF and structured JSON outputs.

**Included capabilities:**

- on-demand or batch compliance report generation
- instrument enrichment across ISIN, CUSIP, FIX, MIC, LEI, and currency fields
- doctrine hash-chain provenance
- immutable human-readable PDF artifacts
- structured JSON for downstream compliance ingestion

**Commercial model:** Per-report API pricing or monthly subscription.

### Integration Mode Summary

| Mode | Indicator | Meaning |
|------|-----------|---------|
| **Standalone** | Purple pill | Aureon drives execution directly |
| **OMS Overlay** | Cyan pill (pulsing) | Aureon governs above an existing OMS via `fix_adapter.py` |

---

## Current Limitations

- The system is a prototype and uses a single shared in-memory state model rather than a production data layer
- The architecture is intentionally compressed into a minimal file count for speed of iteration and demonstration
- Live pricing depends on `yfinance` availability and falls back to simulation when market data is unavailable
- FIX support is a translation stub, not a live production session with a broker or OMS
- Compliance posture is demonstrated at a portfolio-project level and is not a substitute for full legal or regulatory implementation
- The README still contains detailed session history that may later move to dedicated documentation

---

## Roadmap

- Continue standardizing the README to match the broader project portfolio format
- Separate the top-level project narrative from lower-level operating reference material
- Move long-form session history into dedicated documentation if needed
- Add screenshots or architecture visuals for the strongest dashboard and workflow views
- Expand maintainer-oriented documentation around doctrine logic and integration paths

---

## Changelog

### 2026-03-11 - Session 7 (Portfolio Rebalancing, Drift-Aware Signals, Signal Type UI)

**Fix - Initial Portfolio Structure**
- `INITIAL_POSITIONS` redesigned to approximate doctrine-mandated targets at inception
- Added FX positions: EUR/USD (3,500,000 units @ $1.0842) and GBP/USD (2,500,000 units @ $1.2651)
- Added MSFT, AMZN, SOL, USO to initial book; equity shares increased to approach 40% target
- Added USO as commodity position alongside GLD to reach 10% commodity target
- Portfolio at inception: Equities 37.3% · FI 25.0% · FX 13.9% · Commodities 10.0% · Crypto 9.6% · Cash 4.1%
- Drift shown on the dashboard now reflects actual market price movement, not structural underfunding

**Feature - Drift-Aware Thifur-H Signal Engine**
- `_generate_signal()` redesigned to check allocation drift before surfacing any signal
- `DRIFT_THRESHOLD = 0.04` (4%) triggers a REBALANCE signal when an asset class exceeds target delta
- REBALANCE signal selects from class-specific, direction-aware candidate pools
- REBALANCE rationale now states asset class, drift delta, doctrine target, and human-approval requirement
- If no class exceeds threshold, the logic falls through to OPPORTUNISTIC signals
- `signal_type` field added to each pending decision: `"REBALANCE"` or `"OPPORTUNISTIC"`
- Verana L0 session boundary still suppresses non-crypto signals outside market hours
- $400K notional materiality threshold unchanged

**Feature - Signal Type Badge in Pending Decisions UI**
- Pending decision cards now display a labeled badge per signal type
- REBALANCE uses an amber `⚖ REBALANCE` badge with orange accent border
- OPPORTUNISTIC uses a cyan `◈ OPPORTUNISTIC` badge
- The signal category is immediately visible to the operator

### 2026-03-10 - Session 6 (Instrument Enrichment, FIX Adapter, OMS Overlay, Commercial Architecture)

**Feature - Tape Enrichment with Formal Instrument Identifiers**
- Added `_INSTRUMENT_REF` dictionary in `server.py` covering all 20 supported instruments
- Entries provide ISIN, CUSIP, FIX Tag 167 SecurityType, FIX Tag 460 Product, MIC, and ISO 4217 currency
- Added `_AUREON_LEI = "AUREON-LEI-PENDING-00001"` for ISO 17442 entity identification
- Compliance trade report now includes `isin`, `cusip`, `fix_type`, `fix_product`, `mic`, `currency`, and `entity_lei`
- FX pairs use `fix_type=FXSPOT`, `fix_product=4`, `mic=XOFF`
- Crypto uses `fix_type=CRYPTO`, `fix_product=14`, `mic=XCRY`
- Commodities use `fix_product=2`

**New File - `fix_adapter.py` (FIX 4.4 Translation Stub)**
- `translate_to_fix(aureon_decision)` maps an APPROVED decision to a FIX 4.4 NewOrderSingle payload
- `translate_from_fix_execution(fix_exec_report)` maps FIX execution responses back to Aureon format
- `serialize_to_wire(fix_msg)` provides a stub serializer
- `validate_fix_message(fix_msg)` validates required fields and limit-order requirements
- Module docstring documents Direct FIX Session, OMS Hand-off, and Compliance Enrichment Only integration modes
- Running `python3 fix_adapter.py` prints stub output for a sample AAPL market buy

**Feature - Integration Mode Indicator (Dashboard Header)**
- Added a header pill that displays `Standalone` or `OMS Overlay`
- `setIntegrationMode(mode)` toggles pill class and label
- `initIntegrationMode()` sets the default to `standalone`
- Hover tooltip explains the architectural difference between modes
- OMS Overlay mode is reserved for future live FIX-session activation

**Documentation - Commercial Architecture Section**
- Three-tier commercial model documented in the README
- Tier 1: Governance Overlay
- Tier 2: Full Stack
- Tier 3: Compliance Intelligence as a Service
- Integration mode reference table added

### 2026-03-10 - Session 5 (Kaladan L2 Compliance Trade Reports)

**Architecture - Compliance Report as Kaladan L2 Lifecycle Artifact**
- Compliance report now fires when Kaladan confirms execution
- Three-section report structure: Trade Identity, Governance Block, Risk State
- Designed to align with MiFID II Art. 17 / RTS 6 and SR 11-7 style documentation goals
- `_pretrade_cache` stores gate results keyed by `decision_id`

**Feature - `_build_trade_report()`**
- Called immediately after positions update and cash is deducted
- Trade identity includes symbol, asset class, direction, quantity, execution price, notional, settlement window, execution timestamp, decision ID, agent, and authority hash
- Governance block includes doctrine version, gate results, tier authority, approval metadata, and compliance frameworks
- Risk state includes drawdown, portfolio value, cash before/after, concentration, VaR estimate, and positions held post-trade
- `report_id` format is `CTR-<last 8 chars of decision_id>`

**Feature - `_generate_compliance_pdf()`**
- ReportLab PDF with dark-theme Aureon branding
- Immutable PDF bytes stored on the report dict from generation time
- Gate results render as a formatted color-coded table
- Footer includes compliance frameworks, authority hash, report ID, and generation timestamp

**Feature - `_send_trade_confirmation_email()`**
- Fires in a non-blocking background thread seconds after execution
- Separate from scheduled pre-market, close, and weekly sends
- HTML email includes all three report sections and gate results table
- Subject format: `[AUREON] Trade Executed: {ACTION} {SYMBOL} ${NOTIONAL} · {REPORT_ID}`

**New API Endpoints**
- `GET /api/trade-reports` returns chronological feed without PDF bytes
- `GET /api/trade-reports/<id>` returns single-report JSON by report ID or decision ID
- `GET /api/trade-reports/<id>/pdf` serves the immutable PDF artifact inline
- `POST /api/decisions/<id>` now returns `report_id`

**Frontend - Reports Tab**
- Reports tab now includes Weekly P&L, Compliance Trade Reports, and Audit cards
- `#ctr-count` and `#ctr-live-count` badges update live from `/api/trade-reports`
- Compliance feed renders each report as a full card with three-column data grid and PDF link
- Post-trade modal now surfaces Compliance Report ID and PDF link immediately

**Dependency Added**
- `reportlab` for PDF generation

**Resilience Fix**
- `yfinance` import now degrades gracefully to simulated pricing if unavailable

### 2026-03-09 - Session 4 (L0 Governance, Emergency Halt, Doctrine Versioning)

**Architecture - L0 Governance Layer**
- Defined a four-tier authority hierarchy for doctrine modification
- Tier 0: Emergency Halt
- Tier 1: Human Authority
- Tier 2: Regulatory Mandate
- Tier 3: Thifur Telemetry

**Feature - Emergency Halt (Tier 0)**
- Added `halt_active`, `halt_ts`, `halt_authority`, and `halt_reason` to server state
- `_generate_signal()` now returns immediately when halted
- `api_resolve_decision()` returns HTTP 423 on attempted approval while halted
- Added `GET /api/halt`, `POST /api/halt`, and `POST /api/halt/resume`
- Frontend now shows a global halt banner and header control
- Approve attempts while halted show a blocked toast instead of opening the modal
- `slowTick()` syncs halt state every 15 seconds

**Feature - Doctrine Versioning**
- Added immutable `doctrine_version_log`
- Added `pending_doctrine_updates`
- Added `POST /api/doctrine/propose` and `POST /api/doctrine/approve/<update_id>`
- Governance tab now shows doctrine version log, pending updates, and proposal workflow

**Governance Tab Redesign**
- KPI row expanded to four cards
- Added L0 authority hierarchy section
- Doctrine version log now renders dynamically from `/api/governance`
- Human authority log table updated with Tier 0/1/2/3 tags
- New JS functions wired for halt and doctrine proposal actions

### 2026-03-09 - Session 3 (Live Trading Workflow, Settlement Lifecycle)

**Bug Fix - Approve BUY order reappearing after click**
- Removed a duplicate synchronous `resolveDecision` function in `index.html`
- The async backend-integrated workflow now owns decision resolution

**Feature - Pre-Trade Routing Check Modal**
- Added `GET /api/decisions/<id>/pretrade`
- Five doctrine gate checks now return PASS / WARN / FAIL
- Frontend modal animates each gate result sequentially
- EXECUTE ORDER is blocked when any gate returns FAIL
- WARN conditions allow execution with review

**Feature - Post-Trade Execution Confirmation Modal**
- Added confirmation details for symbol, asset class, quantity, execution price, notional, settlement window, timestamp, decision ID, authority hash, and agent

**Fix - Settlement window corrected from T+2 to T+1**
- U.S. equities, FX, and fixed income now correctly show T+1 effective May 28, 2024
- Crypto remains T+0

**Fix - Settlement pipeline now respects asset class**
- T+1 trades no longer reach FULLY_SETTLED on trade date
- FULLY_SETTLED only transitions after next business day 17:30 ET
- Friday trades settle Monday
- Pipeline cards display T+0 or T+1 badge per trade
- Cash Available to Trade now reflects pending T+1 obligations

---

*Project Aureon · Guillermo "Bill" Ravelo · Columbia University MS Technology Management*
# aureon
