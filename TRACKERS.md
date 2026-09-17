# Aureon Trackers

## Active — Tech Debt
[Items with explicit trigger conditions. Each entry names what must be true before it's addressed.]

### IPS rule engine integration (future)
Phase 4.5 implements `Compliance.validate_ips_eligibility` against a
JSON fixture at `aureon/doctrine/ips_fixture.json` (asset class,
duration, credit rating, currency, issuer concentration, ESG
exclusions). Real deployment requires integration with a commercial
IPS engine (Aladdin, custom) or a full rule-engine build-out.

**Trigger:** first engagement that requires a real fund's IPS
instead of the Endowment Series I / Argus fixture. The loader seam
already exists — `source_path` override on the fixture read lets a
future commercial-vendor adapter plug in without changing
Compliance's public surface.

**Not blocking:** the current fixture is doctrinally representative
enough to exercise the PASS / HOLD flow end-to-end.

---

### Algo inventory ongoing validation (future)
Phase 4.5 implements `Compliance.check_algo_inventory` against a
static fixture at `aureon/doctrine/algo_inventory_fixture.json`
with a 180-day `validation_frequency_days` per registered algorithm.
Real deployment requires automated revalidation triggers on:
algorithm code changes (tied to git commit hash), model updates
(tied to model-governance events under Federal Reserve SR 26-2 / Office of the
Comptroller of the Currency (OCC) Bulletin 2026-13, which supersede SR 11-7), regulatory requirement
changes (DORA / MiFID II / RTS 6 amendment feeds).

**Trigger:** before any live-trading activation that crosses a
180-day boundary past `last_validated_at`. At that point the
fixture's time-based staleness check (implemented in
check_algo_inventory) will correctly surface a MISSING_REGISTRATION
halt — but the operator will want auto-revalidation rather than
manual re-writes of the fixture.

**Not blocking:** paper-trading activation, demo usage.

---

### Atrox doctrine narrative rewrite (non-blocking)
`aureon/config/atrox.py` (renamed from `neptune_spear.py` in Phase
4.2) contains operational-metaphor paragraphs that still describe
Atrox in the Operation Neptune Spear metaphor with just name
substitution. A literary/constructed narrative anchor is needed to
replace the GWOT operational metaphor. Scheduled for a separate
focused prompt — not blocking any other work. User has drafted the
replacement narrative; awaiting an integration prompt.

**Trigger:** the existing prose is mechanically correct (Atrox
instead of Neptune Spear) and causes no runtime issue. Swap in the
new narrative when the user wants Atrox's identity to read as its
own rather than a renamed version of Neptune Spear.

---

### C2 log persistence gap
`c2_task_log`, `c2_handoff_log`, and `c2_lineage_log` are written to
`aureon_state` but NOT included in `aureon/persistence/store.py`
`save_state()` snapshot. They reset on every Railway restart, which
breaks audit-trail continuity for any analysis that crosses a deploy.

Phase 4 (da66610) persists the Phase-4 log (`c2_j_compliance_log`) and
`paused_lifecycles` but deliberately did NOT extend the fix to the
pre-existing C2 logs — scope discipline (one architectural primitive per
prompt). Also not fixed in this prompt: the ThifurC2 instance's in-memory
`_tasks`/`_handoff_log`/`_lineage` registers, which required the
`_reconstitute_task_on_resume` workaround for the Phase 4 resume path
(coordinator.py). Full C2 state persistence is the proper fix.

**Trigger:** any prompt that adds cross-restart audit-trail requirements,
or any regulator-facing demo that will survey lineage across a deploy
window. Until then, the gap is documented but not blocking.

**STATUS — RESOLVED 2026-07-04 (WS-0.1, AUR-ROADMAP-001), pending
operator review + deploy.** Full C2 state persistence implemented:
(1) `store.py::save_state()` now persists `c2_task_log`,
`c2_handoff_log`, `c2_lineage_log`, and a new `c2_registers` key;
(2) `ThifurC2.mirror_registers_into_state()` (called from
`server._save_state()`) mirrors the full `_tasks`/`_handoff_log`/
`_lineage` registers into state before every snapshot;
(3) `ThifurC2.restore_registers()` rebuilds them at boot in
`run_doctrine_stack()` (outside `_lock` — no lock-order inversion; see
lock-discipline note in coordinator.py). `_reconstitute_task_on_resume`
retained as fallback for pre-WS-0.1 snapshots. Verified by
`test_c2_persistence.py` (cross-restart replay: task, handoff, dashboard
logs, doctrine stamp all survive; empty/legacy payloads correctly
no-op). Uncommitted — review then commit as one primitive.

---

### Typed-attribute migration for payload classes
Typed payload classes in `aureon/agents/payloads.py` still accept dict
inputs at many call sites via the `_DictCompatMixin`. That was the
deliberate backward-compat path for 2b6da8c. The eventual target is
that Ranger and JTAC methods accept and return only the typed classes
(no dict fallthrough).

**Trigger:** before adding any new Ranger role (Phase 5+), or before
removing `_DictCompatMixin`.

---

### Deployment SHA not exposed by the running service
Neither `/api/snapshot` (or any other API endpoint) nor Railway edge
response headers expose the deployed git SHA. When a commit is pushed,
the only way to confirm the new SHA is live is to wait the Railway
redeploy window and trust that health still returns 200 — there's no
positive confirmation that the new code is the code serving traffic.

**Trigger:** before the first regulator demo or any external stakeholder
walkthrough where "what version are you running?" needs a crisp answer.

**Scope:** add `RAILWAY_GIT_COMMIT_SHA` (Railway auto-injects this env
var) to `/api/snapshot` response, optionally also `/api/version`.

**STATUS — RESOLVED 2026-07-04 (WS-0.6, AUR-ROADMAP-001), pending
operator review + deploy.** `/api/snapshot` now returns `deploy_sha`
via `server._deploy_sha()` (`RAILWAY_GIT_COMMIT_SHA` → `SOURCE_COMMIT`
→ `"unset"` for local dev). Uncommitted.

### Cato Parity Principle — golden-vector harness (WS-0.2, added 2026-07-04)
The Node decision core was extracted verbatim from the
`get_atomic_settlement_gate` handler into `cato-mcp/gate_core.js`
(pure, no I/O; index.js now requires it — single source of truth for
thresholds AND decision logic). New harness `parity/run_parity.py`
drives gate_core.js and the Python twin
(`aureon/mcp/cato_client.py::atomic_settlement_gate`) with 15 golden
vectors (`parity/cato_golden_vectors.json`): boundary-equal,
boundary-trip, missing-input, multi-trigger, Sept 2019, Mar 2020.
**Result 2026-07-04: 15/15 — identical decisions on both sides, all
matching doctrine expectations.** Finding worth keeping: the SOFR
delta boundary is float-sensitive (a nominal 10.0 bps delta like
5.40−5.30 evaluates to 10.000000000000009 and trips the strict `>`
check identically in both runtimes) — documented in V08. Remaining
for full closure of the canonical §X parity conflict: wire
`run_parity.py` into CI, and note that the harness covers the decision
core, not the live-fetch plumbing around it. Uncommitted.


