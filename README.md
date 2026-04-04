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
Research / PM Intent / Signals / Thesis Input
                    |
                    v
      Aureon Agent + Governance Layer
      - intent formation
      - policy and mandate checks
      - risk framing
      - approval lineage
      - governance evidence / replay
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

## Thifur - Execution Intelligence Layer (Bounded Agentics)

Thifur is Aureon's execution intelligence layer, designed to assist with execution strategy selection, routing optimization, and post-trade feedback analysis within a governed framework.

Thifur operates as a bounded agentic layer embedded within Aureon. It enhances execution decision quality but does not possess authority over trade initiation, approval, or release.

### Governance Boundary

Thifur operates under strict governance constraints:

- Thifur agents cannot initiate, approve, or release trades
- All trades must pass through pre-trade decision structuring within Aureon
- All trades must pass through role-based human approvals
- All trades must pass through governed release control
- Agent outputs are advisory and must be validated within the decision workflow
- Authority remains with human roles and governed control logic, not with agents

Aureon enforces a clear separation between:

- intelligence (Thifur bounded agentic systems)
- authority (human and governed control layers)

### Defined Capabilities (Not Activated)

Thifur capabilities are defined at the architectural level but are not activated in the current prototype.

Intended capabilities include:

- execution strategy recommendation such as VWAP, TWAP, and POV
- liquidity-aware execution timing analysis
- venue and routing optimization support
- post-trade execution quality feedback and telemetry

These capabilities require:

- real-time market data feeds
- venue connectivity
- execution telemetry integration

Thifur is therefore a declared capability and not an active execution component in the current system.

### Control Principle

No trade is executed without governed approval.

Thifur informs execution decisions but does not control them.

Authority never leaves the governed system.

---

## System Boundaries

### Aureon Owns

- governed portfolio intent formation before execution
- pre-trade policy, mandate, and control checks
- risk framing and constraint visibility for human review
- configurable role-based approval lineage
- DSOR evidence, replay context, and audit packaging
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

Aureon is designed to support the controlled use of bounded agentics and agentic AI within defined workflows, not unrestricted automation.

AI operates within bounded, role-aware tasks such as trade structuring, constraint validation, scenario analysis, decision support, and execution-intelligence support. All outputs remain subject to human-in-the-loop approval before execution. The DSOR is the control layer where AI-generated recommendations are evaluated, challenged, approved, or rejected within the same governed framework as human input.

This means Aureon can improve pre-trade decision quality without introducing autonomous execution or weakening supervisory control.

---

## Phase 1 vs Later

| Area | Phase 1 Deployable | Later Expansion |
|------|--------------------|-----------------|
| Asset scope | Equities-first | Program Trading, then selected adjacency expansion |
| Primary pilot | Electronic Execution | Broader cross-desk rollout |
| Core value | Pre-trade governance overlay and execution intelligence | Broader operating model expansion |
| AI usage | Controlled, role-bound workflow support with HITL approval | Expanded supervised agent coverage |
| OMS/EMS relationship | Augment incumbent stack | Deeper integration, still not default replacement narrative |
| SOR / routing | Outside Aureon | Potential integration depth only; not Phase 1 ownership |
| Post-trade | Feedback returned for evidence and replay | Deeper downstream packaging and analytics |
| Treasury / settlement | Visible as downstream context only | Attached operating extensions where justified |
| Asset expansion | Carefully bounded | Delta One, Prime, OTC, and additional asset classes as controlled later phases |

Electronic Execution is the first pilot. Program Trading follows after the Electronic Execution operating model is proven.

---

## Doctrine Model With Institutional Translation

The doctrine identity can still be useful as an internal operating language, but it must map cleanly to institutional responsibilities.

| Doctrine Name | Institutional Translation | Phase 1 Responsibility |
|---------------|---------------------------|------------------------|
| **Verana** | Control and governance boundary layer | Session controls, policy boundary enforcement, supervisory control posture |
| **Mentat** | Decision-intelligence and portfolio reasoning layer | Intent synthesis, scenario support, strategy-context framing |
| **Kaladan** | Lifecycle and evidence orchestration layer | Approval lineage, evidence packaging, replay context, downstream status attachment |
| **Thifur** | Trader and execution-support bounded agentics layer | Pre-trade execution-intelligence support, governed release preparation, non-activated execution advisory capability |

Doctrine names should always be read alongside these institutional translations, not as free-floating abstractions.

---

## What The Prototype Demonstrates Today

- a lightweight DSOR-style pre-trade decision workflow
- doctrine and governance surfaces for reviewable decisions
- human approval flow with attributable control points
- pre-trade routing and control checks
- OMS-overlay exploration through FIX translation stubs
- evidence and reporting surfaces tied to decision lineage
- dashboard views for governance, decisions, and downstream status visibility

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
```

Current file roles:

- `server.py`: prototype backend orchestration, state, governance logic, and API routes
- `index.html`: prototype dashboard and operator workflow UI
- `fix_adapter.py`: FIX translation stub for OMS/EMS integration boundary exploration
- `aureon_state_persist.json`: local persisted runtime state
- `scripts/`: local startup helpers

Phase 5 will refactor this structure to better separate decision orchestration, policy/risk checks, approvals, integration adapters, evidence services, presentation, and infrastructure concerns.

---

## Quick Start

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
```

Email is optional for local prototype use.

---

## Current Limitations

- The system is a prototype and does not yet implement production-grade persistence, resiliency, or control architecture
- The codebase is still structurally compressed and does not yet reflect the target service boundaries
- FIX support is a translation stub, not a live broker, EMS, or OMS session
- Some downstream concepts remain visible in the prototype narrative and UI beyond the ideal Phase 1 architectural boundary
- The repository should be read as an institutional product prototype, not as a claim of full OMS, SOR, treasury, settlement, or books-and-records replacement

---

## Long-Term Direction

The long-term ambition is to expand Aureon into a broader institutional decision and governance layer across additional workflows, desks, and asset classes. That ambition remains subordinate to Phase 1 deployability.

The near-term objective is much narrower and more credible:

- prove Electronic Execution as the first GSIB-ready pilot
- establish Aureon as the DSOR before execution
- demonstrate clean boundaries with OMS, EMS, SOR, and downstream post-trade systems
- build trust through governed approvals, replayability, and evidence quality

---

*Project Aureon · Guillermo "Bill" Ravelo · Columbia University MS Technology Management*
