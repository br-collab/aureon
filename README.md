# Project Aureon - The Grid 3

Aureon is an Equities-first agentic pre-trade governance and execution-intelligence platform.

It is designed to sit between portfolio intent and the incumbent OMS/EMS stack as a governed decision layer, not to replace OMS, EMS, SOR, or post-trade infrastructure. In Phase 1, Aureon acts as a Decision System of Record (DSOR) before execution: it captures governed portfolio intent, applies policy and risk framing, records approval lineage, and packages evidence for downstream control, supervision, and replay.

The current repository is a prototype implementation of that model. It demonstrates the governance layer, approval workflow, risk and policy checks, evidence surfaces, and OMS/EMS handoff concepts needed for an Electronic Execution pilot.

---

## Why This Exists

Institutional pre-trade workflows are often fragmented across research inputs, portfolio intent, trader judgment, mandate constraints, risk checks, compliance interpretation, and approval workflows. Execution systems are typically strong at routing and lifecycle management, but weaker at preserving a single governed record of:

- what investment intent was being expressed
- which constraints applied at the moment of release
- how risk and policy considerations were framed
- who approved the decision and under what role authority
- what evidence can be replayed later for supervision, challenge, and audit

Aureon exists to make that pre-trade decision layer explicit. It creates a governed intent packet before the order enters the execution stack, so firms can improve control, explainability, and supervisory confidence without replacing the OMS/EMS environments they already trust.

---

## Phase 1 Deployment Position

Phase 1 positions Aureon as a governance and execution-intelligence overlay for Equities, with Electronic Execution as the first pilot motion.

In that deployment model, Aureon:

- captures portfolio intent from PM, signal, model, or research inputs
- structures that intent into a governed pre-trade decision record
- applies policy, mandate, and risk framing before release
- routes approvals through configurable role-based human review
- hands approved intent into OMS or EMS workflows for execution
- ingests execution status back for replay, evidence, and control packaging

Aureon augments OMS/EMS. It does not replace order staging, venue routing, parent-order lifecycle management, execution algorithms, broker connectivity, or legal books and records.

---

## Target Institutional Architecture

```text
Neptune Spear — Alpha Origination (50,000 ft)
  Systematic signal generation, predictive analytics,
  market intelligence, product recommendations
  [Advisory only — all outputs require human approval]
                    |
                    v
      [HUMAN AUTHORITY — CAOM-001]
      Operator reviews and approves Neptune output
                    |
                    v
      Aureon Agent + Governance Layer
      Layer 0 - Verana  — Network Governance
      Layer 1 - Mentat  — Strategic Intelligence
      Layer 2 - Kaladan — Lifecycle Orchestration
      Layer 3 - Thifur-C2 — Command and Control
        └── Thifur-R — Deterministic Execution
        └── Thifur-J — Bounded Autonomy
        └── Thifur-H — Adaptive Intelligence
                    |
                    v
           OMS / Order Staging
                    |
                    v
          EMS / Trader Workflow
                    |
                    v
     SOR / Broker / Venue Connectivity
                    |
                    v
Exchanges / ATS / Internalization Venues
                    |
                    v
Post-Trade / Clearing / Custody / Settlement
                    |
                    v
Status / fills / breaks / confirms returned to Aureon
for replay, supervisory evidence, and audit packaging
```

---

## Agent Architecture

### Neptune Spear — Alpha Generator (50,000 ft)

Neptune Spear is the alpha origination layer. It is the highest-intelligence agent in the architecture — above the Thifur execution triplet, below human authority. Neptune does not execute. Neptune originates.

**Three domains:**
- **Trade Origination** — systematic signal generation, predictive analytics, cross-asset opportunity identification, 24/7 continuous monitoring
- **Market Intelligence** — real-time data synthesis across Twelve Data, Bloomberg, onchain flows, macro signals, regulatory publications, and alternative data
- **Product Recommendations** — identifies new strategies, instruments, and licensing opportunities based on persistent signal patterns and institutional demand signals

**Governance:** Every Neptune output is advisory. Full analytical lineage is required before any recommendation surfaces to human authority. No downstream agent receives a tasking without explicit operator approval. Neptune never self-executes under any condition.

**Named for:** Operation Neptune Spear. Executed blind into denied territory with incomplete information, zero margin for error, single objective. The agent operates with the same mandate.

---

### Thifur-C2 — Command and Control (1,000 ft)