### Tier 2 Compliance Monitoring operationalized (WS-2.1, added 2026-07-04)
AGENTS.md v0.2 locked all Tier 2 roles on "path inventories not at
skill-file resolution." For AUR-J-COMP-001 that rationale was stale as
of Phase 4.5: `jtac_paths/AUR-J-COMP-001.json` is a formal seven-path
inventory with approval predicates and conflict keys, all callables
implemented, fixtures live. Shipped in this pass: (1)
`AUR-J-PATHSET-COMP-001 v1.0` (Doctrine/) — path-set spec, doubles as
template for the remaining three Tier 2 roles; (2)
`compliance-monitoring-analyst.md` v0.1 DRAFT (first Tier 2 skill
file, written against live code); (3) stale header + get_status
narration in compliance.py corrected. Live-verified 2026-07-04: OFAC
clear, EU match (dual-authority + OFAC_VS_GDPR conflict fired), US
match (single-authority). **Operator approved 2026-07-04; AGENTS.md flipped; divergence logged in canonical §X.** Next Tier 2 by readiness: AML/KYC
(eligibility logic exists in pre-trade structuring), then Risk
Reporting; Trade Surveillance last (scenario library is genuine new
work). Uncommitted.

### Tier 2 AML/KYC built new (WS-2.2, added 2026-07-04)
Canonical §IV assigns "Govern KYC/KYB eligibility verification" to
Thifur-J, but code inspection showed NO prior implementation — the
eight pre-trade gates cover mandate/concentration/notional, not
KYC/KYB. Doctrine assigned it; nobody built it. Shipped: (1)
`kyc_registry_fixture.json` (fictional registry + prohibited/high-risk
jurisdiction lists; source_path seam for commercial KYC utility); (2)
`jtac_paths/AUR-J-AML-001.json` (six-path ladder incl. a new predicate
class — the COMPLETION GATE: kyc_onboarding_complete is satisfiable
only by finishing onboarding, never by override); (3)
`aureon/agents/jtac/aml_kyc.py` (AmlKyc, registered in JTAC_AGENTS);
(4) `c2_j_amlkyc_log` added to persistence snapshot + rehydration;
(5) `AUR-J-PATHSET-AML-001 v1.0` + `aml-kyc-analyst.md` v0.1 DRAFT.
Live-verified: 8/8 cases incl. alias resolution and
prohibited-jurisdiction-without-record → BLOCK (not onboarding).
Operator approved 2026-07-04; AGENTS.md flipped in Project-Atreides. Remaining Tier 2:
Risk Reporting (Kaladan threshold surfaces partially exist), Trade
Surveillance (scenario library = genuine new work). Uncommitted.

### SECURITY: public Tier 0 halt endpoints were unauthenticated (WS-0.7, 2026-07-04)
The `br-collab/aureon` repo and its Railway deployment are **public**.
`/api/halt` (POST) and `/api/halt/resume` (POST) had NO auth — unlike
`/api/admin/reset-state`, which checks `X-Admin-Key`. Anyone reading the
public source could freeze the entire execution surface, or resume a
deliberately-set halt, and the audit record would attribute it to the
operator's default email. Resume is the higher-risk direction.

Fix: added `server._require_admin_key()` (mirrors reset-state; fails
closed if `AUREON_ADMIN_KEY` unset) guarding both POST endpoints; GET
halt-status stays open (read-only). Dashboard (index.html) halt/resume
now prompt for the operator key (in-memory, session-only) and send it
as `X-Admin-Key`, with a 403 handler that clears the cached key.

Doctrinal check: does NOT weaken the Tier 0 invariant. The operator's
GUARANTEED stop path is the Leto kill switch (direct-to-Kraken, bypasses
this HTTP endpoint); Leto only POSTs /api/halt afterward to sync Railway
state and carries the key via its own env. Verified: auth guard unit
test (correct=allow; wrong/missing/unset=deny).

**OPERATIONAL DEPENDENCY — action required:** set `AUREON_ADMIN_KEY` in
the Railway environment. Until it is set, HTTP halt/resume fail closed
for everyone (dashboard included) — the operator can still halt via
Leto/Kraken, but the dashboard button will 403. Also configure the same
key in the Leto env so its post-kill Railway sync succeeds. Uncommitted.

### Tier 2 Risk Reporting built (WS-2.3, added 2026-07-04)
Third Tier 2 role, third distinct provenance pattern: risk SIGNALS
existed (drawdown 5/8, position 20/35, sector 22/25, cash floor 3%)
but only inside per-trade enforcement gates — no portfolio-level
aggregation agent. Shipped: risk_thresholds_fixture.json (consolidated
bands + regulatory anchors), jtac_paths/AUR-J-RISK-001.json (4-path
worst-rung disposition set), aureon/agents/jtac/risk_reporting.py
(RiskReporting, registered), c2_j_risk_log persistence,
AUR-J-PATHSET-RISK-001 v1.0 + risk-reporting-analyst.md v0.1 DRAFT.

DESIGN FIX during build (worth keeping): the interaction test caught
an under-escalation — with DATA_INCOMPLETE ranked above BREACH, a
visible breach concurrent with a missing metric routed to the weaker
single-authority gap-ack instead of dual-authority breach signoff.
Corrected ordering: WITHIN < WARN < INCOMPLETE < BREACH, so a hard
breach always dominates a gap while the report still flags the gap on
every path. Live-verified 6/6. Skill-file approval pending. Only
Trade Surveillance FI remains locked (scenario library = new work).
Uncommitted.

### Tier 2 band COMPLETE — Trade Surveillance built (WS-2.4, added 2026-07-04)
Fourth and last canonical Tier 2 role, the genuinely-new-work one: NO
detection signals existed in code, so the scenario library is authored,
not extracted. Shipped: surveillance_scenarios_fixture.json (wash trade,
marking the close, front running, price deviation, counterparty
concentration; layering/spoofing declared-not-active pending order-book
data), jtac_paths/AUR-J-SURV-001.json (4-path disposition set),
aureon/agents/jtac/trade_surveillance.py (TradeSurveillance, registered),
c2_j_surveillance_log persistence, AUR-J-PATHSET-SURV-001 v1.0 +
trade-surveillance-analyst.md v0.1 DRAFT. Two invariants carried from
Risk Reporting: no pattern auto-disposed (Axiom 2), and monotonic
escalation (ESCALATE dominates data-gap; gap outranks review-flag).
Live-verified 9/9. Skill-file approval pending.

