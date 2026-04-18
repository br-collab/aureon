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

# ── SDN fixture path ──────────────────────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
_SDN_FIXTURE = os.path.join(_REPO_ROOT, "aureon", "doctrine", "sdn_fixture.json")


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
    # OTHER COMPLIANCE TASKS — Phase 4.5 stubs
    # ─────────────────────────────────────────────────────────────────────────

    def check_pretrade_policy(self, *args, **kwargs):
        """Phase 4.5 — pre-trade policy gate."""
        raise NotImplementedError(
            f"[{self.role_id}] check_pretrade_policy is a Phase 4.5 stub"
        )

    def validate_ips_eligibility(self, *args, **kwargs):
        """Phase 4.5 — Investment Policy Statement eligibility."""
        raise NotImplementedError(
            f"[{self.role_id}] validate_ips_eligibility is a Phase 4.5 stub"
        )

    def track_mifid_algo_inventory(self, *args, **kwargs):
        """Phase 4.5 — MiFID II RTS 6 algorithm inventory."""
        raise NotImplementedError(
            f"[{self.role_id}] track_mifid_algo_inventory is a Phase 4.5 stub"
        )

    def route_approval_lineage(self, *args, **kwargs):
        """Phase 4.5 — authority lineage routing."""
        raise NotImplementedError(
            f"[{self.role_id}] route_approval_lineage is a Phase 4.5 stub"
        )

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