Thifur-C2 is the coordination layer between Kaladan's governed intent packet and the Thifur execution triplet. C2 does not execute. C2 does not interpret doctrine. C2 sequences, coordinates handoffs, assembles unified lineage, and presents a single human authority surface across all execution agents simultaneously.

**Five Immutable Stops:**
1. No self-execution — C2 never takes a market action under any condition
2. No doctrine interpretation — doctrine questions escalate to Mentat, never to C2
3. Handoff before action — no Thifur agent acts without a recorded C2 handoff authorization
4. One lineage record — DSOR never receives raw agent telemetry without C2 assembly
5. Escalation completeness — C2 never escalates a partial picture to human authority

**C2 is the architectural answer to the TradFi-DeFi convergence problem.** When a lifecycle object simultaneously requires deterministic rail execution (Thifur-R), programmable asset governance (Thifur-J), and adaptive optimization (Thifur-H), C2 holds the unified picture across all three.

---

### Thifur — Execution Intelligence Layer (500 ft)

Thifur is Aureon's execution intelligence layer, operating as a bounded agentic layer within the governed framework. Thifur enhances execution decision quality but does not possess authority over trade initiation, approval, or release.

**Three execution agents:**

**Thifur-R — Ranger — Deterministic Execution**
Strict determinism. Zero variance permitted. The same input always produces the same output. Governs clearing, settlement, post-trade reconciliation, corporate actions, regulatory reporting. Makes the Citi Revlon $900M wire error structurally impossible.

**Thifur-J — JTAC — Bounded Autonomy**
Governs the TradFi-DeFi convergence zone. Manages tokenized asset lifecycle and multi-constraint flows. Selects among approved paths — never generates new ones. Doctrine always overrides smart contract execution logic.

**Thifur-H — Hunter-Killer — Adaptive Intelligence**
Adaptive optimization for execution strategy, liquidity routing, collateral optimization, FX hedging, and repo. Declared at architectural level. Phase 2 activation pending independent validation per SR 11-7 Tier 1 requirements.

### Governance Boundary

All Thifur agents operate under strict governance constraints:

- No agent initiates, approves, or releases trades
- All trades pass through pre-trade decision structuring within Aureon
- All trades pass through role-based human approvals (CAOM-001)
- Agent outputs are advisory and validated within the decision workflow
- Authority remains with human roles and governed control logic, never with agents

---

## Doctrine Model With Institutional Translation

| Doctrine Name | Altitude | Institutional Translation | Phase 1 Responsibility |
|---------------|----------|---------------------------|------------------------|
| **Neptune Spear** | 50,000 ft | Alpha origination and market intelligence layer | Signal generation, predictive analytics, product recommendations — advisory only |
| **Verana** | Ground | Control and governance boundary layer | Session controls, policy boundary enforcement, supervisory control posture |
| **Mentat** | 30,000 ft | Decision-intelligence and portfolio reasoning layer | Intent synthesis, scenario support, strategy-context framing, doctrine boundaries |
| **Kaladan** | 10,000 ft | Lifecycle and evidence orchestration layer | Approval lineage, evidence packaging, replay context, downstream status attachment |
| **Thifur-C2** | 1,000 ft | Command and Control coordination layer | Sequencing, handoff coordination, unified lineage assembly |
| **Thifur-R/J/H** | 500 ft | Trader and execution-support bounded agentics layer | Deterministic execution, bounded autonomy, adaptive intelligence — all advisory |

Doctrine names should always be read alongside these institutional translations, not as free-floating abstractions.

---

## CAOM-001 — Consolidated Authority Operating Mode

Aureon operates under CAOM-001 for sole-operator deployment. The operator holds all three human authority tiers simultaneously:

- **Tier 1** — Trader / Risk Manager / Portfolio Manager approval gates
- **Tier 2** — Compliance / Doctrine authority
- **Tier 3** — Executive / Systemic risk decisions

No agent substitutes for human authority at any tier. Every approval action is stamped with the CAOM-001 operating mode identifier and recorded in the DSOR.

---

## System Boundaries

### Aureon Owns

- governed portfolio intent formation before execution
- pre-trade policy, mandate, and control checks
- risk framing and constraint visibility for human review
- configurable role-based approval lineage
- DSOR evidence, replay context, and audit packaging
- Neptune Spear origination intelligence — advisory layer above execution
- Thifur-C2 coordination and unified lineage assembly
- controlled AI-assisted workflow support inside governed tasks