Tier 2 band now COMPLETE: COMP + AML + RISK operator-approved,
SURV built. AGENTS.md v0.5. AUR-INV-001 refreshed to v1.1 (Gap 1
closed). Uncommitted.

### Risk Reporting wired to the live book (WS-2.5, added 2026-07-04)
Turns AUR-J-RISK-001 from "verified on injected inputs" to "running
against the live portfolio." Added server._compute_risk_snapshot()
deriving the four metrics from live state (drawdown from _calc_portfolio;
single-position and sector concentration from positions/class_totals;
liquidity from cash+MMF over total). market_loop runs the agent every 60
cycles (~5 min); _risk_agent is a module-level singleton. READ-ONLY
advisory — emits a disposition to c2_j_risk_log, takes no market action,
halts nothing (Axiom 2). New GET /api/risk/latest surfaces the log for
operator/Leto. Verified: a 53% single-position concentration correctly
routes to RISK_LIMIT_BREACH and logs. Closes the sector-concentration
compute gap noted in AUR-J-PATHSET-RISK-001 §VII (class_totals already
existed; the metric was one division away). Uncommitted.

Live-tasking status of the other Tier 2 agents: Compliance already live
(Phase 4 OFAC in the pretrade lifecycle); AML/KYC and Trade Surveillance
still need their C2-tasking hooks (AML on the pretrade counterparty flow,
Surveillance post-execution) — next WS-2.5 follow-ons.

### AML/KYC + Surveillance wired (WS-2.6, added 2026-07-04)
Completes the Tier 2 live-tasking. Unlike Risk Reporting (clean live
wire — portfolio state has all inputs), AML/KYC and Surveillance need
counterparty / beneficial-owner data the current Argus equity flow does
NOT produce. Forcing a per-trade hook would route every trade to a false
KYC_MISSING_HALT / SURVEIL_DATA_INCOMPLETE — noise worse than silence in
a governance system.

Honest wiring, two-part: (1) on-demand endpoints POST /api/aml/screen
and POST /api/surveillance/screen (invocable against real inputs now);
(2) a GUARDED auto-hook (_run_guarded_tier2_screening) in
api_resolve_decision post-release that runs each agent ONLY when the
released decision carries the fields it requires — otherwise
'skipped_no_data', deliberately NOT a halt. Declare-then-activate: the
hook is dormant until OTC/bilateral counterparty data or beneficial-owner
detail flows through, then lights up automatically. Latest-view GETs
/api/aml/latest, /api/surveillance/latest. Read-only throughout (Axiom 2).

Verified: bare equity decision -> both skipped (no false halt); clean
counterparty -> KYC_ELIGIBLE_CLEAR; prohibited -> AML_PROHIBITED_BLOCK;
front-running surveillance fields -> SURVEIL_PATTERN_ESCALATE. Full
regression green (C2 persistence, 15/15 parity).

All four Tier 2 agents now live-wired: Compliance (Phase 4 pretrade),
Risk Reporting (periodic, WS-2.5), AML/KYC + Surveillance (guarded
post-release + on-demand, WS-2.6). Uncommitted.

### Pre-trade asset-class dispatch layer (WS-P1, added 2026-07-04)
First build of the pre-trade modernization workstream (AUR-PRETRADE-REG-001
§VI). Ahead of the Thifur-J gate set, asset_class_dispatch_fixture.json
selects the gate plan by instrument asset class; _resolve_gate_plan()
returns (gate_id, layer, desc, status) per class. Equities and any unmapped
class get exactly the base 8 active gates — ZERO behavior change from
pre-P-1 (verified). A class may declare additional gates; a gate 'declared'
but not yet implemented routes to HOLD, never a silent pass
(gap-completeness invariant at the pre-trade layer).

Interaction finding + fix: _gate_mandate hard-FAILed any class outside the
equity-era APPROVED_ASSET_CLASSES, pre-empting the declared gate. Made it
dispatch-aware — a dispatch-recognized class (has a declared eligibility
gate) HOLDs ('recognized, pending capability') rather than FAILs; a
genuinely unknown class still FAILs. Loop precedence: FAIL > HOLD > WARN >
PASS, so a real OFAC FAIL still blocks a tokenized instrument whose
eligibility gate would only HOLD.

Verified: equity PASS (unchanged, 8 gates); fixed_income HOLD on declared
MIFIR gate; tokenized/digital HOLD on declared eligibility gate;
unknown-class BLOCKED; tokenized+OFAC BLOCKED (FAIL beats HOLD). Full
regression green (C2 persistence, 15/15 parity).

Boundary respected: FICC clearing/settlement gating is Atreides, not this
layer — the fixed_income class carries only the MiFIR pre-trade
transparency gate. Foundation for P-2 (FI transparency) and P-3 (tokenized
eligibility). Uncommitted.

### Tokenized-instrument pre-trade eligibility gate (WS-P3, added 2026-07-04)
Turns the P-1 tokenized/digital HOLD into a real PASS/HOLD/BLOCK. Third
pre-trade gate; completes the P-1/P-2/P-3 arc.

- tokenized_eligibility_fixture.json: MiCA/GENIUS issuer register (status
  AUTHORIZED/PENDING/REVOKED), supported rails, known custody classes.
  source_path seam for a live register feed. Fictional issuers keyed to
  the estate's real tokenization threads (Franklin, Circle, Ondo, Galaxy CLO).
