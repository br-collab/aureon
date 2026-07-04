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
(tied to SR 11-7 model-governance events), regulatory requirement
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