### OMS Owns

- order staging and blotter state
- allocations and parent-order lifecycle management
- order state management after release from Aureon

### EMS Owns

- trader execution workflow
- execution strategy and algo choice
- trader controls and venue interaction

### Outside Aureon in Phase 1

- smart order routing and venue connectivity
- broker/exchange session ownership and SOR responsibilities
- legal books and records
- clearing, custody, treasury, and settlement system ownership
- post-trade system-of-record responsibilities

---

## AI and Governance Position

Aureon is designed to support the controlled use of bounded agentics within defined workflows — not unrestricted automation.

The critical architectural principle: **intelligence and authority are explicitly separated.**

- Neptune Spear originates. The operator approves.
- Mentat reasons. The operator decides.
- Kaladan structures. The operator releases.
- Thifur executes. Within bounds the operator has pre-approved.

No agent in the architecture crosses from intelligence into authority. That separation is not a configuration option — it is the doctrine.

---

## Regulatory Alignment

Aureon's governance architecture is mapped against six regulatory frameworks:

| Framework | Coverage |
|-----------|----------|
| SR 11-7 | Federal Reserve model risk management — Thifur-H and Thifur-J classified Tier 1 |
| OCC 2023-17 | Third-party risk management — Verana Network Registry as critical activity classification framework |
| BCBS 239 | Risk data aggregation — Kaladan data architecture standards across all four BCBS dimensions |
| MiFID II RTS 6 | Algorithmic trading controls — kill switch, algorithm inventory, annual self-assessment |
| EU AI Act | High-risk AI — conformity assessment, human oversight, post-market monitoring |
| DORA | Digital operational resilience — three-level testing programme, RTO/RPO per critical function |

---

## Phase 1 vs Later

| Area | Phase 1 Deployable | Later Expansion |
|------|--------------------|-----------------|
| Asset scope | Equities-first | Program Trading, Delta One, OTC, all asset classes |
| Primary pilot | Electronic Execution | Broader cross-desk rollout |
| Neptune Spear | Declared — architectural specification complete | Full activation with live data pipe integration |
| Thifur-C2 | Declared — coordination architecture specified | Full multi-agent coordination live |
| Thifur-R | Core settlement determinism active | Full clearing governance, cross-border rails |
| Thifur-J | Pre-trade structuring, policy checks | Full tokenized asset lifecycle, DeFi convergence |
| Thifur-H | Declared — not activated | VWAP/TWAP/POV recommendations, Phase 2 |
| AI usage | Controlled, role-bound workflow support with HITL | Expanded supervised agent coverage |
| Regulatory | SR 11-7 Tier 2, OCC 2023-17, BCBS 239 P3/P5 | Full six-framework coverage |

---

## What The Prototype Demonstrates Today

- a lightweight DSOR-style pre-trade decision workflow
- doctrine and governance surfaces for reviewable decisions
- human approval flow with attributable control points under CAOM-001
- pre-trade routing and control checks
- OMS-overlay exploration through FIX translation stubs
- evidence and reporting surfaces tied to decision lineage
- dashboard views for governance, decisions, and downstream status visibility
- email reporting pipeline for governed trade confirmation
- live paper trading on Railway production deployment

The current implementation is still technically compressed. The backend is centered in `server.py`, the UI is concentrated in `index.html`, and several concerns remain co-located for prototype speed. That structural compression is a repository limitation, not the target product architecture.

---

## Current Repository Structure

```text
The Grid 3/
  README.md
  server.py
  index.html
  fix_adapter.py
  setup_launch_agent.sh
  aureon_state_persist.json
  scripts/
  Thought notes/
  aureon/
    config/
      caom.py
      neptune_spear.py
      thifur_c2_doctrine.py
    mcp/
      __init__.py
      server.py
    session/
      session_protocol.py
    approval_service/
      release_control.py
```

Current file roles:

- `server.py`: prototype backend orchestration, state, governance logic, and API routes
- `index.html`: prototype dashboard and operator workflow UI
- `fix_adapter.py`: FIX translation stub for OMS/EMS integration boundary exploration
- `aureon_state_persist.json`: local persisted runtime state
- `aureon/config/caom.py`: CAOM-001 Consolidated Authority Operating Mode configuration
- `aureon/config/neptune_spear.py`: Thifur-Neptune Spear doctrine declaration and knowledge base text
- `aureon/config/thifur_c2_doctrine.py`: Thifur-C2 Command and Control doctrine declaration
- `aureon/mcp/server.py`: MCP server — Phase 1 Verana L0 (JSON-RPC 2.0 over HTTP, `POST /mcp`)
- `aureon/session/session_protocol.py`: six-step session auto-complete protocol
- `aureon/approval_service/release_control.py`: governed release control and approval lineage
- `scripts/`: local startup helpers

