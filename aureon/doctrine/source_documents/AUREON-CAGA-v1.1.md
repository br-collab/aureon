**PROJECT AUREON**
*The Grid 3*
**CANONICAL GOVERNING ARCHITECTURE**
*Doctrine-governed, AI-augmented financial operating system for the convergence of tokenization, AI execution, and programmable payment rails.*

| **Prepared by** | Guillermo "Bill" Ravelo · Ravelo Strategic Solutions LLC |
|---|---|
| **Academic** | Columbia University · M.S. Technology Management |
| **Document version** | Canonical Synthesis v1.1 · April 17, 2026 (revised against deployed server.py) |
| **Doctrine stack** | Aureon Doctrine v1.3 · Cato v0.2.2 core / v0.2.3 cache · CAOM-001 effective April 6, 2026 |
| **Live deployment** | aureon-production.up.railway.app · Endowment Series I — Argus · $100M paper AUM |
| **Status** | Paper trading · approaching institutional testing · no real capital at risk |
| **Classification** | CONFIDENTIAL — Restricted Distribution |

# I. DOCTRINE PREAMBLE
## Purpose
Aureon is the control layer between portfolio intent and execution. It validates doctrine, risk, compliance, and human authority before a signal becomes a market event. Every decision carries an immutable audit lineage — signal origin, doctrine check, risk evaluation, compliance gate, human authority stamp, execution confirmation, settlement evidence — re-constructable on demand for any trade at any granularity within a ten-year retention window.
The thesis is structural, not ornamental. Most financial technology is built execution-first, with governance retrofitted under regulatory pressure. That approach survives until market structure changes faster than institutions can adapt. The convergence already underway — tokenized Treasuries clearing on-chain around the clock, the CFTC confirming tokenized assets as eligible derivatives collateral (December 2025), the GENIUS Act in the legislative pipeline, JPMorgan's first on-chain commercial paper issuance on Solana — will not wait for governance to be retrofitted. Aureon inverts the order: doctrine first, technology built to the doctrine.
## Scope
Aureon governs the decision boundary between signal and execution. It sits above Order Management Systems (OMS), Execution Management Systems (EMS), Smart Order Routers (SOR), and post-trade infrastructure — never inside them. Aureon governs what enters those systems and produces the unified lineage record that trustees, rating agencies, and regulators can rely on. The three deployment modes — governance overlay, full-stack operating system, and compliance artifact engine — are expressions of the same control layer at different integration depths.
## What Aureon Is Not
- Not a broker. Aureon never holds venue connectivity, exchange sessions, or custody relationships.
- Not an OMS or EMS. Order state, allocations, parent-order lifecycle, and trader execution workflow remain outside Aureon's boundary.
- Not a portfolio management replacement. Portfolio construction and mandate design remain with the operator and the fund's investment doctrine.
- Not a market-action agent. No layer of Aureon — including the most autonomous one — ever takes a market action under any condition. Every agent advises. The operator decides.
- Not a counterparty-credit gate. The live settlement gate (Cato) is a market-regime gate. Counterparty-credit signals are an explicit, documented out-of-scope decision pending a future doctrine version.
## Live Deployment — Endowment Series I · Argus
The canonical proof-of-concept runs against a $100M paper-AUM endowment portfolio — Endowment Series I, codename Argus — with a 5% spending-rate target and an intergenerational preservation mandate. Argus is not a generic paper trade; it is a named test harness that stresses the full doctrine stack against a mandate profile representative of institutional endowments, foundations, and sovereign wealth administrators. System of record live inception date: April 7, 2026. Every decision the system has made against Argus is replayable from the DSOR.