- _gate_tokenized_eligibility: three checks, most-restrictive — issuer
  authorization (AUTHORIZED->continue; PENDING->HOLD; REVOKED/unknown->
  BLOCK, MiCA delisting), supported settlement rail exists (unknown->HOLD;
  atomic-vs-FICC viability stays Cato's at settlement), custody-object
  class known (unknown->HOLD). Never a silent PASS.
- dispatch fixture: tokenized + digital TOKENIZED_ELIGIBILITY flipped
  declared -> active.

Interaction fix: replaced the P-1 mandate blanket-HOLD for recognized
classes with _class_dispatch_state() — a class GOVERNED by an active
eligibility gate PASSes mandate (defers to that gate); a class with only
DECLARED gates HOLDs; genuinely unknown FAILs. So an authorized tokenized
instrument now fully PASSes pre-trade.

Verified: authorized PASS; pending-issuer HOLD; revoked/unknown BLOCKED;
unsupported rail HOLD; digital alias works; equity unchanged. Full
regression green (C2 persistence, 15/15 parity). Pre-trade is now
asset-class-aware across equity / fixed income / tokenized / digital.
Uncommitted.

### Two divergent pre-trade gate engines (finding, 2026-07-04)
The estate has TWO parallel pre-trade gate implementations:
(1) ThifurJ.structure_pretrade_record (aureon/agents/jtac/
pretrade_structuring.py) — the C2-lifecycle gates, now asset-class-aware
(P-1/P-2/P-3: dispatch + MiFIR + tokenized eligibility, emits HOLD);
(2) policy_engine.evaluate_pretrade_decision (aureon/policy_engine/
service.py) — a separate equities-only gate set (MARKET_STATUS,
CASH_SUFFICIENCY, POSITION_CONCENTRATION, DRAWDOWN_LIMIT, ...) that the
LIVE dashboard "Pre-Trade Routing" modal (/api/pretrade-check) calls.

Consequence: P-2/P-3 (MiFIR transparency, tokenized eligibility) do NOT
appear in the operator's live pre-trade modal — that screen runs engine
(2), which is not asset-class-aware and never emits HOLD. The new gates
DO surface in the DSOR replay / trade-report gate views, which render
ThifurJ gate_results.

UI fixes shipped this pass (index.html): HOLD now renders orange (dot +
badge + both gate-list color maps) instead of red — it was reading as a
hard block. And the pre-trade modal's overall-status handler gained a
HOLD branch that DISABLES execute (fail-safe: a held gate must not be
executable) instead of falling through to "all gates PASSED + execute
enabled". The modal fix is defensive today (engine 2 doesn't emit HOLD
yet) and becomes load-bearing on convergence.

Follow-on (not yet done): converge the two engines — route the live
modal through the ThifurJ asset-class dispatch (or align engine 2 to it)
so P-2/P-3 actually appear on the operator's pre-trade screen. Also
stale: dashboard title still says "Equities Pre-Trade Governance
Dashboard" — pre-trade is now multi-asset-class.

### Pre-trade engine convergence (WS-P4, added 2026-07-04)
Resolves the two-divergent-pre-trade-engines finding. The live modal's
engine (policy_engine.evaluate_pretrade_decision) now appends the ThifurJ
asset-class gates so the operator's pre-trade screen is asset-class-aware.

- ThifurJ.asset_class_gates(decision): returns ONLY the asset-class-specific
  additional gates (MiFIR transparency, tokenized eligibility) — base gates
  stay the live engine's responsibility, no duplication. Active gates run;
  declared gates HOLD; equities/unmapped -> [] (zero change). Never fails
  open (error -> HOLD, not pass).
- evaluate_pretrade_decision: new asset_class_gate_fn param; appends the
  extra gates; aggregate precedence now FAIL/BLOCKED > HOLD > WARN > PASS.
- server: api_pretrade_check passes _agent_j.asset_class_gates; timeout
  fallback aggregate made HOLD-aware too.

The modal HOLD-handling shipped last pass is now load-bearing: a bond
without evidenced transparency, or a pending/revoked token issuer, now
HOLDs/BLOCKs the live EXECUTE button instead of appearing executable.

Verified: equity unchanged (6 gates, PASS); FI-unpublished -> MiFIR HOLD
-> overall HOLD; FI-published -> PASS; tokenized authorized -> PASS;
revoked -> FAIL; pending -> HOLD. Full regression green (C2 persistence,
15/15 parity). The two pre-trade engines are now aligned; ThifurJ gates
remain the single source of truth for asset-class rules.

### Correction: multi-asset decisions already originate; only tokenized/digital lack a front door (2026-07-04)
Earlier session notes stated decisions "only originate as equities." Code
inspection (server._generate_signal + INITIAL_POSITIONS) corrects that:
the live Argus book is multi-asset (equities, fixed_income AGG/TLT/HYG,
real_assets VNQ/GLD, absolute_return BTAL/CTA) and the Thifur-H signal
engine does drift-aware rebalancing keyed by asset class. So fixed_income
rebalance decisions ALREADY originate with asset_class=fixed_income and
now flow through the P-2 MiFIR gate at pre-trade.

What genuinely has no origination path is TOKENIZED / DIGITAL: there are
no tokenized/native-digital positions to rebalance and no tokenized
candidates in the signal pools, so those decisions can only enter via the
API (/api/pretrade-check on an injected decision, or the on-demand screen
endpoints). The "missing front door" is therefore narrow: an operator
affordance to ORIGINATE a tokenized/digital order, not all non-equities.

Entry into the gates (both asset-class-aware after P-4): (1) live modal
via /api/pretrade-check -> evaluate_pretrade_decision (appends
ThifurJ.asset_class_gates); (2) C2 lifecycle via
ThifurJ.structure_pretrade_record. The decision's asset_class field is
the single key the dispatch reads.

### Operator order-entry front door (WS-P5, added 2026-07-04)
Closes the last pre-trade gap: an operator affordance to ORIGINATE an
order of any asset class — including tokenized/digital, which had no
signal-engine origination path. Governed origination (operator PM role,
Axiom 2): the created order is PENDING and still requires the pre-trade
check + human approval; never auto-executed.

- server POST /api/decisions/create: validates (symbol, action BUY/SELL,
  asset_class, notional>0), fails closed on halt (423) and queue-full
  (12, 409), constructs a decision matching the Thifur-H signal schema
  plus the asset-class fields the gates read (token_issuer_id /
  settlement_rail / custody_class; instrument_subtype / bond_liquidity /
  pretrade_published / waiver_claimed), journals it.
- index.html: "＋ NEW ORDER" header button + modal with asset-class
  dropdown that reveals FI (MiFIR) or tokenized (eligibility) fields;
  posts, then refreshes the queue.

Verified (endpoint logic): operator-originated tokenized order ->
pre-trade PASS on authorized issuer, FAIL on revoked, FI unpublished ->
MiFIR HOLD. Full regression green. UI form built by inspection — needs
one browser click-through to confirm visually. Pre-trade pipeline is now
end-to-end for all four asset classes: originate -> dispatch -> gates ->
disposition -> approve.

WS-P5 UI verified live 2026-07-04 via browser click-through on the
Railway deploy: ＋ NEW ORDER opens, asset-class -> tokenized reveals the
eligibility panel and suppresses the FI fields, submit created
DEC-E6AA8198 (OUSG/BUY/tokenized/$750k, PENDING, origin OPERATOR), and
its pre-trade check returned TOKENIZED_ELIGIBILITY=PASS (issuer
ONDO_OUSG AUTHORIZED) with an overall FAIL driven by CASH_SUFFICIENCY —
i.e. the asset-class gate fired on operator-originated intent and
precedence held. Nothing auto-executed. Test order then discarded via
the existing Reject path (see WS-P6 finding). "Needs one click-through"
is now closed.

