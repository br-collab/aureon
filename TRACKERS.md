# Aureon Trackers

## Active — Tech Debt
[Items with explicit trigger conditions. Each entry names what must be true before it's addressed.]

### Phase 4.2 — Pass 2 symbol rename (blocking)
Display-layer rename Neptune Spear → Atrox and Red Wings → Argus
completed April 16, 2026 (server.py and UI). Pass 2 — full symbol
rename — remains outstanding: server.py internal identifiers
(`_neptune_scan`, `NEPTUNE_WATCHLIST`, `_build_neptune_rec`), state
key `aureon_state["neptune_recommendations"]` with Railway volume
migration, routes `/api/neptune/*` → `/api/atrox/*`, signal_type
literal `"NEPTUNE"` → `"ATROX"`, file renames
`aureon/config/neptune_spear.py` → `aureon/config/atrox.py` and
`aureon/mcp/neptune_client.py` → `aureon/mcp/atrox_client.py`,
doctrine narrative rewrite (not find-and-replace — Atrox needs its
own literary/constructed narrative anchor replacing the Operation
Neptune Spear metaphor), source doc filename, equivalent work for
Argus.

**Trigger:** blocks the Thifur-H / Atrox architectural reconciliation
described under Architectural Findings below. Must complete before
Atrox agent implementation can absorb the SIC/PRED/EXEC domains
currently misfiled in `aureon/agents/hunter_killer/_base.py`.

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

**Dependency:** reconciliation requires Pass 2 symbol rename (Phase
4.2) to complete first. See "Phase 4.2 — Pass 2 symbol rename
(blocking)" under Tech Debt.

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

**Closed:** Phase 4.1 (2026-04-18).