## Source Reconciliation
This canonical document synthesizes four source artifacts across the evolution of the architecture, subordinating earlier thinking to the most recent:
- **Deployed server.py (April 17, 2026). **The live implementation at aureon-production.up.railway.app — 7,654 lines, 81 API routes, Doctrine v1.3 audit-hash-stamped at startup. This is the most recent thinking and is treated as canonical where it diverges from earlier documents.
- **Framework Brief v2 (April 2026, Doctrine v1.3, Cato v0.2.2). **The public-facing deployment view rendered by the live system at /framework-brief.
- **Agent Specification Draft 2.0. **The authoritative agent-level task, guardrail, and regulatory specification.
- **CAOM-001 (effective April 6, 2026). **The authoritative human-authority mapping for the solo-operator phase.
**[RESOLVED] ***Project naming. CAOM-001 uses the prior name "Project Arcadia." All other artifacts — deployed code, Framework Brief v2, Agent Specification, live UI — use "Project Aureon / The Grid 3." This document treats Aureon as canonical. Operative CAOM-001 clauses preserved verbatim; CAOM-001 requires a clean reissue under the Aureon masthead.*
**[RESOLVED] ***Alpha-origination layer naming. The live UI, the registered doctrine document, and the v1.3 provenance record all use "Atrox" (formally, **Thifur**-Atrox) for the 50,000 ft alpha-origination layer. "Neptune Spear" is the operational nickname retained in source filenames, API route paths (/**api**/**neptune**/*), and internal pipe functions. This canonical document treats Atrox as the doctrine name. Framework Brief v2, which still uses "Neptune Spear" in the layer table, requires republication to align with the live UI.*
**[CONFLICT] ***Cato version state in deployed code is mixed: core gate logic is at v0.2.2 (SOFR one-day delta trigger active), the sticky last-known-good price cache has advanced to v0.2.3, and several endpoint docstrings still read v0.2.1. The Framework Brief's claim that both implementations sit cleanly at v0.2.2 is a simplification. The core doctrine is at v0.2.2 as stated; the cache layer is ahead and the docstrings are behind. Action: harmonize version strings before the next institutional demonstration (see Section V, Parity Principle).*

# II. LAYER-BY-LAYER ARCHITECTURE
The Aureon stack is not a pipeline. Each layer holds doctrine authority for its own domain. Authority flows top-down. Intelligence flows bidirectionally. No layer operates without the one above it, and no layer substitutes for the human authority tiers declared in CAOM-001.
The canonical decomposition renders four governance layers, with the execution layer internally decomposed into the Thifur agent family. An earlier six-layer presentation (Framework Brief v2) separated the alpha-origination layer (Atrox) as its own altitude above Mentat. This canonical document treats Atrox as the advisory intent-origination surface feeding Mentat, not as a governance layer — because Atrox is advisory only and holds no independent gate authority. The governance layers are Mentat, Kaladan, Thifur, and Verana.
*[RECONCILED] Framework Brief v2 six-layer view (Atrox · **Mentat** · Kaladan · Thifur-C2 · **Thifur** R/J/H · Verana L0) and Agent Specification Draft 2.0 four-layer view (Verana L0 · **Mentat** · Kaladan · **Thifur**) describe the same architecture at different resolutions. The four-layer governance structure is canonical. Atrox is rendered as an advisory intent-origination surface feeding **Mentat**.*
## Architecture at a Glance

| **Layer** | **Altitude** | **Doctrine Name** | **Governance Function** |
|---|---|---|---|
| **Layer 3** | 500 ft | Thifur — Agentic Execution | C2 coordination · R deterministic · J bounded autonomy · H adaptive (declared, not activated) |
| **Layer 2** | 10,000 ft | Kaladan — Lifecycle Orchestration | Approval lineage · DSOR record assembly · evidence packaging · treasury, settlement, compliance artifacts |
| **Layer 1** | 30,000 ft | Mentat — Strategic Intelligence | Intent synthesis · scenario support · doctrine truth evaluation · strategy-context framing |
| **Layer 0** | Ground | Verana — Network Governance | Session controls · policy boundary enforcement · MCP registry · Cato doctrine gate · supervisory posture |

*Advisory surface above **Mentat**: **Thifur**-Atrox (operational nickname: Neptune Spear) surfaces alpha hypotheses and pre-trade intent at 50,000 ft. Operator review is required before any Atrox-originated intent reaches Kaladan for structuring. Atrox originates; Kaladan packages; Thifur-C2 coordinates; **Thifur** R / J / H execute within bounded scope; Verana enforces network state throughout.*
## Layer 1 · Mentat — Strategic Intelligence (30,000 ft)
### Function
Mentat is the decision-intelligence layer. It receives operator-approved intent from Atrox, synthesizes portfolio context, frames scenario analysis, and evaluates doctrine truth. Mentat is the only layer authorized to interpret doctrine — every other layer either enforces doctrine (Verana), orchestrates under doctrine (Kaladan), or executes within doctrine bounds (Thifur). When doctrine is ambiguous, only Mentat may resolve it, and only after operator authority closes the resolution loop.
### Responsibilities
- Synthesize portfolio intent from Atrox-originated, operator-approved signals into structured decision objects.
- Surface mandate alignment, underweight / overweight flags, conviction scores, and risk framing.
- Evaluate doctrine truth when scenarios encounter ambiguity — present both valid paths with rationale to the operator.
- Stamp every downstream Kaladan packet with the active doctrine version.
- Record operator-selected resolutions as doctrine precedent for future scenarios.
### Boundaries
- Mentat does not approve. It frames. The operator approves.
- Mentat does not orchestrate execution. Kaladan orchestrates.
- Mentat does not take network actions. Verana enforces network state.
## Layer 2 · Kaladan — Lifecycle Orchestration (10,000 ft)
### Function
Kaladan is the lifecycle orchestration layer. It converts Mentat-framed intent into a governed intent packet carrying the complete pre-trade record: doctrine version stamp, approval lineage, mandate validation, and evidence bundle. The governed intent packet is the only object Thifur-C2 accepts as valid input. Kaladan is also the system of record for the DSOR — the Decision System of Record — and owns the assembly of the replayable governance package that every decision, at every granularity, can be reconstructed from.
### Responsibilities
- Assemble the governed intent packet with doctrine version, authority hashes, mandate validation, and evidence bundle.
- Sequence the role-based approval workflow through the authority tiers declared in CAOM-001.
- Package regulatory evidence at every lifecycle stage — pre-trade, execution, post-trade, settlement.
- Surface drawdown guard, position limits, liquidity buffer status, and concentration state.
- Hold degraded-operations state and coordinate fallback sequences across Thifur agents under DORA.
- Deliver the final unified lineage record — assembled by Thifur-C2 — to the DSOR.
### Boundaries
- Kaladan does not interpret doctrine. It enforces the version Mentat stamped.
- Kaladan does not coordinate agent handoff. Thifur-C2 does.
- Kaladan does not execute. It packages what Thifur will execute.
## Layer 3 · Thifur — Agentic Execution (500 ft)
Thifur is the execution family. It is internally decomposed into four agents: C2 (Command and Control coordination), R (Ranger — deterministic execution), J (JTAC — bounded autonomy), and H (Hunter-Killer — adaptive intelligence). Each agent has bounded scope. Agent-to-agent transfers are illegal. All handoff flows through C2. All escalations present a single unified picture to human authority.
### Thifur-C2 — Command and Control
C2 is the Agent orchestration layer between Kaladan's governed intent packet and the execution triplet. C2 does not originate. C2 does not execute. C2 does not interpret doctrine. C2 sequences agent activation, records every handoff, assembles the unified lineage record, and presents a single escalation surface to human authority. C2 is the architectural answer to the multi-agent convergence problem: when a single lifecycle object simultaneously requires deterministic settlement (R), programmable-asset governance (J), and adaptive optimization (H), C2 is the only layer that holds the complete picture.
C2 is also the sole coordination point at the TradFi–DeFi convergence boundary. No Thifur agent on either side of that boundary communicates directly across it. All cross-boundary coordination routes through C2.

| **C2 — FIVE IMMUTABLE STOPS** <br> 1. No self-execution. C2 never takes a market action, generates an order, modifies a position, or issues a settlement instruction under any condition. <br> 2. No doctrine interpretation. C2 receives doctrine version stamps from Kaladan. Doctrine ambiguity escalates to Mentat via the human authority surface. <br> 3. Handoff before action. No Thifur agent may act on a lifecycle object without a recorded C2 handoff authorization. No exceptions. <br> 4. One lineage record. C2 assembles the unified lineage. DSOR never receives raw agent telemetry as a substitute. Gaps are flagged explicitly — never silently filled. <br> 5. Escalation completeness. C2 never escalates a partial picture. If agent context is pending, C2 waits within defined time bounds before escalating. Gaps are flagged explicitly in the escalation package. |
|---|

### Thifur-R — Ranger · Deterministic Execution
Thifur-R governs the TradFi execution domain under strict determinism. Same input, same output. Always. This is the agent that makes a Citi Revlon $900M-class error structurally impossible — zero variance, immutable lineage stamped at execution time, and no retroactive modification under any condition. Thifur-R owns payment rail execution in the convergence model: when a tokenized asset requires traditional-rail settlement, J prepares the instruction package and C2 hands off to R. R never receives input directly from any other agent.
### R — Guardrails
- Zero variance. No path selection, no optimization, no judgment.
- No self-initiation. Every action requires a C2-issued tasking record.
- No settlement without DSOR confirmation. Every instruction trace to a pre-trade record.
- Immediate escalation on discrepancy. No silent retry. No retry without human authority.
- Immutable lineage. Stamped at execution, never modified post-execution.
### Thifur-J — JTAC · Bounded Autonomy
Thifur-J governs the TradFi–DeFi convergence zone — tokenized assets moving through programmable workflows, cross-border flows with jurisdictional constraints, and multi-constraint paths where strict determinism is insufficient but unconstrained optimization is impermissible. JTAC — Joint Terminal Attack Controller — selects among pre-approved paths, never generates new ones. Code does not override doctrine: when smart-contract logic conflicts with Mentat doctrine, J holds execution and escalates to C2.
### J — Guardrails
- Approved paths only. J selects from the Kaladan-defined routing and lifecycle set. Never generates new.
- Doctrine over code. Smart contract execution never overrides doctrine. Conflict holds the object.
- No release without approval lineage. Attributed human approval record required in DSOR.
- Eligibility before routing. KYC / KYB and mandate validation must pass before routing.
- Jurisdictional attribution before execution. Every cross-border segment requires a Verana-assigned jurisdictional authority.
### Thifur-H — Hunter-Killer · Adaptive Intelligence
Thifur-H is the adaptive optimization agent — VWAP / TWAP / POV execution strategy, liquidity-aware timing, collateral optimization, FX hedging within doctrine-defined risk parameters. H is the most powerful agent in the architecture and the most scrutinized. Its power and its risk come from the same source: continuous optimization within multi-variable financial domains at machine speed.
**Status — declared, not activated. **H is specified now so the governance architecture does not need to be retrofitted when activation occurs. Phase 2 activates the execution-strategy task family. Phase 3 activates the collateral, FX, and repo optimization families.
### H — Guardrails
- Objective function supremacy. H optimizes within Tier 2–approved objective functions only. Never redefines its own.
- Doctrine over optimization. An efficient but non-compliant action does not execute.
- Risk parameter hard stops. Maximum loss, concentration, and liquidity thresholds are hard stops. Breach triggers automatic suspension.
- Emergency suspension — any Tier 1 or above can suspend H immediately with no prior approval. Resumption requires Tier 2.
- No activation without independent validation under SR 11-7 Tier 1.
- Explainability before execution. If an action cannot be explained in human-readable terms, it does not execute.
## Layer 0 · Verana — Network Governance (Ground)
### Function
Verana is the network layer. It holds the registry of every node the system interacts with — settlement rails, payment counterparties, tokenized-asset platforms, data sources, MCP servers. It enforces session boundaries, jurisdictional attribution, OFAC screening, doctrine integrity, and systemic-stress monitoring. Verana is the only layer authorized to autonomously block: if a doctrine integrity check fails, Verana stops the session regardless of any other authority present.
### Responsibilities
- Register every third-party node under OCC 2023-17 with SLA enforcement and pre-staged fallback.
- Enforce session boundary checks at session open (CAOM-001 Step 1).
- Host the Cato settlement doctrine gate as the pre-settlement enforcement point.
- Record the CAOM operating mode declaration in the Network Registry at session open.
- Run the Jurisdictional Boundary Engine for cross-border flow attribution.
- Monitor concentration, systemic stress, and doctrine integrity continuously and autonomously.
- Absorb regulatory mandates autonomously — the doctrine v1.1 bump (DORA Article 28 absorption) was a Verana L0 event, not a human-authority event.
### Cato — The Live Verana Gate
Cato is the Verana L0 pre-settlement doctrine gate for tokenized institutional repo. It answers one question before every settlement: is atomic on-chain Delivery-versus-Payment viable right now, or should this trade route to FICC (Fixed Income Clearing Corporation)? The gate runs four deterministic checks and emits PROCEED, HOLD, or ESCALATE plus a recommended settlement rail.
Cato exists in two implementations that must produce bit-for-bit identical decisions for identical inputs: the external open-source MCP server (Node.js, MIT license, 23 tools at github.com/br-collab/Cato---FICC-MCP) and the in-process Python twin inside Aureon. The in-process twin's core gate logic is at v0.2.2 with the SOFR one-day delta trigger active; its sticky price cache has advanced to v0.2.3; several endpoint docstrings still read v0.2.1. The external MCP README describes v0.2.0 / v0.2.1 routing. The deterministic parity — what Section V defines as the Parity Principle — requires these to converge at the next version stamp.
### Cato v0.2.2 Thresholds

| **Input** | **Threshold** | **Effect** |
|---|---|---|
| **OFR STLFSI4** | > 1.0 | ESCALATE — systemic stress, route to human authority |
| **OFR STLFSI4** | > 0.5 | HOLD — broad stress, route to FICC traditional |
| **ETH L1 gas** | > 50 gwei | HOLD — L1 congestion, route to FICC traditional |
| **\|SOFR(t) − SOFR(t−****1)\|**** × 100** | > 10 bps | HOLD — funding-market shock (v0.2.2 Sept 2019 backtest fix) |
| **All below threshold** | — | PROCEED — atomic settlement viable |

### Supported Settlement Rails

| **Rail** | **Speed** | **Cost (normal state)** | **Status** |
|---|---|---|---|
| **FICC traditional** | T+1 | ~0.5 bps net of 40% netting + SOFR cost of capital | Live |
| **Ethereum L1** | ~12s | ~$0.08 at 0.5 gwei, $2,300 ETH | Live |
| **Base (Ethereum L2)** | ~2s | ~$0.001 at 0.01 gwei | Live |
| **Arbitrum**** (L2)** | ~2s | ~$0.10 at 0.6 gwei | Live |
| **Solana** | ~400ms | ~$0.0004 at 5,000 lamports | Live |
| **Fed L1 / PORTS** | Instant | TBD — sovereign tokenized reserve rail | Pending GENIUS Act |

*The governance gate — not the rail — is the product. When the Fed issues tokenized reserves or PORTS ships, Cato routes there. The doctrine does not change. The rail does. The fed_l1 placeholder slot in every Cato **chain_state** response is reserved for exactly that event (Duffie, 2025, "The Case for PORTS", Brookings).*
### SR 11-7 Tier 1 Backtest — Cato v0.2.2

| **Event** | **v0.2.1** | **v0.2.2** | **Verdict** |
|---|---|---|---|
| **March 2020 — COVID repo freeze** | 100% (20/20) | 100% (20/20) | ✓ Caught — OFR peak 5.657, SOFR Δ 84 bps |
| **September 2019 — repo spike** | 0% (0/5) | 80% (4/5) | ✓ Caught after v0.2.2 fix — pure funding crunch, OFR FSI negative |
| **March 2023 — SVB collapse** | 45.5% (5/11) | 45.5% (5/11) | ! Calibration limit — slow credit event, not in rate/stress signals |

*The September 2019 gap closed in v0.2.2 by restoring the SOFR one-day delta trigger dropped in the v0.2.0 refactor. SVB is a documented calibration limitation — it requires counterparty-credit signals (HY OAS, bank equity) not currently in the doctrine. Cato is a market-regime gate, not a counterparty-credit gate. That is a design choice, not a gap. A future Cato version may extend into credit signals; that extension will be a doctrine amendment, not a patch.*

# III. GOVERNANCE AXIOMS
These are the rules the system enforces on itself. They are not configurable. They are not overridden by any agent. They may only be modified by the operator through the Doctrine Modification Governance workflow described in Section V. Every axiom is architecturally enforced — not aspirational.

| **AXIOM 1 — DOCTRINE BEFORE EXECUTION** <br> No decision executes without a doctrine version stamp, an authority hash, and an approval-lineage record in the DSOR. The ordering is absolute: Mentat stamps doctrine, Kaladan packages, C2 coordinates, R / J / H execute. No layer substitutes for the layer above it. Enforced in the deployed code by the startup doctrine-stack cycle that signs every ready state with a SHA-256 audit hash. |
|---|
| **AXIOM 2 — AGENTS ADVISE, OPERATORS DECIDE** <br> No agent at any layer holds approval authority. Agents surface analysis, enforce pre-configured rules, and emit telemetry. Every approval gate requires explicit operator action. This holds under CAOM-001 and remains non-negotiable in any transition to institutional role separation. |
| **AXIOM 3 — HANDOFF BEFORE ACTION** <br> No Thifur agent acts on a lifecycle object without a recorded C2 handoff authorization. Agent-to-agent direct transfers are illegal. This is the architectural enforcement of BCBS 239 P3 (automated, reconciled risk-data aggregation) and SR 11-7 aggregate-model-risk view. |
| **AXIOM 4 — ONE LINEAGE RECORD** <br> The DSOR receives the C2-assembled unified lineage, never raw agent telemetry. Gaps in agent telemetry are flagged explicitly — never silently filled. A unified picture with a flagged gap is valid. A complete-looking picture with an unflagged gap is an SR 11-7 violation. |
| **AXIOM 5 — DOCTRINE OVER CODE** <br> Smart-contract execution logic never overrides Mentat doctrine. When code and doctrine conflict, Thifur-J holds the object, C2 escalates, human authority decides. This axiom is what makes programmable assets governable inside a regulatory framework. |
| **AXIOM 6 — ESCALATION COMPLETENESS** <br> C2 never presents a partial picture to human authority. If agent context is pending, C2 waits within defined time bounds before escalating. The escalation package always carries complete context or explicit flags for what is missing. Human authority is never overwhelmed with three concurrent agent contexts — always one governed picture. |
| **AXIOM 7 — EXPLAINABILITY BEFORE EXECUTION** <br> Every Thifur-H action must be explainable in human-readable terms before execution. If it cannot be explained, it does not execute. This is the EU AI Act high-risk AI requirement applied architecturally rather than compliance-theatrically. |
| **AXIOM 8 — VERANA AUTONOMOUS BLOCK** <br> Verana is the only layer authorized to autonomously block. Doctrine integrity failure, OFAC screening failure, session-boundary violation, and systemic-stress hard-stop are enforced by Verana without reference to any other authority. An autonomous block is a feature of Layer 0, not a failure of Layers 1–3. |
| **AXIOM 9 — TIER 0 EMERGENCY HALT ABOVE ALL DOCTRINE** <br> The Emergency Halt is a Tier 0 authority that sits above the three-tier CAOM-001 structure. Any authority can trigger it. When Halt is active, all Thifur execution is frozen immediately — R, J, and any future H domain — regardless of what other authorities or doctrine versions are active. Halt state carries its own immutable lineage: activation timestamp, invoking authority, stated reason. Resumption requires explicit operator action and generates a doctrine-change-style audit record. Halt is the system's circuit breaker; it is outside the tier hierarchy by design. |

# IV. FAILURE MODES AND ESCALATION LOGIC
The architecture is specified by its failure modes. An institutional risk committee should be able to name each class of failure, the detecting layer, the holding behavior, and the escalation destination. The matrix below is complete at the specification level — every cell maps to a guardrail or protocol in the Agent Specification and CAOM-001 source documents, and every row has a corresponding enforcement path in the deployed code.
## Convergence Governance — TradFi / DeFi Boundary

| **Scenario** | **Primary Agent** | **Supporting Agents** | **Coordination Rule** |
|---|---|---|---|
| **Tokenized asset requires traditional-rail settlement** | Thifur-J (lifecycle) | Thifur-R (settles) | J prepares instruction package. C2 records handoff. R executes deterministically. No direct J→R transfer. |
| **AI optimization concurrent with tokenized settlement** | Thifur-J (lifecycle) | Thifur-H (collateral), Thifur-R (settles) | C2 sequences H advisory first. J validates against doctrine. R executes. H never generates a settlement instruction. |
| **Smart-contract logic conflicts with ****Mentat**** doctrine** | Thifur-J (holds) | C2 escalates to human authority | J suspends. C2 packages conflict context from all active agents. Minimum Tier 2 human authority required to proceed. |
| **Payment rail failure during tokenized settlement** | Thifur-R (fallback) | Thifur-J (holds asset state) | C2 freezes J object. R executes Verana fallback sequence. J resumes only after C2 confirms fallback rail is governed and SLA-compliant. |
| **Tokenized concentration breach mid-lifecycle** | Verana Concentration Monitor | All active Thifur agents suspend | C2 halts all agents on affected lifecycle. Unified escalation minimum Tier 1. No agent resumes without human clearance. |
| **Cross-border flow with jurisdictional conflict** | Thifur-J (holds routing) | Mentat Conflict Resolution | J suspends. C2 packages conflict for Mentat. Kaladan holds lifecycle. Minimum Tier 2 human authority before J resumes. |

## Emergency Halt — Tier 0
The Emergency Halt endpoint (/api/halt POST) freezes all Thifur execution system-wide in a single operation. Halt state is stamped with activation timestamp, invoking authority, and stated reason, and is visible on /api/halt GET and in the governance pane. Resumption through /api/halt/resume POST is a deliberate two-step action that itself becomes an audit record. Halt is not a fallback and not a DORA degraded-operations trigger — it is the kill-switch of last resort for the entire execution surface.
## Degraded Operations
Under DORA (Digital Operational Resilience Act), no Thifur agent enters degraded mode unilaterally. When any agent detects a degradation trigger — rail outage, telemetry loss, latency breach — the agent emits a degradation signal to C2. C2 activates the pre-defined fallback sequence under Kaladan's Degraded Operations Mode. All three execution agents are sequenced coordinated — partial-degradation races are not permitted. The unified lineage record is maintained continuously across the degradation event.
Recovery Time Objective (RTO): 15 minutes for settlement execution on the primary path. Fallback sequences are pre-staged in Verana's Fallback Authority registry before any live execution. Annual Threat-Led Penetration Testing (TLPT) covers the full Thifur surface, with Thifur-H explicitly in scope.
## Kill Switch Hierarchy
Under MiFID II RTS 6 algorithmic trading controls, the kill switch is three-level — not two, once the Tier 0 Emergency Halt is counted:
- **Level 1 — Algo-scope suspension. **Suspends a single algorithm or agent in a single domain. Any Tier 1 authority can trigger. Resumption requires Tier 2.
- **Level 2 — Full Algo Suspension. **C2 cancels all Thifur-H and Thifur-J orders across all domains in one command within five seconds. Any Tier 2 authority can trigger. Resumption requires Tier 3 and a post-incident doctrine review.
- **Tier 0 — Emergency Halt. **Complete execution freeze across R, J, and H. Any authority can trigger. Resumption requires explicit operator action and generates an audit record equivalent to a doctrine change.
No agent — under any condition — may activate or override a kill switch at any level. Kill-switch authority resides with human operators. This is non-negotiable under CAOM-001 and non-negotiable in any post-CAOM institutional deployment.
## Regulatory Stress Test Matrix

| **Agent** | **SR 11-7** | **MiFID II RTS 6** | **EU AI Act** | **DORA** | **BCBS 239** |
|---|---|---|---|---|---|
| **Thifur-C2** | Aggregate model risk view | Kill Switch Level 2 | Single oversight surface | Coordinated degraded ops | P3 unified lineage |
| **Thifur****-R** | Tier 2 — deterministic | Post-trade / 5-sec alerts | Not high-risk AI | RTO 15 min settlement | P3 automated accuracy |
| **Thifur****-J** | Tier 1 — pre-deploy validation | AUR-J-TRADE-001 inventory | High-risk — conformity | ICT third-party registry | P4 completeness |
| **Thifur****-H** | Tier 1 — independent validation | Kill Switch, price collars | High-risk — EU DB registration | TLPT annual scope | P5 real-time timeliness |

# V. HUMAN AUTHORITY, DOCTRINE PROVENANCE, AND PARITY
## CAOM-001 — Consolidated Authority Operating Mode
CAOM-001 is the formally governed configuration under which a single human operator holds all three tiers of Human Authority simultaneously, while agents assume the analytical and advisory functions that institutional role-holders perform in a multi-person deployment. CAOM-001 is not a workaround. It is not a reduced-governance state. It is a defined, doctrine-consistent operating mode, effective April 6, 2026, appropriate for solo fund operators, proof-of-concept environments, and pre-staffing deployments.
### Authority Mapping

| **Institutional Role** | **Tier** | **CAOM Mapping** | **Agent Advisory Support** |
|---|---|---|---|
| **Emergency Halt** | T0 Circuit Breaker | Operator holds seat · above all doctrine | No agent may trigger or override · audit record on activation and resumption |
| **Trader** | T1 Operational | Operator holds seat | Thifur-H: VWAP/TWAP, slippage, liquidity depth |
| **Risk Manager** | T1 Operational | Operator holds seat | Mentat risk framing; Kaladan drawdown; Thifur-J policy check |
| **Portfolio Manager** | T1 Operational | Operator holds seat | Mentat: mandate alignment, conviction score |
| **Compliance Officer** | T2 Governance | Operator holds seat | Verana: OFAC, doctrine integrity, stress (autonomous) |
| **Head of Risk / CRO** | T2 Governance | Operator holds seat | Kaladan: drawdown guard, limits, liquidity buffer |
| **Executive / Principal** | T3 Executive | Operator holds seat | All systemic / doctrine / kill-switch decisions — operator only |

*Agents provide analysis, surface signals, enforce pre-configured doctrine rules. Agents do not make approval decisions. Every approval gate requires explicit operator action. The agent fills the analytical role; the human fills the authority role. This distinction is non-negotiable.*
**[CONFLICT] ***CAOM-001 as issued declares three tiers (T1 Operational, T2 Governance, T3 Executive). The deployed code adds a Tier 0 Emergency Halt that sits above all three. This canonical document adopts T0 as the correct rendering. CAOM-001 requires a formal addendum to declare Tier 0 explicitly in the authority mapping, pending which the live code is the source of truth.*
### Session-Open Protocol
- 1. Verana session boundary check (automated) — must pass before session opens.
- 2. CAOM mode declaration — operator confirms CAOM-001 is active operating mode.
- 3. Role consolidation acknowledgment — operator affirms tier holdings for the session, logged to DSOR.
- 4. Agent advisory readiness check — Thifur-C2 confirms all advisory agents are online and doctrine-loaded.
- 5. Systemic stress status review — Verana surfaces OFR STLFSI4 signal; operator may proceed unless Verana hard-blocks.
- 6. Session open confirmation — operator confirms; execution gates activate.
*The 6 April 2026 pre-trade routing failure was caused by the absence of Steps 2 and 3 prior to CAOM-001 codification. CAOM-001 is both the architectural fix and the formal doctrine. All six steps are implemented as discrete endpoints (/**api**/session/status, /**api**/session/step/1, /**api**/session/step/2, /**api**/session/step/3, /**api**/session/open) in the deployed server.*
### Transition Triggers
CAOM is the initial operating mode, not the permanent one. The following conditions trigger a formal review of institutional role separation:
- AUM exceeds $10M — formal review of dedicated Risk Manager role separation.
- External investor capital onboards — Compliance Officer role separation required. CAOM is not compatible with third-party investor governance obligations.
- Regulatory examination scheduled — Tier 2 and Tier 3 authority reviewed under applicable framework.
- First institutional staff hire — begin formal CAOM transition plan, role separation phased by function starting with Compliance.
- Strategy licensing to third party — licensing counterparty governance requirements may impose role separation.
## Doctrine Provenance — v1.0 Through v1.3
The doctrine version log is a live, append-only record in the deployed system. Every version bump carries a SHA-256 hash, the authority that authorized the bump, the tier the bump required, the trigger class, and the stated reason. This is the change-control evidence a risk committee independently verifies:

| **Version** | **Authority** | **Tier / Trigger** | **Reason** |
|---|---|---|---|
| **1.0** | SYSTEM | System Init | Initial doctrine load — Aureon Grid 3 deployment. |
| **1.1** | Verana L0 Regulatory Absorption | T2 — Regulatory Mandate | EU DORA Article 28 absorbed. Four nodes flagged. Doctrine updated autonomously by Verana. |
| **1.2** | Operator (Tier 1 Human Authority) | T1 — Human Authority | Basel III Endgame vs EU CRR III conflict. Operator resolved by applying the higher RWA standard. |
| **1.3** | Operator (CAOM-001) | T1 — Human Authority | Thifur-Atrox (Alpha Generator, Draft 1.0) and Thifur-C2 (Command and Control, Draft 1.0) registered. Atrox formalized above execution triplet. Authority chain codified: Atrox → Operator → Kaladan → C2 → R / J / H. Five Immutable Stops codified in C2 doctrine. |

*The v1.1 entry is material evidence that Axiom 8 (Verana Autonomous Block) is implemented, not theoretical: Verana absorbed a regulatory mandate autonomously and advanced the doctrine version without human intervention. The v1.2 entry demonstrates the operator-led conflict resolution path for jurisdictional ambiguity. The v1.3 entry is the current state.*
## Doctrine Modification Governance
Doctrine amendments in the deployed system flow through a two-step tier-gated workflow: /api/doctrine/propose POST registers a proposed amendment (rationale, trigger, affected layer) and /api/doctrine/approve/<update_id> POST executes the version bump with the approving authority identity, tier, and a fresh SHA-256 hash. The workflow is the formal successor to the Thifur-C2 Section IV rule that the Five Immutable Stops may only be modified by the operator through a formal doctrine addendum recorded in Verana's Network Registry. That rule is now architecturally enforced — the propose/approve endpoints are the only path that advances the version log.
## The Parity Principle
Any component of Aureon implemented in two codebases — the external MCP server and the in-process Python twin, for Cato today, and by extension for any future Verana tool — must produce bit-for-bit identical decisions for identical inputs. Doctrine changes land in both codebases in the same commit series. The external and internal implementations should be at the same doctrine version at all times. This parity is what lets a trustee, a rating agency, or a regulator trust the gate regardless of caller.
**[CONFLICT] ***Open parity gap: the deployed Cato implementation is **version-mixed**. Core gate logic runs the v0.2.2 SOFR one-day delta trigger. The sticky last-known-good price cache has advanced to v0.2.3. Several endpoint docstrings still document v0.2.1 behavior. The external MCP README also reflects v0.2.0 / v0.2.1 routing. Action: issue a consolidated v0.2.3 stamp that brings core logic, price cache, endpoint docstrings, and the external MCP README into a single commit series with identical decisions on identical inputs. Until that happens, the claim of parity is conditional, not established.*