### Discard path already exists; DECISION_WITHDRAWN deferred (WS-P6, added 2026-07-04)
Correction on the record. While verifying WS-P5 I asserted there was "no
cancel/reject endpoint" for a pending decision and proposed building one.
That was a probe error: I tested only `/reject`, `/cancel` sub-paths and
DELETE, and missed that reject is a *resolution value* on the base route.
The discard path was already fully wired:

- server `POST /api/decisions/<id>` with `{resolution:"REJECTED"}` removes
  the decision from `pending_decisions`, executes nothing, journals
  `DECISION_REJECTED`, and writes a Commander's-log entry. Passes through
  the CAOM-001 session guard like any resolution.
- index.html:4790 renders a "Reject" button on every pending decision
  card; `resolveDecision(id,'REJECTED')` calls the above and refreshes.

Verified live: rejecting DEC-E6AA8198 returned status "rejected", queue
went to 0, no trade. So the WS-P5 front door already has a matching exit.

Deferred (not built): a semantically-distinct `DECISION_WITHDRAWN`
disposition. Rationale for building it later — REJECT and WITHDRAW are
functionally identical today but audit-distinct: REJECT = authority
declined a reviewed order on the merits; WITHDRAW = originator retracted
un-reviewed intent (fat-finger). Conflating them inflates the rejection
population that a surveillance rule / audit sample / rejection-rate
metric might read as signal. Trigger to build: **CAOM seat separation**
(originator and approver become different people) OR the first time a
downstream consumer reads rejection counts as a risk signal. Until then
the existing Reject button is the discard path. Low priority; single
operator holds both seats today, so the split buys nothing now.

### Gate 6 (macro stress overlay) has never evaluated since 9cfbb9e (finding, 2026-09-14)
`policy_engine.evaluate_pretrade_decision` gate 6 has not evaluated since
it landed in 9cfbb9e (2026-04-04). Two independent defects:

- **Wrong arity.** It called `ofr_snapshot_fn()`; the function passed in,
  `_get_ofr_stress_snapshot(macro_snapshot)`, requires an argument
  (`evidence_service` calls it correctly). Every call raised `TypeError`.
- **Wrong key.** It read `stress_score`; the snapshot carries `fsi_value`.

The bare `except Exception` turned the `TypeError` into
`PASS — "Macro overlay unavailable — proceeding"`. Verified: with a severe
reading of 2.50 the gate returned PASS.

**Fixed on `governance-core-fail-closed`:** correct arity and key; an
unusable reading (missing, NaN, ±inf, non-numeric) or an unreadable feed
HOLDs, matching Cato v0.3.1 / golden vector V16; the pre-trade route reads
`_ofr_cache` only, so the gate never fetches inside the request. The 0.7
WARN threshold is unchanged pending the STLFSI4 index decision below.

**What the evidence record actually says** (checked, not assumed):

- Operator-facing: the pre-trade modal showed `MACRO_STRESS_OVERLAY: PASS`
  for every decision in the window. That result was never persisted.
