"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/jtac/aml_kyc.py                                       ║
║  AML/KYC — AUR-J-AML-001                                             ║
║                                                                      ║
║  MANDATE (WS-2.2 scope):                                             ║
║    Counterparty KYC/KYB eligibility verification against the fixture ║
║    KYC registry. Six-path decision ladder, halt-and-pend on every    ║
║    non-clear rung. Emits JTACPathSelection; C2 owns lifecycle        ║
║    continuation, pause, and resume.                                  ║
║                                                                      ║
║  DECISION LADDER (doctrinal order — see AUR-J-PATHSET-AML-001):      ║
║    1. AML_PROHIBITED_BLOCK      terminal, no override                ║
║    2. KYC_MISSING_HALT          completion gate (onboarding)         ║
║    3. KYC_EXPIRED_HALT          single authority (re-verification)   ║
║    4. KYB_UBO_UNRESOLVED_HALT   dual authority (UBO + Compliance)    ║
║    5. AML_HIGH_RISK_ESCALATE    dual authority (EDD + Compliance)    ║
║    6. KYC_ELIGIBLE_CLEAR        continue                             ║
║                                                                      ║
║  BOUNDARY WITH AUR-J-COMP-001:                                       ║
║    Compliance screens counterparties against the SDN list (sanction  ║
║    axis). This role verifies onboarding eligibility (identity /      ║
║    ownership / risk axis). A counterparty must clear BOTH. Neither   ║
║    role consults the other — C2 sequences them (Axiom 3).            ║
║                                                                      ║
║  REGULATORY ADDRESS:                                                 ║
║    31 CFR 1010/1020 (BSA/CIP) — identity verification               ║
║    FinCEN CDD Rule 31 CFR 1010.230 — beneficial ownership (UBO)      ║
║    FATF Rec. 10/12/19 — CDD, PEPs, high-risk jurisdictions           ║
║    EU AI Act — high-risk (access to financial services), conformity  ║
║    assessment required before EU deployment                          ║
║    SR 11-7 Tier 1 — independent validation declared                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from aureon.agents.jtac._base import JTACConcreteBase
from aureon.agents.base import Intent, Advisory, Tasking, Result
from aureon.agents.payloads import CounterpartyScreeningRequest, JTACPathSelection

AGENT_AML_VERSION = "0.1"
ROLE_ID = "AUR-J-AML-001"

_DOCTRINE = os.path.join(os.path.dirname(__file__), "..", "..", "doctrine")
_KYC_REGISTRY = os.path.join(_DOCTRINE, "kyc_registry_fixture.json")