# VI. INSTITUTIONAL LICENSING THESIS
Aureon's commercial path is licensing the governance layer, not operating a fund. The convergence of tokenization, AI-driven execution, and programmable payment rails is arriving in capital markets faster than incumbent governance frameworks can adapt. BlackRock BUIDL is live on nine chains with more than $2B AUM. Franklin Templeton BENJI runs on ten. Tokenized US Treasuries alone reached $12.88B in April 2026 inside a $27B+ tokenized RWA market growing 300% year-over-year. None of these live institutional products has publicly documented a complete governance model — continuous compliance surveillance, human-in-the-loop gate framework, immutable audit chain — that a trustee, a rating agency, or a regulator can actually rely on. That gap is the addressable market. The governance layer is not commoditized.
Aureon is deployable in three modes against that market: as a governance overlay above existing OMS infrastructure (pre-trade gates, compliance surfaces, DSOR audit artifacts without displacing execution infrastructure); as a full-stack doctrine operating system for a fund or desk building greenfield; or as a pure compliance artifact engine (every decision returns a replayable regulatory submission package). The unifying thesis under all three modes is the same: doctrine was built before the technology, so when market structure shifts — PORTS ships, the GENIUS Act passes, Fed L1 tokenized reserves go live — the doctrine does not change. The rail does. That is the structural advantage, and it is what will be licensed.