- `trade_reports[].gate_results` is `[]` for every report —
  `resolve_pending_decision` passes an empty list ("populated by pre-trade
  check" is not true). No trade report records a gate-6 PASS; none records
  any pre-trade gate.
- `decision_journal[].pretrade_gates` is `[]` after approval: the entry is
  built after the decision leaves `pending_decisions`.
- Trade reports DO carry `ofr_fsi_at_exec` / `ofr_band_at_exec`, captured
  through the correct call — the OFR FSI (or its FRED proxy) at execution,
  not STLFSI4, with no field saying which source produced it.
- A second gate-6 copy, `server._build_pretrade_checks_from_cache` (the
  8-second timeout fallback), reads `aureon_state["ofr_stress_index"]`,
  which nothing ever writes — it can only return PASS. `session_protocol`
  reads the same never-written key, so its OFR stress warning never fires.

**Trigger:** before any trade report from 2026-04-04 onward is used as
pre-trade evidence (audit sample, SR 11-7 validation, a regulator request).
Disclosure proposal, not yet implemented: an append-only errata collection
keyed by defect and date range, rendered with each affected report and in
compliance PDFs, never rewriting a hashed report; persist the pre-trade
payload actually shown to the operator into the trade report at approval;
add `ofr_source_at_exec`. Fix the cache-fallback gate 6 and the
`session_protocol` key in the same changeset.

---

## Active — Architectural Findings
[Observations about the system that shape future decisions but aren't prescriptive.]

### Two OFAC enforcement axes — intentional, complementary, do not consolidate
Aureon implements OFAC sanctions screening at two distinct points in the
lifecycle. They are **not redundant** and should not be merged.

- **`ThifurJ._gate_ofac`** (AUR-J-TRADE-001, in
  `aureon/agents/jtac/pretrade_structuring.py` as part of the 8-gate
  `_run_gate` dispatch). Screens **INSTRUMENT ISINs** against
  `MANDATE_LIMITS["ofac_blocked_isins"]`. Hard-stop semantics — no
  human override clears a sanctioned instrument.

- **`Compliance.screen_ofac`** (AUR-J-COMP-001, Phase 4 da66610, in
  `aureon/agents/jtac/compliance.py`). Screens **COUNTERPARTY NAMES**
  against `aureon/doctrine/sdn_fixture.json`. Halt-and-pend semantics
  — operator may override with attribution (legitimate humanitarian
  license, OFAC general license, frozen-asset transactions).

The distinction is structural: instrument matches are unambiguous and
terminal; counterparty matches carry false-positive risk and may have
legally authorized handling. Both must run; they catch different
failure modes. See the Compliance docstring for the cross-reference.

**Trigger for future contributors:** if someone proposes "consolidating
OFAC into one place," read this entry first.

---

### Aureon's JTAC registry is keyed by role_id; operational strings separately
`JTAC_AGENTS` dict is keyed by `role_id` (e.g. `"AUR-J-COMP-001"`),
matching the Ranger convention. The operational agent-identifier string
`"THIFUR_J"` in `AGENT_J = "THIFUR_J"` (coordinator.py), authority-log
entries, handoff `agents` lists, and persisted position records is a
separate identity and stays unchanged. Changing it would rewrite
historical audit-trail records — not a rename, a data migration.

**Implication:** when a future phase introduces registry lookup for
ThifurJ (currently called directly as `agent_j`), the lookup is
`JTAC_AGENTS["AUR-J-TRADE-001"]`. The `"THIFUR_J"` string stays in
operational code.

---

### Thifur-H current implementation doctrinally misfiled
`aureon/agents/hunter_killer/_base.py` contains 531 lines of
alpha-origination logic (SIC spread detection, predictive markets
timing, execution strategy optimization) that per Atrox (formerly
Neptune Spear) doctrine belong in Atrox's Trade Origination / Market
Intelligence / Product Recommendations domains. Thifur-H's actual
doctrinal role is C2-tasked advisory adaptive intelligence (Portfolio
Risk / Model Risk / Data Governance per AUR-PT-EFICC-001 for post-trade
eFICC; equivalent roles under different objective functions for
Arcadia Fund deployment context).

**Reconciliation:**
(a) extract current ThifurH logic into Atrox agent implementation;
    Atrox produces recommendations requiring human approval before
    flowing through Kaladan → Thifur-C2 → Thifur execution triplet,
(b) rebuild Thifur-H fresh as C2-tasked advisory adaptive intelligence
    per deployment context,
(c) wire Atrox into Phase 4 halt-and-pend approval-gate pattern,
(d) wire Thifur-H into C2 task dispatch pattern.

**Dependency:** Pass 2 symbol rename completed in Phase 4.2 — no
longer blocking. Reconciliation prompt (extract alpha-origination
logic into Atrox agent, rebuild Thifur-H as C2-tasked advisory
adaptive intelligence) can be scheduled whenever.

**Phase 4.1 scope note:** `HUNTER_KILLER_AGENTS` registry key
remained `"THIFUR_H"` (unchanged) — rekeying into `AUR-H-*` role_ids
is not meaningful until the reconciliation above decides what the
Tier-3 roles actually are.

---

### Class: a failure that reads as success (finding, 2026-09-14)
One defect class, not a list of unrelated bugs: a code path that cannot
tell "checked and clear" from "could not check", and reports the second as
the first. Each instance below turns a missing input, a raised exception or
an undelivered message into a normal-looking success value.

| Instance | Where | Reads as | Status |
|---|---|---|---|
| Missing OFR stress reading | Cato `gate_core.js` / `cato_client.py` | PROCEED, "all doctrine thresholds clear" | Fixed — Cato f34d375 (v0.3.1), aureon mirror c2bfd9d, golden vector V16 |
| Macro stress feed unavailable | `policy_engine` gate 6 | PASS | Fixed on `governance-core-fail-closed`, completed by W2B-3/F1 (a fabricated reading is INDETERMINATE) — see the gate 6 entry under Tech Debt |
| Failed or rejected OMS send | `release_control.release_to_oms` | RELEASED / RELEASED_SEND_FAILED on a normal return | Fixed — 79d48f6 (raises `OMSReleaseError`, 502) |
| Alpaca upstream failure | `server.py` Alpaca endpoints (three instances of "Alpaca API request failed") | HTTP 200 with `status: error` | Open — on `main` since 28f39e3 (Railway agent, 2026-04-13) |
| Missing pipe `status` key | `server.py` doctrine-stack pipe log line | `UNKNOWN`, masking a missing key | Open — on `main` since 7edf26d (Railway agent, 2026-04-10) |
| Timeout-fallback gate 6 | `server._build_pretrade_checks_from_cache` | PASS from a state key nothing writes | **Closed by W2B-3** — the function is deleted; the timeout path reruns the same engine without the FRED fetch |
| Session-open OFR warning | `session_protocol` | no warning, from the same unwritten key | Open — found 2026-09-14 |
| EMS "release" | `ems_adapter.build_execution_release` | `status: SENT` on a packet that is only built, never transmitted | Open — found 2026-09-14 |
| FRED STLFSI4 fetch fails | Cato `index.js` gate handler, `value ?? "0"` | PROCEED, "All doctrine thresholds clear" | Fix open — Cato-FICC-MCP#2; tracked in #12 |
| FRED outage feeds a fabricated stress reading | `_fallback_macro_snapshot` → `_fallback_ofr_snapshot` → twin, gate 6, `ofr_fsi_at_exec` | a measured-looking 0.38 | **Closed by W2B-3/F1** — see the entry below; #11, #12 |

**How to apply:** when a check's input is absent, malformed or
unreachable, the result is HOLD (or an exception the caller must handle),
never the value that means "clear". Treat `except Exception: <success>`,
`.get(key, <clear value>)` and "return 200 on error" as review flags.

---

### A fabricated number in an audit artifact: `ofr_fsi_at_exec` during a FRED outage (finding, 2026-09-14)
Instance of "a failure that reads as success", logged on its own because
the output is not a status flag but a number stored as evidence.

When FRED is unreachable, `_get_fred_macro_snapshot` falls back to
`_fallback_macro_snapshot`, which returns fixed constants (VIX 24.0, HY
OAS 4.25, curve −47 bps). When the OFR scrape also fails,
`_fallback_ofr_snapshot` turns those constants into `fsi_value = 0.38`,
band "watch", `source: "ofr_proxy"`. That 0.38 is then:

- handed to the Python twin by `_cato_refresh_inputs` as a usable reading
  (the twin PROCEEDs; its v0.3.1 guard never sees an unusable value);
- read by gate 6 as a usable reading;
- written into trade reports by `evidence_service` as
  `ofr_fsi_at_exec = 0.38`, `ofr_band_at_exec = "watch"`, with **no field
  recording that it was not measured** (the `source` is dropped).

Reproduced offline on 2026-09-14: an approval with every feed down stored
`ofr_fsi_at_exec: 0.38` in the trade report.

**Parallel:** br-collab/cepti branch `quarantine/phase2-overnight`. There,
`docs/sma/PHASE2_E2E_IMPLEMENTATION_SUMMARY.md` presents an E2E results
block ("7 passed, 0 failed … All tests PASSED!", with per-test durations)
for a suite whose own tip commit (a20541e) says the scripts could not be
executed directly, and `scripts/sma/e2e-test-performance.ts` derives
per-platform publish time by assuming "~3 platforms". Same output class — a
plausible, specific number standing in for one that was never observed —
different mechanism: a code fallback there is a written summary here.

**Trigger:** the evidence errata work (approved 2026-09-14) —
`ofr_source_at_exec` plus an erratum covering reports stored while the
proxy or fallback constants were in effect. Removed at the source by the
STLFSI4 ingest contract (#11): no proxy, no constants, an unreadable feed
holds.

**Closed by W2B-3/F1 (2026-09-17).** Every macro and OFR snapshot now
carries provenance (`aureon/policy_engine/evidence.py`): `FACT_EXTERNAL`
for a published reading, `POLICY_RESULT` for the proxy computed from live
FRED series, `FABRICATED_DEFAULT` whenever a fixed constant entered the
chain. An unlabelled snapshot counts as fabricated.

- **Gate 6:** fabricated → `INDETERMINATE`, so approval is refused through
  every path. A proxy over live FRED is evaluated, states
  `source=ofr_proxy`, and HOLDs at or above the 0.70 warning threshold.
- **Cato:** `_cato_refresh_inputs` passes no reading at all when the value
  is fabricated, so the twin's own fail-closed guard holds.
- **Audit:** `ofr_fsi_at_exec`, `ofr_band_at_exec` and
  `macro_regime_at_exec` are `null` when the reading is fabricated, with
  `market_evidence_unavailable_reason` saying why, plus
  `systemic_overlay_provenance`. Reports stored before this change still
  hold 0.38; the errata above remains the way to read them.
- **Dashboard:** the OFR tile reads "NO READING · feed unavailable", and a
  proxy reading is marked PROXY.
- Tests: `test_stress_evidence_provenance.py` (13).

---

### AUR-I-18 (P1): Thifur-H books its ledger from the Kraken acknowledgement, not from the fill (finding, 2026-09-17)

Found while verifying W2B-4. `thifur_h.py` writes `ledger.open_positions[order_id]`
as soon as Kraken returns a transaction id for a maker-or-cancel limit order,
and records the **signal's** suggested price and quantity. A placement is not an
execution: the order can rest unfilled, be cancelled, or fill later, partially,
at another price. The exit path then estimates profit and loss "assuming
immediate-fill semantics", and nothing reconciles it against Kraken.

This is the AUR-I-02 / AUR-I-06 defect class — booking from intent, and an
execution record derived from the intent it should be checked against — on the
**live-money** path. Wave 2 fixed it for the paper path only
(`aureon/booking/consumer.py` books from a fill; `aureon/booking/reconcile.py`
compares intent with execution).

It does **not** touch `aureon_state` cash, positions or trades, so the paper
book is unaffected. What is affected is Thifur-H's own ledger and the DSOR
entries and profit-and-loss figures derived from it — the evidence for the live
account.

**Not fixed in Wave 2, by instruction:** it touches the live Kraken account, so
Bill decides when it is built. Design note:
[`aureon/thifur/NOTE-AUR-I-18.md`](thifur/NOTE-AUR-I-18.md) — book from
`TradesHistory` fill events, reuse the Wave 2 fill shape with
`provenance: FACT_EXTERNAL`, accumulate partial fills with idempotency by trade
id, and backfill or relabel positions opened before the fix.

---

### AUR-I-19 (P2): one operator key can act in every role (finding, 2026-09-17)

`approval_role` is chosen in the request body and checked against nothing. The
same key can approve as TRADER, then as RISK, then as COMPLIANCE, so the
routing quorum (AUR-I-08) and the HOLD-exception authority (W2B-3) record roles
that are not independent people.

Accepted for now under CAOM-001, which is explicitly a single operator
(JUM-D-15). What Wave 2 does about it (fix F4) is disclose it rather than imply
independence:

- every authority record states `role_source: "request_body"` and
  `independence_asserted: false`;
- the ApprovedIntentEnvelope's authority manifest carries the same, plus
  `operating_mode: "CAOM-001 single operator"`;
- the dashboard shows a single-operator note beside multi-role approvals.

**The real fix is the actor registry (JUM-D-18), in Wave 4:** per-role
entitlements, and an approval refused when the actor does not hold the role.

---

### Commit record correction: 9cfbb9e understates the governance core (2026-09-14)
9cfbb9e (railway-app[bot], 2026-04-04) is titled "fix: create aureon
subpackage stubs to unblock gunicorn import of server:app". History is not
rewritten; this is the accurate description of what it added:

```
feat(governance): extract the governance core into aureon/ — approval,
pre-trade policy, evidence, persistence, OMS/EMS/FIX adapters

1,143 lines across 15 files. Seven are empty __init__.py package markers
that make aureon.* importable so gunicorn can load server:app. The other
eight are the domain layer server.py now delegates to:

- approval_service/service.py (268): resolve_pending_decision, HITL
  approve/reject lifecycle, _apply_trade books positions and cash
- approval_service/release_control.py (190): Decision model, role gating
  (missing_roles, can_release), release_to_oms packet
- policy_engine/service.py (221): evaluate_pretrade_decision — market
  status, cash, concentration, drawdown, OFAC/SDN, macro stress
- evidence_service/service.py (162): build_trade_report compliance record
- persistence/store.py (133): save_state / load_state with corrupted-JSON
  salvage
- integration_adapters/oms_adapter.py (44), ems_adapter.py (56),
  fix_adapter.py (69): simulated OMS ack, EMS release packet, FIX 4.4
  NewOrderSingle builder and send stub

Authored by the Railway agent to clear a boot failure; recorded as a stub
fix, it is the first commit of the extracted governance core.
```

The same content, at pre-purge hash 3a9a1d5, was the tip of
`railway/code-change-NHS_v0`.


## Active — Operational Findings
[Deployment, infrastructure, and production-observability concerns.]

### Railway auto-PR agent keeps re-adding catch-all Flask route
Reference memory: `feedback_railway_agent.md`. The Railway auto-PR agent
has repeatedly opened PRs that add a catch-all Flask route that shadows
`/api/*` and `/mcp`. This is an external-system regression, not something
in our code, but it needs ongoing vigilance.

**Trigger:** review any Railway-originated PR for this pattern before
merging. If seen, close the PR and do not merge.

---

### Railway autodeploy window has no positive SHA confirmation
After `git push`, the Railway redeploy window is ~60–180s; there is no
way from the running service to confirm that the new SHA is the one
serving traffic (see "Deployment SHA not exposed" under Tech Debt).
Current practice: wait, probe health endpoints, trust 200 responses.

**Trigger:** see the Tech Debt entry. Same fix addresses both.

---

### Railway branch fhvO9j: a second approval route without the CAOM-001 session guard (2026-09-14)
`railway/code-change-fhvO9j` tip d2f8d27 (railway-app[bot], 2026-04-05)
adds `POST /api/decisions/<decision_id>/approve`, a copy of the approval
handler under a second URL. Unlike `api_resolve_decision` on `main` it:

- has **no CAOM-001 session guard** (main returns 403 when no session is
  open), so it would approve and release outside an open session;
- takes `approval_role` from the request body, defaulting to `TRADER`;
- calls `release_to_oms` and ignores a failed release.

Never merged. It was the only commit on the seven `railway/*` branches not
already on `main`; the other six branches carried only commits already on
`main` (by patch identity). All seven branches still carried pre-purge
commit hashes; their unique objects were scanned and contain no purged
paths, gitlinks, or key-shaped strings.

**Trigger:** any Railway-originated PR or branch that adds a route touching
approval, release or execution. Check it against `api_resolve_decision`'s
guards (session, halt, role) before merging; a second path to the same
action must carry every guard the first one does.

---

### Stale Cato copies on this public repository (logged 2026-09-14, not fixed)
`CATO DEMO/` and `eFICC - MCP/` are tracked on `main` and referenced by
nothing else in the repository.

- `CATO DEMO/index.js` and `CATO DEMO/cato_client.py` are a **v0.2.2** copy
  of the Cato server and twin, and carry the defects since fixed upstream:
  the gate handler's `ofr_stress_index?.value ?? "0"` (a FRED outage reads
  as PROCEED; Cato-FICC-MCP#2), and the twin's
  `ofr_stress if ofr_stress is not None else 0.0` with no v0.3.1
  usable-reading guard at all (Cato f34d375 / aureon c2bfd9d). It also
  carries the hardcoded 0.5 bps / 40% cost literals.
- `eFICC - MCP/eficc-mcp-index.js` is an older read-only FICC data server
  with no gate logic; it reads STLFSI4 for display. Stale, but it does not
  carry the gate defects.

**Trigger:** before anyone points a reader at this repository as a
reference for Cato — a public copy of the gate with the pre-fix defects
reads as current code. Remove, or replace with a pointer to
br-collab/Cato-FICC-MCP.

---

### Boot warning misstates what FRED_API_KEY controls (logged 2026-09-14, not fixed)
`server._atrox_refresh_loop` warns at boot that without `FRED_API_KEY` "the
SOFR and OFR fetches 400" and that CATO-F "reuses the same OFR STLFSI4
band". The OFR reading does not come from FRED at all — it is a scrape of
financialresearch.gov with a FRED-derived proxy fallback — and CATO-F in
aureon is fed only from request bodies and demo constants. The warning
points an operator at the wrong cause.

**Trigger:** fix with the STLFSI4 ingest contract (#11), when the stress
reading does come from FRED and the warning becomes true.

---

### CLAUDE.md says the twin reads OFR STLFSI4 (logged 2026-09-14, not fixed)
CLAUDE.md's Cato section ("Live market data flow") says
`_cato_refresh_inputs` reads "OFR STLFSI4 from the existing `_ofr_cache`".
`_ofr_cache.fsi_value` is the OFR Financial Stress Index (or its proxy),
not FRED STLFSI4 — the divergence tracked in #11.

**Trigger:** correct in the same change set as #11, so the document never
describes the twin's input as something it is not.

---

### A live-execution loop starts at import (logged 2026-09-14, not fixed)
CLAUDE.md says background threads start from `_start_background_threads()`
via gunicorn's `post_fork`, "not at import time". `server.py:8761` calls
`_atrox_live.start()` at module top level, so importing `server` — a worker,
a test (`test_c2_persistence.py` imports it), a script — starts the Atrox
Live loop, which is wired to `execute_close_signal`. Observed 2026-09-14:
importing `server` in a test harness logged "Atrox Live loop started
(interval=300s)".

**Trigger:** before any test or tool imports `server` in an environment
holding Kraken credentials. Move the start into
`_start_background_threads()`, or correct CLAUDE.md if import-time start is
intended.


## Closed
[Items that have been addressed. Commit SHA + date.]

### Typed-payload validation hardening (status fields)
`TradeReconciliationResult` and `LineageCheckResult` declared `status`
required via `_validate_required` but defaulted to `""`, causing the
validator (which checks `is None`) to silently pass. Defaults changed
to `None`.

**Closed:** 8c0afa1 (2026-04-18). Audit went from 9 PASS / 2 FAIL to
11 PASS / 0 FAIL.

---

### Dead `agent_r=None` parameter in ThifurC2.process_pretrade_lifecycle
Signature carried an `agent_r=None, # ignored — resolved via RANGER_AGENTS`
placeholder from Phase 3a transition. No caller required it after
Ranger registry integration completed. Removed.

**Closed:** e0e713a + 8c0afa1 (2026-04-18).

---

### JTAC file-layout alignment to Ranger convention
`aureon/agents/jtac/_base.py` originally held the full `ThifurJ` impl,
diverging from the Ranger pattern where `_base.py` holds the concrete
base and each role lives in its own file.

**Closed:** 5ae7b66 (2026-04-18). `ThifurJ` moved to
`aureon/agents/jtac/pretrade_structuring.py`; `JTAC_AGENTS` re-keyed
`"THIFUR_J"` → `"AUR-J-TRADE-001"` to match the Ranger convention.
`_base.py` now holds `JTACConcreteBase` as of da66610.

---

### JTAC base unification
Phase 4 (da66610) introduced `JTACConcreteBase` but left `ThifurJ`
(AUR-J-TRADE-001, 596 lines) inheriting `JTACAgent` directly. Two
JTAC bases coexisted temporarily. Phase 4.1 retrofitted `ThifurJ`
onto `JTACConcreteBase`. Audit confirmed the retrofit was clean —
no conflicts with any base method, zero behavior changes. 8/8 gate
outputs preserved, all four Phase 4 lifecycle scenarios still pass,
typed-payload audit still 23/23.

**Closed:** bcf7590 (2026-04-18).

---

### Phase 4.2 — Pass 2 symbol rename (Neptune Spear → Atrox, Red Wings → Argus)
Display-layer rename completed April 16, 2026 (Pass 1). Pass 2 —
full symbol rename across internal identifiers, state keys with
Railway volume migration, Flask routes, signal-type literals, file
renames, imports, and doctrine prose — completed in Phase 4.2.

Scope of Pass 2: 601 replacements across 546 lines in 18 files.
Two files renamed via `git mv`:
  `aureon/config/neptune_spear.py` → `aureon/config/atrox.py`
  `aureon/mcp/neptune_client.py` → `aureon/mcp/atrox_client.py`
State-key rename `neptune_recommendations` → `atrox_recommendations`
implemented as a three-step safe migration in
`aureon/persistence/store.py::migrate_neptune_to_atrox` (copy →
verify → delete only on verification success). Idempotent. Covers
pre-existing Railway volume data.

The two doctrine-audit hash seeds (`b"AUREON-DOCTRINE-1.3-NEPTUNE-C2"`
at server.py:320 and server.py:4211) were preserved byte-identical —
changing them would alter the deterministic audit hash value and is
doctrine-version territory, not a rename. Flagged pre-change; left
intact by design.

Red Wings → Argus half of the rename was a no-op: Pass 1 had fully
cleared all code references; only TRACKERS.md historical prose
remained.

Atrox operational-metaphor narrative rewrite intentionally deferred
— see "Atrox doctrine narrative rewrite (non-blocking)" under Active
— Tech Debt.

**Closed:** Phase 4.2 (2026-04-18).
