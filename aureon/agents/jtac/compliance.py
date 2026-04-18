"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/jtac/compliance.py                                    ║
║  Compliance — AUR-J-COMP-001                                         ║
║                                                                      ║
║  MANDATE (Phase 4 scope):                                            ║
║    OFAC counterparty screening against fixture SDN list.             ║
║    Exact-match semantics. Halt-and-pend on match.                    ║
║    Emit JTACPathSelection and (on conflict) ConflictResolution.      ║
║                                                                      ║
║  DUAL-AXIS OFAC ENFORCEMENT (see TRACKERS.md):                       ║
║    This role screens COUNTERPARTIES by name. Phase 4 is              ║
║    exact-match-only — fuzzy / phonetic / transliteration / 50%-rule  ║
║    / SSI / address proximity are explicitly deferred.                ║
║                                                                      ║
║    Separately, ThifurJ.pretrade_structuring.py has _gate_ofac which  ║
║    screens INSTRUMENTS (ISINs) against MANDATE_LIMITS with hard-stop ║
║    semantics (no resumable halt). The two roles enforce OFAC at      ║
║    distinct axes and are complementary, not redundant — do not       ║
║    consolidate them.                                                 ║
║                                                                      ║
║  OTHER COMPLIANCE TASKS:                                             ║
║    Pre-trade policy checks, IPS eligibility, MiFID II algorithm      ║
║    inventory, approval lineage routing, and surveillance hooks are   ║
║    declared stubs in this file and raise NotImplementedError. Phase  ║
║    4.5 will land them via a focused per-task prompt.                 ║
║                                                                      ║
║  REGULATORY ADDRESS:                                                 ║
║    OFAC 31 CFR 501–598 — SDN screening (counterparty axis)           ║
║    EU GDPR Art. 17 — data retention conflict (see known_conflicts)   ║
║    SR 11-7 Tier 1 — independent validation declared                  ║
║    EU AI Act — high-risk, conformity assessment required             ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from aureon.agents.base import Intent, Advisory, Tasking, Result
from aureon.agents.jtac._base import JTACConcreteBase
from aureon.agents.payloads import (
    ApprovedPath,
    JTACPathSelection,
    ApprovalGateContext,
    ConflictResolution,
    CounterpartyScreeningRequest,
    PreTradePolicyCheckRequest,
    PreTradePolicyCheckResult,
    IPSEligibilityResult,
    AlgoInventoryCheckRequest,
    AlgoInventoryCheckResult,
    ApprovalLineageRequirement,
)

AGENT_COMP_VERSION = "1.0"
ROLE_ID            = "AUR-J-COMP-001"

# ── EU jurisdiction set (ISO 3166-1 alpha-2) ──────────────────────────────────
# Used by OFAC_VS_GDPR_DATA_RETENTION conflict applicability. Kept as a module
# constant for visibility; a richer jurisdiction service is post-Phase 6.
_EU_JURISDICTIONS = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})

# ── Fixture doctrine paths ────────────────────────────────────────────────────
_THIS_DIR   = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT  = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
_DOCTRINE   = os.path.join(_REPO_ROOT, "aureon", "doctrine")
_SDN_FIXTURE           = os.path.join(_DOCTRINE, "sdn_fixture.json")
_MANDATE_FIXTURE       = os.path.join(_DOCTRINE, "mandate_fixture.json")
_IPS_FIXTURE           = os.path.join(_DOCTRINE, "ips_fixture.json")
_ALGO_INVENTORY        = os.path.join(_DOCTRINE, "algo_inventory_fixture.json")
_APPROVAL_LINEAGE_RULES = os.path.join(_DOCTRINE, "approval_lineage_rules.json")