# APPENDIX A — OPEN CONFLICTS AND DRIFT LOG
The following items surfaced during canonical synthesis against the deployed April 17, 2026 state and are recorded here for explicit tracking rather than silent resolution. Each requires a documented closure action before the next institutional demonstration.
### Resolved
These items were open in the prior canonical revision and have been closed in this one.
- **Project naming (Arcadia → Aureon). **Deployed code, Framework Brief v2, Agent Specification, and live UI all use Aureon. Canonical treats Aureon as definitive. CAOM-001 requires a clean reissue under the Aureon masthead — operative clauses preserved verbatim.
- **Alpha-origination layer name (Neptune Spear → Atrox). **Live UI renders Atrox. Registered doctrine document is titled Thifur-Atrox. v1.3 provenance record formalizes Atrox above the execution triplet. Neptune Spear retained as the operational nickname in filenames, API routes, and internal pipe functions.
- **Layer count. **Four governance layers canonical (Mentat · Kaladan · Thifur · Verana L0) with Thifur internally decomposed into C2 + R / J / H. Atrox is the advisory intent-origination surface above Mentat, not an independent governance layer.
### Open
Cato version parity. Deployed code is version-mixed (core v0.2.2, cache v0.2.3, docstrings v0.2.1). External MCP README at v0.2.0 / v0.2.1. Action: consolidated v0.2.3 stamp across core, cache, docstrings, and external README in a single commit series with verified identical decisions on identical inputs.
CAOM-001 Tier 0 addendum. CAOM-001 declares three tiers; the deployed code implements a Tier 0 Emergency Halt above all three. Action: issue a CAOM-001 Amendment 001 declaring Tier 0 and binding it to the /api/halt endpoint behavior.
Framework Brief v2 republication. The Brief's layer table still lists "Neptune Spear" at 50,000 ft; the live UI renders "Atrox." Action: republish the Brief to align with the live system.
Thifur-H activation gate. H is architecturally specified but not activated. Agent Specification requires independent SR 11-7 Tier 1 validation before any domain activation. No conflict — this is the documented gating sequence. Tracked for risk-committee visibility: H activation is the next major doctrine event and will require its own risk-committee review.
SVB calibration limit. Cato v0.2.2 catches March 2020 (100%) and September 2019 (80%) but only 45.5% of SVB (March 2023). Recorded as documented calibration limit — Cato is a market-regime gate, not a counterparty-credit gate. Any future extension into counterparty-credit signals (HY OAS, bank equity) will be a formal doctrine amendment with its own backtest and SR 11-7 review.
*— End of Canonical Governing Architecture —*
