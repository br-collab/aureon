# Project Aureon - The Grid 3

**Doctrine Stack:** Aureon Consolidated Canonical Doctrine v1.6 · CAOM-001 · Cato (mixed: core v0.2.2 / cache v0.2.3) · AUR-CUSTODY-001 v1.0 · AUR-CUSTODY-CASH-001 v0.2
**Live Deployment:** [aureon-production.up.railway.app](https://aureon-production.up.railway.app) · Endowment Series I — Argus · $100M paper AUM
**Settlement & Custody Console:** [/cockpit](https://aureon-production.up.railway.app/cockpit) — pipeline, breaks workbench, and cash leg
**Status:** Paper trading · approaching institutional testing · no real capital at risk
**Classification:** Public prototype · full doctrine available under NDA

Aureon is a doctrine-governed control layer between portfolio intent and execution — built for the convergence of tokenization, AI execution, and programmable payment rails. It sits above OMS, EMS, and post-trade infrastructure. It governs what enters those systems, and it produces the unified lineage record a trustee, rating agency, or regulator can rely on.

This repository is the **Phase 1 Equities prototype** — a working implementation of the governance pattern with Electronic Execution as the first pilot motion. The full institutional doctrine spans eFICC (electronic Fixed Income, Currencies, and Commodities) post-trade with an eleven-role agent workforce specification. That broader specification is the v1.5.1 Consolidated Canonical Doctrine, available under NDA to qualified institutional counterparties.

In Phase 1, Aureon acts as a Decision System of Record (DSOR) before execution: it captures governed portfolio intent, applies policy and risk framing, records approval lineage, and packages evidence for downstream control, supervision, and replay.

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

### Why Equities Now, eFICC as the Doctrine Target

Equities is the first pilot surface because it offered the cleanest validation harness for the governance pattern. **The institutional doctrine target is eFICC post-trade** — where simultaneous regulatory deadline pressure is forcing every broker-dealer and asset manager to rebuild post-trade infrastructure at the same time:

- **Treasury cash clearing compliance** — December 2026
- **Repo clearing mandate** — June 2027
- **EU T+1 transition** — October 2027
- **DORA full enforcement** — already live, hitting fixed-income operations hardest because of OTC dependencies

Equities post-trade is largely solved at the institutional level — Aladdin, Bloomberg AIM, the major custodians cover it. eFICC is the opposite: every desk has its own conventions, every counterparty has its own rails, every regulator has different requirements. That fragmentation is precisely why a doctrine-first governance layer wins there. The control layer doesn't care about the underlying mess as long as the gates and the lineage hold.

Aureon went where the regulatory storm is hitting hardest, not where the sandbox was cleanest. Equities is the proof. eFICC is the deployment.

---

## Project Atreides — the custody and settlement estate

The pre-trade estate described above governs what *enters* the execution stack. **Project Atreides** is the post-trade half: an **AI-assisted multi-asset settlement governance layer with custodial routing**. It lives in its own repository, [`br-collab/Project-Atreides`](https://github.com/br-collab/Project-Atreides), and this repository consumes it as a **pinned dependency** rather than a copy.

Multi-asset is a scope claim the code carries: six securities rails, nine cash rails each with an explicit finality class, and three settlement kinds. Path selection runs across seven doctrine-defined dimensions — one of which is *depository membership versus sub-custodian intermediation*, weighed on operational efficiency, counterparty-risk concentration, jurisdictional compliance, and cost. Tier 2 agents enumerate from a pre-declared registry of 22 approved paths and **never construct a path at decision time**; an empty match escalates under `APPROVED_PATHS_ONLY` rather than improvising. The **cash leg** is where the implementation goes deepest — it is the centre of gravity, not the boundary.

Most post-trade tooling governs the securities side and treats the money as a consequence. A settlement has two legs; governing one and defaulting the other is a half-governed settlement. Atreides governs the second.

**The cardinal boundary, which is permanent rather than a stage of maturity:**

> Atreides prepares · governs · reconciles. **The entitled member submits.**

The framework holds no depository, CCP, or payment-system credential, opens no sessions, submits nothing, and scrapes no portal. An outside framework cannot lawfully interpose itself in a regulated member's submission, so the seat it occupies is governance, not execution. This is enforced at the type layer rather than by convention — `InstructionPackage` and `InstructionArtifact` both pin `is_submission` to `Literal[False]`, which makes a submission object *unconstructible* rather than merely discouraged. There is no `submit()` method anywhere in the package.

### What runs here

| Surface | Route | What it does |
| --- | --- | --- |
| Clearing Operator Cockpit | `/api/cockpit/*` (8 routes) | The operator cycle: gather → validate → prepare → *(member submits)* → reconcile. Beat 4 is permanently absent by design. |
| Funding-state model | `/api/cashleg/funding` | Can the leg settle at all? Returns FUNDED / WILL_QUEUE / WILL_FAIL / CAP_BREACH / CLEARING_FUND_DEFICIENT / INDETERMINATE. A queued gross-final instruction is **not** classified as a failure — re-issuing one creates an irreversible duplicate payment. |
| CATO-F — cash settlement-rail gate | `/api/cashleg/gate` | Deterministic PROCEED / HOLD / ESCALATE across Fedwire, CHIPS, FedNow, NSS, FICC/GSD, correspondent and tokenized rails. Emits a rail **and a finality class**. The cash-leg twin of Cato; the two share OFR STLFSI4 stress bands so that parity is structural rather than a matter of discipline. An absent gate resolves to HOLD, never PROCEED. |
| ISO 20022 emission | `/api/cashleg/instruction` | Rail → `SettlementMethod1Code` → a `pacs.009.001.13` instruction package with a `head.001.001.04` business application header, validated in CI against the published XSDs. |
| Settlement & Custody Console | `/cockpit` | The operator surface for all of the above. |

### Console layout

**Custody is the console, not a tab.** It has three elements: **Pipeline** (the governance spine — one custody operation through seven gates to an append-only decision-of-record, stopping at the first gate that holds), **Breaks Workbench** (the exception surface — symptom traced to proximate cause traced to originating event), and **Cash Leg** (funding feasibility, rail with finality class, ISO 20022 package). The securities leg and the cash leg both run the Pipeline's gates; Breaks Workbench is orthogonal to both.

### Package topology — a dependency, not a copy

`requirements.txt` declares:

```
atreides @ git+https://github.com/br-collab/Project-Atreides.git@v0.3.1
```

This repository holds **no vendored copy** of the custody domain layer. That is a deliberate reversal: the cockpit originally reached production by being copied across the repository boundary, which was the only move available while both packages defined a top-level module named `aureon`. The copy carried a transitive pydantic requirement this repository did not declare and took the deployment down with a Railway 502 on boot. The `atreides` rename removed the constraint; the determination is recorded in `AUR-ADD-006`.

The pin is an immutable tag, so a change on `Project-Atreides` `main` **cannot** reach this deployment without a deliberate version bump. That property was exercised in production on 31 July 2026: a doctrine-version correction on `main` was correctly invisible to the running system until the pin moved.

`aureon/dsor/bridge.py` is kept — it is the adapter between the two lineage models, not a duplicate.

### What is deliberately not built

Beat 4 — submission — permanently. Live rail execution, the quorum signature ceremony, and break actioning are roadmap; gate *decisions* are implemented and tested. Depository-specific ISO 20022 profiles (DTCC Settlement Client Interface, Fedwire ISO migration) are stubbed **UNVERIFIED** rather than guessed, because confirming them requires participant access to documentation behind MyDTCC. That is a commercial gate, not a technical one.

---

## Target Institutional Architecture

```text
Atrox — Alpha Origination (50,000 ft)
  Systematic signal generation, predictive analytics,
  market intelligence, product recommendations
  [Advisory only — all outputs require human approval]
                    |
                    v
      [HUMAN AUTHORITY — CAOM-001]
      Operator reviews and approves Atrox output
                    |
                    v
      Aureon Agent + Governance Layer
      Layer 0 - Verana  — Network Governance
        └── Cato — Live settlement-doctrine gate (open-source MCP, MIT)
      Layer 1 - Mentat  — Strategic Intelligence
      Layer 2 - Kaladan — Lifecycle Orchestration
      Layer 3 - Thifur-C2 — Command and Control
        └── Thifur-R — Deterministic Execution
        └── Thifur-J — Bounded Autonomy
        └── Thifur-H — Adaptive Intelligence
      Tier 0 — Emergency Halt (above all doctrine, any authority can trigger)
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

### Atrox — Alpha Generator (50,000 ft)

Atrox is the alpha origination layer. It is the highest-intelligence agent in the architecture — above the Thifur execution triplet, below human authority. Atrox does not execute. Atrox originates.

**Three domains:**
- **Trade Origination** — systematic signal generation, predictive analytics, cross-asset opportunity identification, 24/7 continuous monitoring
- **Market Intelligence** — real-time data synthesis across Twelve Data, Bloomberg, onchain flows, macro signals, regulatory publications, and alternative data
- **Product Recommendations** — identifies new strategies, instruments, and licensing opportunities based on persistent signal patterns and institutional demand signals

**Governance:** Every Atrox output is advisory. Full analytical lineage is required before any recommendation surfaces to human authority. No downstream agent receives a tasking without explicit operator approval. Atrox never self-executes under any condition.

**Named for:** Atrox. Executed blind into denied territory with incomplete information, zero margin for error, single objective. The agent operates with the same mandate.

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
Adaptive optimization for execution strategy, liquidity routing, collateral optimization, FX hedging, and repo. **Phase 2 first-light validation complete** — end-to-end signal cycle exercised against the live Kraken exchange under CAOM-001 sole-operator mode, with $10 position cap, $5 session-loss cap, XBTUSD-only whitelist, and post-only limit orders. Five-gate governance layer enforced and recorded (CAOM-001 authorization, symbol whitelist, position size, session drawdown, HITL); every gate evaluated for every signal regardless of upstream block, for SR 11-7 evidence completeness. Session ledger tracks orders by Kraken txid, supports per-order rollback, and exposes a MiFID II RTS 6 kill switch that cancels all open orders. The full Decision System of Record export from a 20-cycle validation protocol (5 clean execution, 15 intentional breach tests across symbol/size/authorization gates) is committed under `evidence/`. Exchange connectivity is direct Kraken REST with HMAC-SHA512 signing — no MCP intermediary on the live path.

### Governance Boundary

All Thifur agents operate under strict governance constraints:

- No agent initiates, approves, or releases trades
- All trades pass through pre-trade decision structuring within Aureon
- All trades pass through role-based human approvals (CAOM-001)
- Agent outputs are advisory and validated within the decision workflow
- Authority remains with human roles and governed control logic, never with agents

---

## Cato — The Live Verana Settlement-Doctrine Gate

Cato is the Verana L0 pre-settlement doctrine gate for tokenized institutional repo. It answers one question before every settlement: is atomic on-chain Delivery-versus-Payment viable right now, or should this trade route to FICC (Fixed Income Clearing Corporation)? The gate runs four deterministic checks and emits PROCEED, HOLD, or ESCALATE plus a recommended settlement rail.

Cato exists in two implementations that must produce bit-for-bit identical decisions for identical inputs: the external open-source MCP server (Node.js, MIT license, 23 tools at [github.com/br-collab/Cato---FICC-MCP](https://github.com/br-collab/Cato---FICC-MCP)) and the in-process Python twin inside Aureon. The deterministic parity is currently in a known mixed state and tracked in the open conflicts log.

**SR 11-7 Tier 1 backtest verified:** March 2020 COVID repo freeze (100%), September 2019 repo spike (80% post-fix), March 2023 SVB collapse (45.5% — documented calibration limit; Cato is a market-regime gate, not a counterparty-credit gate).

**Supported settlement rails:** FICC traditional, Ethereum L1, Base, Arbitrum, Solana — with the `fed_l1` placeholder reserved for a sovereign tokenized reserve rail - documented, non-functional, and pending an issuance that does not yet exist. PORTS is deliberately not listed as a rail: Perpetual Overnight Rate Treasury Securities (Duffie & Wilson, Brookings, December 2025) is an instrument proposal that would settle on the rails above, and its relevance to a settlement gate is second-order - a perpetual near-cash Treasury shifts repo substitution and intraday collateral velocity, changing the load on these rails rather than adding one. The GENIUS Act governs privately issued payment stablecoins, not central-bank money.

**The governance gate — not the rail — is the product.** When market structure shifts, Cato routes to the new rail. The doctrine does not change.

---

## Inherent-Safety, Axioms, and Failure-Mode Taxonomy (v1.5+)

The doctrine uses **inherent-safety** as a defined technical term, separate from its colloquial use. An inherent-safety surface is one where the failure mode requires multiple independent simultaneous failures to produce loss, each independently bounded under stated assumptions. This is the language regulators recognize from aviation safety, nuclear operations, and ISO 26262 functional-safety frameworks.

### The Ten Governance Axioms

The system enforces ten axioms on itself. They are not configurable. They may only be modified through the Doctrine Modification Governance workflow.

1. **Doctrine Before Execution** — no decision executes without doctrine version stamp, authority hash, and approval-lineage record
2. **Agents Advise, Operators Decide** — no agent at any layer holds approval authority
3. **Handoff Before Action** — no Thifur agent acts without recorded C2 handoff authorization
4. **One Lineage Record** — DSOR receives the C2-assembled unified lineage, never raw agent telemetry
5. **Doctrine Over Code** — smart-contract execution never overrides Mentat doctrine
6. **Escalation Completeness** — C2 never presents a partial picture to human authority
7. **Explainability Before Execution** — every Thifur-H action must be explainable in human-readable terms
8. **Verana Autonomous Block** — Verana is the only layer authorized to autonomously block
9. **Tier 0 Emergency Halt Above All Doctrine** — any authority can trigger; freezes all execution immediately
10. **Inherent-Safety Surfaces Require Architectural Impossibility of Single-Point Failure** — no single authority, component, signature, key, jurisdiction, or counterparty may sit on the loss path

### Three-Class Failure-Mode Taxonomy

Every failure surface classifies as one of three recoverability classes:

- **RA — Recoverable Automatic:** detected and recovered by the system without human action; lineage continuous across the event
- **RM — Recoverable Manual:** detected and recovered with explicit human action; lineage may carry a flagged gap requiring manual reconciliation
- **UR — Unrecoverable:** failure produces loss that cannot be undone; **must not be reachable on inherent-safety surfaces** (Axiom 10)

### Quorum Authority — Future Mode

Quorum authority is defined as the architectural prerequisite for institutional custody operations of material magnitude (large transfers, key ceremonies, encumbrance changes, lien releases, cold-storage rotations). Single-authority approval on these operations is an inherent-safety violation under Axiom 10. **Explicitly out of scope under CAOM-001** because single-operator three-tier signing does not meet separation-of-duties architecturally. v1.6 (custody) will operationalize the primitive within the custody domain.

---

## Tier 0 — Emergency Halt

The Emergency Halt is a Tier 0 authority that sits **above** the three-tier CAOM-001 structure. Any authority can trigger it. When Halt is active, all Thifur execution is frozen immediately — R, J, and any future H domain — regardless of what other authorities or doctrine versions are active.

Halt state carries its own immutable lineage: activation timestamp, invoking authority, stated reason. Resumption requires explicit operator action and generates a doctrine-change-style audit record.

**Endpoints:** `POST /api/halt`, `GET /api/halt`, `POST /api/halt/resume`.

The architectural invariant: a human can always stop the system; the system can never stop a human from stopping the system.

---

## Doctrine Model With Institutional Translation

| Doctrine Name | Altitude | Institutional Translation | Phase 1 Responsibility |
|---------------|----------|---------------------------|------------------------|
| **Tier 0 Halt** | Above all | Constitutional circuit breaker | Any authority freezes all execution; outside the three-tier hierarchy |
| **Atrox** | 50,000 ft | Alpha origination and market intelligence layer | Signal generation, predictive analytics, product recommendations — advisory only |
| **Mentat** | 30,000 ft | Decision-intelligence and portfolio reasoning layer | Intent synthesis, scenario support, strategy-context framing, doctrine boundaries |
| **Kaladan** | 10,000 ft | Lifecycle and evidence orchestration layer | Approval lineage, evidence packaging, replay context, downstream status attachment |
| **Thifur-C2** | 1,000 ft | Command and Control coordination layer | Sequencing, handoff coordination, unified lineage assembly |
| **Thifur-R/J/H** | 500 ft | Trader and execution-support bounded agentics layer | Deterministic execution, bounded autonomy, adaptive intelligence — all advisory |
| **Verana** | Ground | Control and governance boundary layer | Session controls, policy boundary enforcement, supervisory control posture |
| **Cato** | Verana L0 | Live settlement-doctrine gate | Pre-settlement DvP viability check; PROCEED/HOLD/ESCALATE; rail recommendation |

Doctrine names should always be read alongside these institutional translations, not as free-floating abstractions.

---

## CAOM-001 — Consolidated Authority Operating Mode

Aureon operates under CAOM-001 for sole-operator deployment. The operator holds all three human authority tiers simultaneously:

- **Tier 0** — Emergency Halt (constitutional, above all doctrine)
- **Tier 1** — Trader / Risk Manager / Portfolio Manager approval gates
- **Tier 2** — Compliance / Doctrine authority
- **Tier 3** — Executive / Systemic risk decisions

No agent substitutes for human authority at any tier. Every approval action is stamped with the CAOM-001 operating mode identifier and recorded in the DSOR.

**CAOM-001 is not a workaround.** It is a defined, doctrine-consistent operating mode purpose-built for solo fund operators running a one-person shop with AI agents filling operational roles. All Human Authority Doctrine requirements remain in force under CAOM. The difference is in how roles are assigned — not in whether governance applies.

**Transition triggers** out of CAOM include: AUM exceeds $10M (formal Risk Manager review), external investor capital onboarding (Compliance Officer separation required — CAOM is incompatible with third-party investor governance), regulatory examination scheduled, first institutional staff hire, strategy licensing to a third party, **or any operation the doctrine flags as quorum-required** (custody operations of material magnitude).

---

## System Boundaries

### Aureon Owns

- governed portfolio intent formation before execution
- pre-trade policy, mandate, and control checks
- risk framing and constraint visibility for human review
- configurable role-based approval lineage
- DSOR evidence, replay context, and audit packaging
- Atrox origination intelligence — advisory layer above execution
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

- Atrox originates. The operator approves.
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
| Atrox | 6 data pipes live (Unusual Whales, Tradier, Alpaca, CBOE, EDGAR, Blockscout) + dashboard tab | Full production activation with trade origination |
| Thifur-C2 | Declared — coordination architecture specified | Full multi-agent coordination live |
| Thifur-R | Core settlement determinism active | Full clearing governance, cross-border rails |
| Thifur-J | Pre-trade structuring, policy checks | Full tokenized asset lifecycle, DeFi convergence |
| Thifur-H | **Phase 2 validated** — five-gate governance layer live on Kraken, 20-cycle protocol passed end-to-end (5 clean execution + 15 breach tests), DSOR evidence committed under `evidence/`, SR 11-7 Tier 1 | VWAP/TWAP/POV recommendations, multi-venue expansion, tokenized equity rails |
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
- Atrox alpha origination layer with 6 live data pipes (options flow, dark pool, VIX fear gauge, market snapshots, institutional 13F, on-chain intelligence)
- MCP server (Verana L0) exposing 5 governance resources and 4 compliance tools to external AI agents
- Atrox dashboard tab with pipe status, fear gauge, flow intelligence, and on-chain data
- Settlement & Custody Console at `/cockpit` — governance pipeline, breaks workbench, and a full cash-leg path
- cash-leg governance end to end: funding-state model, CATO-F rail gate with finality class, and a schema-validated ISO 20022 `pacs.009.001.13` instruction package
- the custody domain layer consumed as a pinned external dependency rather than vendored, with the submission boundary enforced at the type layer

The current implementation is still technically compressed. The backend is centered in `server.py`, the UI is concentrated in `index.html`, and several concerns remain co-located for prototype speed. That structural compression is a repository limitation, not the target product architecture.

---

## Current Repository Structure

```text
repository root/
  server.py                            backend orchestration, state, governance, HTTP surface
  index.html                           Phase 1 pre-trade operator dashboard
  atreides-settlement-dashboard.html   Settlement & Custody Console, served at /cockpit
  requirements.txt                     declares `atreides` as a pinned git dependency
  gunicorn.conf.py  Procfile  railway.json  runtime.txt
  scripts/  evidence/  parity/  Thought notes/

  aureon/
    thifur/            CANONICAL Thifur-H code path — advisory mode, live Kraken account
      thifur_h.py  agent_h.py  atrox_live.py  atrox_sandbox.py  kraken_client.py
    agents/            agent base, CAOM wiring, payloads; c2/ jtac/ ranger/ subtrees
    dsor/              bridge.py — adapter between this repo's lineage model and Atreides'
    doctrine/          doctrine sources, conflicts register, JTAC path-sets
    config/            caom.py · atrox.py · thifur_c2_doctrine.py · settings.py
    mcp/               MCP server (Verana L0) + data pipes: atrox, tradier, alpaca,
                       cboe, edgar, blockscout, cato
    policy_engine/     policy and mandate evaluation
    approval_service/  release control, routing, approval lineage
    evidence_service/  evidence packaging for supervision and replay
    integration_adapters/  oms_adapter.py · ems_adapter.py · fix_adapter.py
    persistence/  core/  data/  cli/  session/  mmf/
```

**What is deliberately absent.** There is no `aureon/cockpit/`, no `aureon/agents/tier1/`, and no `aureon/contracts/`. Those directories existed until 31 July 2026 as vendored copies of the Atreides custody domain layer, and were retired in favour of the declared dependency in `requirements.txt` per `AUR-ADD-006`. Do not reintroduce them — a copy of a module that has an authoritative home elsewhere is the failure mode that produced a Railway 502 on boot when it carried a transitive dependency this repository did not declare.

Current file roles:

- `server.py`: backend orchestration, state, governance logic, and API routes — including the eight `/api/cockpit/*` routes, the four `/api/cashleg/*` routes, and the Thifur-H session surface
- `index.html`: Phase 1 pre-trade operator dashboard
- `atreides-settlement-dashboard.html`: Settlement & Custody Console — pipeline, breaks workbench, cash leg
- `aureon/thifur/`: the canonical Thifur-H implementation. Advisory mode is active in deployment under CAOM-001 human-in-the-loop approval; autonomous mode is declared and not activated, gated on independent SR 11-7 Tier 1 validation and EU AI Act registration per `AUR-CANONICAL-001 v1.6 §II`
- `aureon/dsor/bridge.py`: the lineage adapter. Kept deliberately — it is not a duplicate of anything in Atreides
- `aureon/config/caom.py`: CAOM-001 Consolidated Authority Operating Mode configuration
- `aureon/mcp/server.py`: MCP server — Phase 1 Verana L0 (JSON-RPC 2.0 over HTTP, `POST /mcp`)
- `aureon/integration_adapters/fix_adapter.py`: FIX translation stub for the OMS/EMS integration boundary

The backend remains centred in `server.py` and the pre-trade UI in `index.html`; several concerns are still co-located for prototype speed. That structural compression is a repository limitation, not the target product architecture. A later phase will separate decision orchestration, policy and risk checks, approvals, integration adapters, evidence services, presentation, and infrastructure concerns.

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
| **Atrox** | External market data pipes, alternative data, onchain feeds via MCP | Structured, auditable data ingestion with full provenance — replaces raw API polling |
| **Mentat L1** | Regulatory publication feeds, SEC/ESMA/FRB document streams | Doctrine updates require traceable source documents |
| **Verana L0** | OFAC SDN list updates, DORA/MiFID II regulatory change feeds | Network Registry must absorb external regulatory changes with lineage |

---

### Verana L0 — Phase 1 Connection Schema

```
MCP Client (Claude Desktop / external agent / Atrox)
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

### Atrox — External Data Pipe Architecture

Atrox is the highest-intelligence origination agent in the architecture. In Phase 1 activation, Atrox consumes external data sources via structured data pipe clients — giving every data input a structured, auditable provenance trail. Six pipes are currently live.

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
  Atrox (MCP Client)
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

**Why MCP for Atrox's data pipes:**
- Every data source is a named, versioned MCP resource — not a raw API call
- Full provenance trail: which data, from which server, at which timestamp
- If a regulator asks "what data did Atrox use for this recommendation?" — the MCP resource URI is the answer
- Same HITL guardrail applies: Atrox synthesizes, operator approves, nothing executes autonomously

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
- Atrox data pipes are implemented (6 live pipes: Unusual Whales, Tradier, Alpaca, CBOE, EDGAR, Blockscout); full production activation pending regulatory validation
- Thifur-C2 is fully specified at the doctrine level — coordination implementation is the next phase
- The codebase is still structurally compressed and does not yet reflect the target service boundaries
- FIX support is a translation stub, not a live broker, EMS, or OMS session
- Thifur-H Phase 2 activated — five-gate governance layer live, Kraken live account validation in progress under CAOM-001, 20-cycle stress test protocol executing, DSOR export active for SR 11-7 evidence packaging; production expansion pending full validation cycle completion
- The repository should be read as an institutional product prototype, not as a claim of full OMS, SOR, treasury, settlement, or books-and-records replacement

---

## Long-Term Direction

The long-term ambition is to expand Aureon into a broader institutional decision and governance layer across additional workflows, desks, and asset classes. The commercial path is **licensing the governance layer, not operating a fund** — through three deployment modes: governance overlay above existing OMS infrastructure, full-stack doctrine OS for greenfield builds, or pure compliance artifact engine where every decision returns a replayable regulatory submission package.

The structural advantage: when market structure shifts (PORTS ships, GENIUS Act passes, Fed L1 tokenized reserves go live), the doctrine does not change. The rail does.

The near-term objective is much narrower and more credible:

- prove Electronic Execution as the first GSIB-ready pilot
- establish Aureon as the DSOR before execution
- demonstrate clean boundaries with OMS, EMS, SOR, and downstream post-trade systems
- build trust through governed approvals, replayability, and evidence quality
- activate Atrox as the alpha origination layer on live data pipes
- complete Thifur-H 20-cycle validation against Kraken live account and advance to full $500 live capital deployment
- ship v1.6 (custody) — the next major doctrine addition, anchored on Axiom 10 and the quorum authority primitive

---

*Project Aureon · Guillermo "Bill" Ravelo · Columbia University M.S. Technology Management · Capstone Doctrine Publication*
*The Grid 3 · v1.5.1 · CAOM-001 · Crawl Phase — Paper Trade Data Collection · Thifur-H Phase 2 Activated*
*Full Consolidated Canonical Doctrine v1.5.1 available under NDA to qualified institutional counterparties.*