class Compliance(JTACConcreteBase):
    """AUR-J-COMP-001 — Compliance Monitoring.

    Phase 4 implements ONE task end-to-end: OFAC counterparty screening.
    All other Compliance tasks are declared stubs raising NotImplementedError;
    they land in Phase 4.5.
    """

    role_id   = ROLE_ID
    role_name = "Compliance Monitoring"

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        # Named log key so it can be added to the persistence snapshot.
        self._compliance_log_key = "c2_j_compliance_log"
        # Load approved paths once at instantiation. Uses the doctrine-seam
        # loader — future DB backend overrides source_path.
        self.load_approved_paths(role_id=self.role_id)
        # SDN fixture is lazy-loaded on the first screen_ofac call.
        self._sdn_loaded = False
        self._sdn_primary_names: set[str] = set()
        self._sdn_alias_names: set[str] = set()
        self._sdn_entries_by_name: dict[str, dict] = {}
        print(
            f"[COMPLIANCE] Initialized — v{AGENT_COMP_VERSION} | "
            f"Role: {self.role_id} | Paths loaded: "
            f"{list(self._approved_paths.keys())}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # SDN FIXTURE LOADING
    # ─────────────────────────────────────────────────────────────────────────

    def _load_sdn_fixture(self, source_path: Optional[str] = None) -> None:
        """Lazy-load the SDN fixture. Populates a case-folded primary-name set
        and alias-name set for O(1) exact-match checks. Keeping primary and
        alias sets separate preserves sdn_id attribution on match."""
        if self._sdn_loaded:
            return
        path = source_path or _SDN_FIXTURE
        with open(path, "r") as fh:
            raw = json.load(fh)
        for entry in raw.get("sdn_entries", []):
            primary = entry["primary_name"].strip().upper()
            self._sdn_primary_names.add(primary)
            self._sdn_entries_by_name[primary] = entry
            for alias in entry.get("aliases", []):
                key = alias.strip().upper()
                self._sdn_alias_names.add(key)
                self._sdn_entries_by_name[key] = entry
        self._sdn_loaded = True

    # ─────────────────────────────────────────────────────────────────────────
    # PRIMARY TASK — OFAC COUNTERPARTY SCREENING
    # ─────────────────────────────────────────────────────────────────────────

    def screen_ofac(self,
                    request: CounterpartyScreeningRequest
                    ) -> JTACPathSelection:
        """Phase 4 primary task.

        Exact-match, case-insensitive comparison of request.counterparty_name
        against both primary names and aliases in the fixture SDN list.

        Returns a JTACPathSelection:
          - no match → OFAC_CLEAR_NO_MATCH (requires_approval=False)
          - exact match, non-EU → OFAC_EXACT_MATCH_HALT (requires_approval=True)
          - exact match, EU jurisdiction → OFAC_EXACT_MATCH_HALT with
            requires_authority_resolution=True and conflict_id =
            OFAC_VS_GDPR_DATA_RETENTION

        The caller (C2) inspects the selection to decide whether to continue
        the lifecycle, pause for single-authority approval, or pause for
        dual-authority conflict resolution.
        """
        self._load_sdn_fixture()
        candidate = request.counterparty_name.strip().upper()
        hit = (candidate in self._sdn_primary_names
               or candidate in self._sdn_alias_names)

        # Regulatory context for conflict detection.
        # For the OFAC_VS_GDPR_DATA_RETENTION conflict the triggering
        # jurisdiction is the COUNTERPARTY's EU membership — OFAC (US) is
        # the source regime, EU is the target regime where the conflict
        # actually arises. Only populate the EU flag when the counterparty
        # is an EU resident; otherwise leave the context empty so the
        # applicability check at the base does not treat a US counterparty
        # as triggering a GDPR conflict.
        jurisdiction = (request.counterparty_jurisdiction or "").strip().upper()
        reg_ctx: dict = {}
        if jurisdiction in _EU_JURISDICTIONS:
            reg_ctx["jurisdiction"] = "EU"

        if not hit:
            path = self.select_path_by_id("OFAC_CLEAR_NO_MATCH")
            selection = self.build_path_selection(
                task_id=request.task_id,
                path=path,
                rationale=(
                    f"Counterparty '{request.counterparty_name}' not present "
                    f"in fixture SDN — clear, no match"
                ),
                regulatory_context=reg_ctx,
            )
            self._log_screening_result(
                task_id=request.task_id,
                counterparty_name=request.counterparty_name,
                counterparty_jurisdiction=jurisdiction,
                selected_path_id=selection.selected_path_id,
                hit=False,
                sdn_id=None,
            )
            return selection

        # Exact match
        matched_entry = self._sdn_entries_by_name.get(candidate, {})
        path = self.select_path_by_id("OFAC_EXACT_MATCH_HALT")
        selection = self.build_path_selection(
            task_id=request.task_id,
            path=path,
            rationale=(
                f"Counterparty '{request.counterparty_name}' exact-matches "
                f"SDN entry {matched_entry.get('sdn_id', '?')} "
                f"({matched_entry.get('primary_name', '?')})"
            ),
            regulatory_context=reg_ctx,
        )
        self._log_screening_result(
            task_id=request.task_id,
            counterparty_name=request.counterparty_name,
            counterparty_jurisdiction=jurisdiction,
            selected_path_id=selection.selected_path_id,
            hit=True,
            sdn_id=matched_entry.get("sdn_id"),
        )
        return selection

    # ─────────────────────────────────────────────────────────────────────────
    # FIXTURE LOADING
    # ─────────────────────────────────────────────────────────────────────────

    def _load_json_fixture(self, path: str) -> dict:
        """Load a doctrine JSON fixture. Raises FileNotFoundError if missing —
        a missing fixture is a structural error, not a silent fallback."""
        with open(path, "r") as fh:
            return json.load(fh)

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 1 — PRE-TRADE POLICY CHECKS
    # ─────────────────────────────────────────────────────────────────────────

    def check_pretrade_policy(self,
                              request: PreTradePolicyCheckRequest
                              ) -> PreTradePolicyCheckResult:
        """Apply mandate + IPS constraints to the trade intent.

        Status semantics:
          - "BLOCK" → hard violation (prohibited asset class, prohibited
            counterparty type, prohibited jurisdiction). Terminal halt.
          - "HOLD"  → soft approach to a mandate threshold (position size /
            sector concentration) OR IPS ineligibility. Halt-and-pend
            single-authority.
          - "PASS"  → all checks clear. Lifecycle continues.

        Side effect: on HOLD/BLOCK, a JTACPathSelection is built via
        select_path_by_id + build_path_selection and cached on
        self._pending_policy_selections[task_id] so C2 can retrieve it
        for the halt-and-pend persistence without re-selecting the path.
        """
        mandate = self._load_json_fixture(_MANDATE_FIXTURE)
        intent = dict(request.intent_summary or {})
        asset_class = str(intent.get("asset_class") or "").strip().lower()
        notional    = float(intent.get("notional") or 0.0)
        instrument  = str(intent.get("instrument") or "")
        counterparty = str(intent.get("counterparty") or "")
        counterparty_type = str(intent.get("counterparty_type") or "").strip().lower()
        jurisdiction = str(intent.get("jurisdiction") or "").strip().upper()
        sector = str(intent.get("sector") or "").strip().lower()

        # Size/concentration estimates from state
        with self._lock:
            portfolio_value = float(self._state.get("portfolio_value", 0) or 0) or 1.0
            class_totals = dict(self._state.get("class_totals") or {})
        position_pct = (notional / portfolio_value) * 100.0 if portfolio_value else 0.0
        sector_existing = float(class_totals.get(sector, 0.0)) if sector else 0.0
        sector_pct = ((sector_existing + notional) / portfolio_value) * 100.0 if sector else 0.0

        checks: list = []
        failures: list = []

        # ── BLOCK checks (hard violations) ────────────────────────────
        checks.append("prohibited_asset_classes")
        if asset_class and asset_class in {a.lower() for a in mandate.get("prohibited_asset_classes", [])}:
            failures.append({
                "check_name": "prohibited_asset_classes",
                "reason": f"asset_class '{asset_class}' is on the mandate's prohibited list",
                "severity": "BLOCK",
            })
        checks.append("prohibited_counterparty_types")
        if counterparty_type and counterparty_type in {c.lower() for c in mandate.get("prohibited_counterparty_types", [])}:
            failures.append({
                "check_name": "prohibited_counterparty_types",
                "reason": f"counterparty_type '{counterparty_type}' is prohibited",
                "severity": "BLOCK",
            })
        checks.append("permitted_jurisdictions")
        permitted = {j.upper() for j in mandate.get("permitted_jurisdictions", [])}
        if jurisdiction and permitted and jurisdiction not in permitted:
            failures.append({
                "check_name": "permitted_jurisdictions",
                "reason": f"jurisdiction '{jurisdiction}' not in mandate-permitted set",
                "severity": "BLOCK",
            })

        # ── HOLD checks (threshold approach) ──────────────────────────
        checks.append("max_position_size_pct")
        max_pos = float(mandate.get("max_position_size_pct", 100.0))
        hold_pos = float(mandate.get("hold_thresholds", {}).get("position_size_pct_hold_at", max_pos))
        if position_pct >= max_pos:
            failures.append({
                "check_name": "max_position_size_pct",
                "reason": f"position_size {position_pct:.2f}% >= hard cap {max_pos}%",
                "severity": "BLOCK",
            })
        elif position_pct >= hold_pos:
            failures.append({
                "check_name": "max_position_size_pct",
                "reason": f"position_size {position_pct:.2f}% >= HOLD threshold {hold_pos}%",
                "severity": "HOLD",
            })

        checks.append("max_sector_concentration_pct")
        max_sec = float(mandate.get("max_sector_concentration_pct", 100.0))
        hold_sec = float(mandate.get("hold_thresholds", {}).get("sector_concentration_pct_hold_at", max_sec))
        if sector and sector_pct >= max_sec:
            failures.append({
                "check_name": "max_sector_concentration_pct",
                "reason": f"sector_{sector} concentration {sector_pct:.2f}% >= hard cap {max_sec}%",
                "severity": "BLOCK",
            })
        elif sector and sector_pct >= hold_sec:
            failures.append({
                "check_name": "max_sector_concentration_pct",
                "reason": f"sector_{sector} concentration {sector_pct:.2f}% >= HOLD threshold {hold_sec}%",
                "severity": "HOLD",
            })

        # ── IPS Eligibility (Task 2 — invoked internally) ─────────────
        ips_result = self.validate_ips_eligibility(
            intent_summary=intent,
            ips_version=request.ips_version,
            task_id=request.task_id,
        )
        checks.extend(ips_result.checks_performed)
        if ips_result.status == "INELIGIBLE":
            for item in ips_result.ineligibilities:
                failures.append({
                    "check_name": item.get("check_name", "ips_eligibility"),
                    "reason":     item.get("reason", "IPS ineligibility"),
                    "severity":   "HOLD",
                    "ips_context": True,
                })

        # ── Resolve aggregate status ─────────────────────────────────
        has_block = any(f["severity"] == "BLOCK" for f in failures)
        has_hold  = any(f["severity"] == "HOLD" for f in failures)
        if has_block:
            status, path_id = "BLOCK", "PRETRADE_POLICY_BLOCK"
        elif has_hold:
            status, path_id = "HOLD", "PRETRADE_POLICY_HOLD"
        else:
            status, path_id = "PASS", "PRETRADE_POLICY_PASS"

        # Build and cache path selection for C2 retrieval
        path = self.select_path_by_id(path_id)
        selection = self.build_path_selection(
            task_id=request.task_id,
            path=path,
            rationale=f"Pre-trade policy {status}: {len(failures)} failure(s)",
        )
        self._pending_policy_selections = getattr(self, "_pending_policy_selections", {})
        self._pending_policy_selections[request.task_id] = selection

        result = PreTradePolicyCheckResult(
            task_id=request.task_id,
            status=status,
            policy_checks_performed=checks,
            failures=failures,
            ips_eligibility=ips_result.to_dict(),
            pending_approval_for=list(path.approval_predicates),
            selected_path_id=path_id,
            mandate_version=mandate.get("mandate_version"),
            ips_version=ips_result.ips_version,
        )

        self._log_policy_result(result)
        return result

    def get_pending_policy_selection(self, task_id: str) -> Optional[JTACPathSelection]:
        """Retrieve the cached JTACPathSelection built during the last
        check_pretrade_policy call for task_id. Used by C2 halt-and-pend."""
        cache = getattr(self, "_pending_policy_selections", {}) or {}
        return cache.get(task_id)

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 2 — IPS ELIGIBILITY VALIDATION
    # ─────────────────────────────────────────────────────────────────────────

    def validate_ips_eligibility(self,
                                 *,
                                 intent_summary: dict,
                                 ips_version: str,
                                 task_id: str,
                                 ) -> IPSEligibilityResult:
        """Validate a trade intent against the IPS fixture rules.

        Invoked internally by check_pretrade_policy. Does NOT write a
        compliance-log entry directly — the caller writes a consolidated
        entry covering all pre-trade policy checks.
        """
        ips = self._load_json_fixture(_IPS_FIXTURE)
        intent = dict(intent_summary or {})
        asset_class = str(intent.get("asset_class") or "").strip().lower()
        duration    = intent.get("duration_years")
        credit      = str(intent.get("credit_rating") or "").strip().upper()
        currency    = str(intent.get("currency") or "").strip().upper()
        issuer_pct  = intent.get("issuer_concentration_pct")
        sector      = str(intent.get("sector") or "").strip().lower()

        checks: list = []
        ineligibilities: list = []

        checks.append("permitted_asset_classes")
        permitted_classes = {a.lower() for a in ips.get("permitted_asset_classes", [])}
        if asset_class and permitted_classes and asset_class not in permitted_classes:
            ineligibilities.append({
                "check_name": "permitted_asset_classes",
                "reason": f"asset_class '{asset_class}' not in IPS-permitted set",
            })

        checks.append("duration_bounds")
        bounds = ips.get("duration_bounds", {})
        min_y, max_y = bounds.get("min_years"), bounds.get("max_years")
        if duration is not None and min_y is not None and max_y is not None:
            try:
                d = float(duration)
                if d < float(min_y) or d > float(max_y):
                    ineligibilities.append({
                        "check_name": "duration_bounds",
                        "reason": f"duration {d}y outside [{min_y},{max_y}]",
                    })
            except (TypeError, ValueError):
                pass

        checks.append("credit_rating_floor")
        hierarchy = ips.get("credit_rating_hierarchy", [])
        floor = ips.get("credit_rating_floor", "")
        if credit and floor and hierarchy:
            try:
                floor_idx = hierarchy.index(floor)
                credit_idx = hierarchy.index(credit)
                if credit_idx > floor_idx:
                    ineligibilities.append({
                        "check_name": "credit_rating_floor",
                        "reason": f"credit_rating {credit} below floor {floor}",
                    })
            except ValueError:
                ineligibilities.append({
                    "check_name": "credit_rating_floor",
                    "reason": f"credit_rating {credit} not in hierarchy",
                })

        checks.append("permitted_currencies")
        permitted_ccy = {c.upper() for c in ips.get("permitted_currencies", [])}
        if currency and permitted_ccy and currency not in permitted_ccy:
            ineligibilities.append({
                "check_name": "permitted_currencies",
                "reason": f"currency '{currency}' not in IPS-permitted set",
            })

        checks.append("max_single_issuer_concentration_pct")
        max_iss = float(ips.get("max_single_issuer_concentration_pct", 100.0))
        if issuer_pct is not None:
            try:
                if float(issuer_pct) > max_iss:
                    ineligibilities.append({
                        "check_name": "max_single_issuer_concentration_pct",
                        "reason": f"issuer concentration {issuer_pct}% > IPS cap {max_iss}%",
                    })
            except (TypeError, ValueError):
                pass

        checks.append("esg_excluded_sectors")
        excluded = {s.lower() for s in ips.get("esg_constraints", {}).get("excluded_sectors", [])}
        if sector and sector in excluded:
            ineligibilities.append({
                "check_name": "esg_excluded_sectors",
                "reason": f"sector '{sector}' is on IPS ESG exclusion list",
            })

        status = "ELIGIBLE" if not ineligibilities else "INELIGIBLE"
        return IPSEligibilityResult(
            task_id=task_id,
            status=status,
            checks_performed=checks,
            ineligibilities=ineligibilities,
            ips_version=ips.get("ips_version", ips_version or ""),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 3 — MiFID II ALGORITHMIC TRADING INVENTORY
    # ─────────────────────────────────────────────────────────────────────────

    def check_algo_inventory(self,
                             request: AlgoInventoryCheckRequest
                             ) -> AlgoInventoryCheckResult:
        """Session-level check that every active algorithm is registered
        per MiFID II RTS 6 AND its last_validated_at is within its own
        validation_frequency_days window. Runs on operator-triggered
        algorithm activation, NOT per trade.

        On MISSING_REGISTRATION: builds path ALGO_INVENTORY_MISSING_HALT
        and caches the selection for C2 to retrieve for halt-and-pend.
        """
        inventory = self._load_json_fixture(_ALGO_INVENTORY)
        registered_map = {
            entry["role_id"]: entry
            for entry in inventory.get("registered_algorithms", [])
        }
        now = datetime.now(timezone.utc)

        registered_out: list = []
        missing: list = []

        for algo_id in request.active_algorithms or []:
            entry = registered_map.get(algo_id)
            if not entry:
                missing.append(algo_id)
                continue
            # Check validation freshness
            try:
                last_validated = datetime.fromisoformat(
                    entry["last_validated_at"].replace("Z", "+00:00")
                )
                freq_days = int(entry.get("validation_frequency_days", 180))
                age_days = (now - last_validated).days
                if age_days > freq_days:
                    missing.append(algo_id)
                    continue
            except (KeyError, ValueError, TypeError):
                missing.append(algo_id)
                continue
            registered_out.append({
                "role_id": algo_id,
                "registration_version": entry.get("registration_version"),
                "last_validated_at": entry.get("last_validated_at"),
            })

        status = "REGISTERED" if not missing else "MISSING_REGISTRATION"
        path_id = "ALGO_INVENTORY_REGISTERED" if not missing else "ALGO_INVENTORY_MISSING_HALT"
        path = self.select_path_by_id(path_id)
        selection = self.build_path_selection(
            task_id=request.task_id,
            path=path,
            rationale=(
                f"Algo inventory {status}: "
                f"{len(registered_out)} registered, {len(missing)} missing"
            ),
        )
        self._pending_algo_selections = getattr(self, "_pending_algo_selections", {})
        self._pending_algo_selections[request.task_id] = selection

        result = AlgoInventoryCheckResult(
            task_id=request.task_id,
            status=status,
            registered_algorithms=registered_out,
            missing_registrations=missing,
            pending_approval_for=list(path.approval_predicates),
            selected_path_id=path_id,
        )

        self._log_algo_inventory_result(result, inventory_version=inventory.get("inventory_version", ""))
        return result

    def get_pending_algo_selection(self, task_id: str) -> Optional[JTACPathSelection]:
        """Retrieve the cached selection from the last check_algo_inventory
        call for task_id. Used by the /api/c2/algo-inventory-check endpoint
        to persist a paused_lifecycle on MISSING_REGISTRATION."""
        cache = getattr(self, "_pending_algo_selections", {}) or {}
        return cache.get(task_id)

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 4 — APPROVAL LINEAGE ROUTING
    # ─────────────────────────────────────────────────────────────────────────

    def determine_approval_lineage(self,
                                   *,
                                   pause_reason: str,
                                   task_id: str,
                                   source_path: Optional[str] = None
                                   ) -> ApprovalLineageRequirement:
        """Look up the required human authorities for a given pause_reason.

        Replaces the hardcoded authority lists that Phase 4's resume logic
        carried. Data source: approval_lineage_rules.json (seam: source_path
        overridable for future DB-backed rule store).

        Unknown pause_reason falls back to ["compliance"] with no SLA —
        ensures any future halt reason surfaces a human authority without
        silently bypassing the gate.
        """
        path = source_path or _APPROVAL_LINEAGE_RULES
        try:
            rules = self._load_json_fixture(path)
        except FileNotFoundError:
            rules = {"rules": []}
        match = next(
            (r for r in rules.get("rules", []) if r.get("pause_reason") == pause_reason),
            None,
        )
        if match is None:
            return ApprovalLineageRequirement(
                task_id=task_id,
                pause_reason=pause_reason,
                required_authorities=["compliance"],
                sla_seconds=None,
                fallback_authorities=[],
            )
        return ApprovalLineageRequirement(
            task_id=task_id,
            pause_reason=pause_reason,
            required_authorities=list(match.get("required_authorities", [])),
            sla_seconds=match.get("sla_seconds"),
            fallback_authorities=list(match.get("fallback_authorities", [])),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # POLICY / INVENTORY LOG HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _log_policy_result(self, result: PreTradePolicyCheckResult) -> None:
        """Write a consolidated pre-trade policy entry to c2_j_compliance_log."""
        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "ts":                        ts,
            "task_id":                   result.task_id,
            "role_id":                   self.role_id,
            "event_type":                "PRETRADE_POLICY",
            "status":                    result.status,
            "policy_checks_performed":   list(result.policy_checks_performed),
            "failures":                  list(result.failures),
            "selected_path_id":          result.selected_path_id,
            "mandate_version":           result.mandate_version,
            "ips_version":               result.ips_version,
            "doctrine_version":          self._state.get("doctrine_version", "unknown"),
        }
        with self._lock:
            log = self._state.setdefault(self._compliance_log_key, [])
            log.insert(0, entry)
            if len(log) > 500:
                self._state[self._compliance_log_key] = log[:500]

    def _log_algo_inventory_result(self, result: AlgoInventoryCheckResult,
                                    inventory_version: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "ts":                    ts,
            "task_id":               result.task_id,
            "role_id":               self.role_id,
            "event_type":            "ALGO_INVENTORY_CHECK",
            "status":                result.status,
            "registered_count":      len(result.registered_algorithms),
            "missing_registrations": list(result.missing_registrations),
            "selected_path_id":      result.selected_path_id,
            "inventory_version":     inventory_version,
            "doctrine_version":      self._state.get("doctrine_version", "unknown"),
        }
        with self._lock:
            log = self._state.setdefault(self._compliance_log_key, [])
            log.insert(0, entry)
            if len(log) > 500:
                self._state[self._compliance_log_key] = log[:500]

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL LOGGING
    # ─────────────────────────────────────────────────────────────────────────

    def _log_screening_result(self,
                               task_id: str,
                               counterparty_name: str,
                               counterparty_jurisdiction: str,
                               selected_path_id: str,
                               hit: bool,
                               sdn_id: Optional[str]) -> None:
        """Write the screening outcome to c2_j_compliance_log."""
        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "ts":                        ts,
            "task_id":                   task_id,
            "role_id":                   self.role_id,
            "event_type":                "OFAC_SCREENING",
            "counterparty_name":         counterparty_name,
            "counterparty_jurisdiction": counterparty_jurisdiction,
            "hit":                       hit,
            "sdn_id":                    sdn_id,
            "selected_path_id":          selected_path_id,
            "doctrine_version":          self._state.get("doctrine_version", "unknown"),
        }
        with self._lock:
            log = self._state.setdefault(self._compliance_log_key, [])
            log.insert(0, entry)
            if len(log) > 500:
                self._state[self._compliance_log_key] = log[:500]

    # ─────────────────────────────────────────────────────────────────────────
    # AGENT ABC SURFACE
    # ─────────────────────────────────────────────────────────────────────────

    def advise(self, intent: Intent) -> Advisory:
        return Advisory(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            summary=(
                f"Compliance screening advisory for "
                f"{intent.payload.get('counterparty_name', '?')}"
            ),
            recommendation={"screening": "pending"},
            requires_approval=True,
        )

    def execute(self, tasking: Tasking) -> Result:
        return Result(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            outcome="DELEGATED",
            dsor_record_id=tasking.c2_tasking_id,
        )

    def get_status(self) -> dict:
        return {
            "agent_id":       self.role_id,
            "role_name":      self.role_name,
            "version":        AGENT_COMP_VERSION,
            "role_id":        self.role_id,
            "status":         "ACTIVE",
            "phase":          "Phase 4 — OFAC Counterparty Screening",
            "approved_paths": list(self._approved_paths.keys()),
            "sr_11_7_tier":   "Tier 1",
            "scope_note":     (
                "Phase 4 implements OFAC counterparty screening only. "
                "Other Compliance tasks are Phase 4.5 stubs."
            ),
            "guardrails":     [
                "Approved paths only",
                "No release without approval lineage",
                "Eligibility before routing",
                "Doctrine over regulation conflict",
                "No self-initiation",
            ],
        }


# ── Path callables ────────────────────────────────────────────────────────────
# Referenced by callable_ref in aureon/doctrine/jtac_paths/AUR-J-COMP-001.json.
# Phase 4 is code-as-path: these callables are the authoritative action for
# each path when execution proceeds past the approval gate. For Phase 4 they
# are minimal — the real side-effects (telemetry, lifecycle continuation) are
# owned by C2 post-resume, not by the path callable itself.

def _path_clear_no_match(task_id: str, **_ignored) -> dict:
    """Called when OFAC_CLEAR_NO_MATCH is the selected path. The lifecycle
    proceeds to TradeSupport; this callable records the clear outcome."""
    return {
        "path_id":   "OFAC_CLEAR_NO_MATCH",
        "task_id":   task_id,
        "outcome":   "CLEAR",
        "continue":  True,
    }


def _path_exact_match_halt(task_id: str, **_ignored) -> dict:
    """Called when OFAC_EXACT_MATCH_HALT is the selected path. The lifecycle
    halts; this callable records the halt decision. Actual halt-and-pend
    lifecycle persistence is owned by C2."""
    return {
        "path_id":   "OFAC_EXACT_MATCH_HALT",
        "task_id":   task_id,
        "outcome":   "HALT",
        "continue":  False,
    }


def _path_pretrade_policy_pass(task_id: str, **_ignored) -> dict:
    return {"path_id": "PRETRADE_POLICY_PASS", "task_id": task_id,
            "outcome": "PASS", "continue": True}


def _path_pretrade_policy_hold(task_id: str, **_ignored) -> dict:
    return {"path_id": "PRETRADE_POLICY_HOLD", "task_id": task_id,
            "outcome": "HOLD", "continue": False}


def _path_pretrade_policy_block(task_id: str, **_ignored) -> dict:
    return {"path_id": "PRETRADE_POLICY_BLOCK", "task_id": task_id,
            "outcome": "BLOCK", "continue": False}


def _path_algo_inventory_registered(task_id: str, **_ignored) -> dict:
    return {"path_id": "ALGO_INVENTORY_REGISTERED", "task_id": task_id,
            "outcome": "REGISTERED", "continue": True}


def _path_algo_inventory_missing_halt(task_id: str, **_ignored) -> dict:
    return {"path_id": "ALGO_INVENTORY_MISSING_HALT", "task_id": task_id,
            "outcome": "HALT", "continue": False}