Phase 5 will refactor this structure to better separate decision orchestration, policy/risk checks, approvals, integration adapters, evidence services, presentation, and infrastructure concerns.

---

## MCP Integration Layer

Aureon exposes a Model Context Protocol (MCP) server, enabling external AI agents, Claude Desktop, and data infrastructure to interact with the governance stack through a structured, auditable interface. The MCP layer does not bypass doctrine — every resource read and tool call reflects live system state and authority constraints.

**Transport:** Streamable HTTP — JSON-RPC 2.0 over `POST /mcp`  
**Discovery:** `GET /mcp` returns server info and capability index  
**Spec:** MCP protocol version `2024-11-05`

---

### MCP Server Agents (expose resources + tools)

| Agent | Phase | Endpoint | What It Exposes |
|---|---|---|---|
| **Verana L0** | Phase 1 — Live | `POST /mcp` | Network Registry, Regulatory Frameworks, OFAC Screening List, Compliance Alerts, Doctrine Status |
| **Kaladan L2** | Phase 2 — Planned | `POST /mcp` | DSOR records, approval lineage, lifecycle status, evidence packages |
| **Thifur (R/J/H/C2)** | Phase 3 — Planned | `POST /mcp` | Advisory outputs, handoff records, unified lineage, execution telemetry |

### MCP Client Agents (consume external MCP servers)

| Agent | What It Consumes | Why |
|---|---|---|
| **Neptune Spear** | External market data pipes, alternative data, onchain feeds via MCP | Structured, auditable data ingestion with full provenance — replaces raw API polling |
| **Mentat L1** | Regulatory publication feeds, SEC/ESMA/FRB document streams | Doctrine updates require traceable source documents |
| **Verana L0** | OFAC SDN list updates, DORA/MiFID II regulatory change feeds | Network Registry must absorb external regulatory changes with lineage |

---

### Verana L0 — Phase 1 Connection Schema

```
MCP Client (Claude Desktop / external agent / Neptune Spear)
  │
  │  POST /mcp
  │  Content-Type: application/json
  │  {"jsonrpc": "2.0", "id": "1", "method": "initialize", "params": {...}}
  │
  ▼
Aureon MCP Server (aureon/mcp/server.py)
  │
  ├── resources/list     → 5 Verana resources
  ├── resources/read     → live aureon_state data
  ├── tools/list         → 4 Verana tools
  └── tools/call         → governed tool execution
```

**Resources available:**

```
aureon://verana/network-registry        — node counts, agent roster, doctrine version
aureon://verana/regulatory-frameworks   — SR 11-7, OCC 2023-17, BCBS 239, MiFID II, DORA, EU AI Act
aureon://verana/ofac-screening-list     — OFAC SDN blocked identifiers with sanction basis
aureon://verana/compliance-alerts       — live alert feed, drawdown state, halt status
aureon://verana/doctrine-status         — doctrine version, audit hash, version log
```

**Tools available:**

```
verana_screen_ofac(identifier)          — Gate 5 OFAC SDN screen — returns PASS or BLOCKED
verana_framework_status(framework)      — query specific regulatory framework status
verana_node_status()                    — network operational posture
verana_compliance_snapshot()            — full Verana governance picture in one call
```

**Example — initialize:**
```json
POST /mcp
{"jsonrpc": "2.0", "id": "1", "method": "initialize",
 "params": {"protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "claude-desktop", "version": "1.0"}}}
```

**Example — OFAC screen:**
```json
{"jsonrpc": "2.0", "id": "2", "method": "tools/call",
 "params": {"name": "verana_screen_ofac", "arguments": {"identifier": "MSFT"}}}
```

**Example — read network registry:**
```json
{"jsonrpc": "2.0", "id": "3", "method": "resources/read",
 "params": {"uri": "aureon://verana/network-registry"}}
```

---

### Neptune Spear — External Data Pipe Architecture

Neptune Spear is the highest-intelligence origination agent in the architecture. In Phase 2 activation, Neptune consumes external data sources via MCP clients — giving every data input a structured, auditable provenance trail.