class AmlKyc(JTACConcreteBase):
    """AUR-J-AML-001 — AML/KYC eligibility verification.

    WS-2.2 (2026-07-04): first Tier 2 role built new (no prior code)
    against the operationalization standard established by
    AUR-J-PATHSET-COMP-001 §VII: versioned path inventory
    (jtac_paths/AUR-J-AML-001.json), implemented callables with
    halt-and-pend semantics, fixture rule set (kyc_registry_fixture.json),
    and this class. Fixture is exact-match by name/alias, mirroring the
    Phase 4 SDN convention; fuzzy matching and KYC-utility integration
    are deferred with the same triggers as fuzzy OFAC.
    """

    role_id   = ROLE_ID
    role_name = "AML/KYC"

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        # Named log key — included in the persistence snapshot (WS-0.1
        # convention: lifecycle-relevant logs must survive restarts).
        self._amlkyc_log_key = "c2_j_amlkyc_log"
        self.load_approved_paths(role_id=self.role_id)
        self._registry_loaded = False
        self._entries_by_name: dict[str, dict] = {}
        self._prohibited_jurisdictions: set[str] = set()
        self._high_risk_jurisdictions: set[str] = set()
        print(
            f"[AML-KYC] Initialized — v{AGENT_AML_VERSION} | "
            f"Role: {self.role_id} | Paths loaded: "
            f"{list(self._approved_paths.keys())}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # REGISTRY FIXTURE LOADING
    # ─────────────────────────────────────────────────────────────────────────

    def _load_registry_fixture(self, source_path: Optional[str] = None) -> None:
        """Lazy-load the KYC registry fixture. Case-folded exact-match on
        primary names and aliases, mirroring the SDN loader. *source_path*
        is the doctrine seam for a future KYC-utility integration."""
        if self._registry_loaded:
            return
        path = source_path or _KYC_REGISTRY
        with open(path, "r") as fh:
            raw = json.load(fh)
        for entry in raw.get("kyc_entries", []):
            primary = entry["primary_name"].strip().upper()
            self._entries_by_name[primary] = entry
            for alias in entry.get("aliases", []):
                self._entries_by_name[alias.strip().upper()] = entry
        self._prohibited_jurisdictions = {
            j.strip().upper() for j in raw.get("prohibited_jurisdictions", [])
        }
        self._high_risk_jurisdictions = {
            j.strip().upper() for j in raw.get("high_risk_jurisdictions", [])
        }
        self._registry_loaded = True

    # ─────────────────────────────────────────────────────────────────────────
    # PRIMARY TASK — KYC/KYB ELIGIBILITY VERIFICATION
    # ─────────────────────────────────────────────────────────────────────────

    def verify_counterparty_eligibility(
        self, request: CounterpartyScreeningRequest
    ) -> JTACPathSelection:
        """Run the six-rung decision ladder for one counterparty.

        Reuses CounterpartyScreeningRequest deliberately — same identity
        fields as the sanction axis, no new payload surface. Returns a
        JTACPathSelection; C2 reads requires_approval and
        pending_approval_for to decide continue / halt-and-pend.
        """
        self._load_registry_fixture()
        candidate = request.counterparty_name.strip().upper()
        req_jurisdiction = (request.counterparty_jurisdiction or "").strip().upper()
        entry = self._entries_by_name.get(candidate)

        # Rung 1 — PROHIBITED (terminal). Checked on both the registry
        # rating and the request/registry jurisdiction: a prohibited
        # jurisdiction blocks even when no registry record exists.
        entry_jurisdiction = (entry or {}).get("jurisdiction", "").strip().upper()
        if (
            (entry and entry.get("risk_rating", "").upper() == "PROHIBITED")
            or req_jurisdiction in self._prohibited_jurisdictions
            or entry_jurisdiction in self._prohibited_jurisdictions
        ):
            return self._select(
                request, "AML_PROHIBITED_BLOCK", entry,
                f"Counterparty '{request.counterparty_name}' prohibited — "
                f"rating/jurisdiction on prohibited list. Terminal; no override."
            )

        # Rung 2 — MISSING (completion gate).
        if entry is None:
            return self._select(
                request, "KYC_MISSING_HALT", None,
                f"No KYC registry record for '{request.counterparty_name}' — "
                f"halt pending onboarding completion."
            )

        # Rung 3 — EXPIRED (single authority).
        if self._is_expired(entry.get("expires_at")):
            return self._select(
                request, "KYC_EXPIRED_HALT", entry,
                f"KYC verification for '{request.counterparty_name}' expired "
                f"{entry.get('expires_at')} — halt pending re-verification."
            )

        # Rung 4 — UBO / KYB (dual authority).
        if not entry.get("ubo_resolved", False) or \
                entry.get("kyb_status", "").upper() != "VERIFIED":
            return self._select(
                request, "KYB_UBO_UNRESOLVED_HALT", entry,
                f"Beneficial ownership unresolved or KYB pending for "
                f"'{request.counterparty_name}' — dual-authority resumption."
            )

        # Rung 5 — HIGH RISK / PEP (dual authority, EDD).
        if (
            entry.get("pep_flag", False)
            or entry.get("risk_rating", "").upper() == "HIGH"
            or entry_jurisdiction in self._high_risk_jurisdictions
        ):
            return self._select(
                request, "AML_HIGH_RISK_ESCALATE", entry,
                f"'{request.counterparty_name}' flagged high-risk "
                f"(PEP/rating/jurisdiction) — EDD plus Compliance sign-off "
                f"required before relationship proceeds."
            )

        # Rung 6 — CLEAR.
        return self._select(
            request, "KYC_ELIGIBLE_CLEAR", entry,
            f"'{request.counterparty_name}' verified, current, UBO resolved, "
            f"risk acceptable — eligible."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNALS
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_expired(expires_at: Optional[str]) -> bool:
        """True if *expires_at* (ISO-8601, Z-suffixed) is in the past.
        A missing or unparseable expiry is treated as expired — the
        conservative reading; silent eligibility is never the default."""
        if not expires_at:
            return True
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        return exp <= datetime.now(timezone.utc)

    def _select(self,
                request: CounterpartyScreeningRequest,
                path_id: str,
                entry: Optional[dict],
                rationale: str) -> JTACPathSelection:
        """Select a path by id, build the JTACPathSelection, log the outcome."""
        path = self.select_path_by_id(path_id)
        selection = self.build_path_selection(
            task_id=request.task_id,
            path=path,
            rationale=rationale,
            regulatory_context={},
        )
        with self._lock:
            log = self._state.setdefault(self._amlkyc_log_key, [])
            log.insert(0, {
                "ts":                        datetime.now(timezone.utc).isoformat(),
                "task_id":                   request.task_id,
                "role_id":                   self.role_id,
                "event_type":                "KYC_ELIGIBILITY",
                "counterparty_name":         request.counterparty_name,
                "counterparty_jurisdiction": (request.counterparty_jurisdiction or "").upper(),
                "counterparty_id":           (entry or {}).get("counterparty_id"),
                "selected_path_id":          selection.selected_path_id,
                "doctrine_version":          self._state.get("doctrine_version", "unknown"),
            })
            if len(log) > 500:
                self._state[self._amlkyc_log_key] = log[:500]
        return selection

    # ─────────────────────────────────────────────────────────────────────────
    # AGENT INTERFACE
    # ─────────────────────────────────────────────────────────────────────────

    def advise(self, intent: Intent) -> Advisory:
        return Advisory(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            summary=(
                f"KYC/KYB eligibility advisory for "
                f"{intent.payload.get('counterparty_name', '?')}"
            ),
            recommendation={"eligibility": "pending"},
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
            "version":        AGENT_AML_VERSION,
            "role_id":        self.role_id,
            "status":         "ACTIVE",
            "phase":          "WS-2.2 — KYC/KYB eligibility verification",
            "approved_paths": list(self._approved_paths.keys()),
            "sr_11_7_tier":   "Tier 1",
            "scope_note":     (
                "Second Tier 2 workforce role (AUR-J-PATHSET-AML-001). "
                "Live: six-rung eligibility ladder against fixture KYC "
                "registry. Deferred: fuzzy matching, KYC-utility "
                "integration, transaction-pattern monitoring."
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
# Referenced by callable_ref in aureon/doctrine/jtac_paths/AUR-J-AML-001.json.
# Minimal by design — side-effects (telemetry, lifecycle continuation) are
# owned by C2 post-resume, matching the AUR-J-COMP-001 convention.

def _path_eligible_clear(task_id: str, **_ignored) -> dict:
    return {"path_id": "KYC_ELIGIBLE_CLEAR", "task_id": task_id,
            "outcome": "CLEAR", "continue": True}


def _path_missing_halt(task_id: str, **_ignored) -> dict:
    return {"path_id": "KYC_MISSING_HALT", "task_id": task_id,
            "outcome": "HALT_PENDING_ONBOARDING", "continue": False}


def _path_expired_halt(task_id: str, **_ignored) -> dict:
    return {"path_id": "KYC_EXPIRED_HALT", "task_id": task_id,
            "outcome": "HALT_PENDING_REVERIFICATION", "continue": False}


def _path_ubo_unresolved_halt(task_id: str, **_ignored) -> dict:
    return {"path_id": "KYB_UBO_UNRESOLVED_HALT", "task_id": task_id,
            "outcome": "HALT_PENDING_UBO_RESOLUTION", "continue": False}


def _path_high_risk_escalate(task_id: str, **_ignored) -> dict:
    return {"path_id": "AML_HIGH_RISK_ESCALATE", "task_id": task_id,
            "outcome": "HALT_PENDING_EDD", "continue": False}


def _path_prohibited_block(task_id: str, **_ignored) -> dict:
    return {"path_id": "AML_PROHIBITED_BLOCK", "task_id": task_id,
            "outcome": "BLOCKED_TERMINAL", "continue": False}