```
External Data Sources (MCP Servers)
  ├── Market Data MCP      — Twelve Data / Bloomberg feeds structured as MCP resources
  ├── Onchain Data MCP     — DeFi protocol state, token flows, liquidity depth
  ├── Macro Intelligence MCP — Fed publications, ECB releases, BIS working papers
  ├── Alternative Data MCP — satellite, credit card, shipping, sentiment feeds
  └── Regulatory Feed MCP  — SEC EDGAR, ESMA register, FRB supervisory publications
          │
          │  MCP resources/read + tools/call
          ▼
  Neptune Spear (MCP Client)
  Synthesizes across all feeds → generates investment thesis
          │
          │  Recommendation + full analytical lineage
          ▼
  Human Authority (CAOM-001 operator approval required)
          │
          │  Approved output
          ▼
  Kaladan L2 → Thifur-C2 → R / J / H
```

**Why MCP for Neptune's data pipes:**
- Every data source is a named, versioned MCP resource — not a raw API call
- Full provenance trail: which data, from which server, at which timestamp
- If a regulator asks "what data did Neptune use for this recommendation?" — the MCP resource URI is the answer
- Same HITL guardrail applies: Neptune synthesizes, operator approves, nothing executes autonomously

---

### Phase 2 — Kaladan DSOR Records Schema (planned)

```
aureon://kaladan/dsor/{decision_id}     — full governed decision record
aureon://kaladan/dsor/recent            — last 50 DSOR records
aureon://kaladan/lifecycle/{id}         — lifecycle object state
aureon://kaladan/evidence/{id}          — compliance evidence package
```

### Phase 3 — Thifur Advisory Outputs Schema (planned)

```
aureon://thifur/c2/status               — C2 operational status, active tasks
aureon://thifur/c2/handoff-log          — recent handoff records
aureon://thifur/r/settlement/{id}       — settlement preparation package
aureon://thifur/j/pretrade/{id}         — pre-trade structuring output
```

Tools planned:
```
thifur_c2_get_lineage(task_id)          — retrieve unified lineage record
thifur_j_pretrade_screen(decision)      — run pre-trade gate sequence
thifur_r_settlement_status(decision_id) — settlement readiness check
```

---

## Production Deployment

Live at: `https://aureon-production.up.railway.app`

Hosted on Railway with Gunicorn. State persisted via Railway Volume at `/data`.

Environment variables required:
```
TWELVE_DATA_API_KEY     — primary market data (Twelve Data)
AUREON_EMAIL            — Gmail SMTP sender
AUREON_EMAIL_PW         — Gmail app password (not account password)
AUREON_EMAIL_RECIPIENT  — report delivery address
RAILWAY_VOLUME_MOUNT_PATH — persistent state path (/data)
```

Market data: Twelve Data primary, yfinance fallback, 60-second price cache.

---

## Quick Start (Local)

From the repository root:

```bash
pip install flask yfinance reportlab python-dotenv
./scripts/start.sh
```

Alternative:

```bash
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
TWELVE_DATA_API_KEY=your_key
```

---

## Current Limitations

- The system is a prototype and does not yet implement production-grade persistence, resiliency, or control architecture
- Neptune Spear and Thifur-C2 are fully specified at the doctrine level — code implementation is the next phase
- The codebase is still structurally compressed and does not yet reflect the target service boundaries
- FIX support is a translation stub, not a live broker, EMS, or OMS session
- Thifur-H is declared but not activated pending independent validation
- The repository should be read as an institutional product prototype, not as a claim of full OMS, SOR, treasury, settlement, or books-and-records replacement

---

## Long-Term Direction

The long-term ambition is to expand Aureon into a broader institutional decision and governance layer across additional workflows, desks, and asset classes — including the Arcadia Fund as a live systematic arbitrage proof of concept and potential licensing of named strategy modules to institutional counterparties.

The near-term objective is much narrower and more credible:

- prove Electronic Execution as the first GSIB-ready pilot
- establish Aureon as the DSOR before execution
- demonstrate clean boundaries with OMS, EMS, SOR, and downstream post-trade systems
- build trust through governed approvals, replayability, and evidence quality
- activate Neptune Spear as the alpha origination layer on live data pipes

---

*Project Aureon · Guillermo "Bill" Ravelo · Columbia University MS Technology Management*
*The Grid 3 · CAOM-001 · Crawl Phase — Paper Trade Data Collection*
