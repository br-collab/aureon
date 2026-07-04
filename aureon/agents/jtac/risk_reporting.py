"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/jtac/risk_reporting.py                               ║
║  Risk Reporting — AUR-J-RISK-001                                    ║
║                                                                      ║
║  MANDATE (WS-2.3 scope):                                            ║
║    Periodic PORTFOLIO-LEVEL risk aggregation. Compute every metric  ║
║    in risk_thresholds_fixture.json against live portfolio state,    ║
║    assemble a per-metric risk report (BCBS 239 aggregation), and    ║
║    select the disposition path matching the WORST rung reached.     ║
║                                                                      ║
║  DISPOSITION PATHS (worst-rung-wins):                               ║
║    RISK_WITHIN_LIMITS     all metrics below warn → continue          ║
║    RISK_WARN_THRESHOLD    ≥1 in warn band → CRO acknowledgment       ║
║    RISK_LIMIT_BREACH      ≥1 at/over breach → halt, dual authority   ║
║    RISK_DATA_INCOMPLETE   metric uncomputable → halt, gap flagged    ║
║                                                                      ║
║  BOUNDARY WITH PRE-TRADE RISK GATING:                              ║
║    pretrade_structuring.py gates a SINGLE TRADE at entry (blocking).║
║    This role reports STANDING portfolio risk (periodic, aggregating,║
║    escalating). Complementary, not redundant — neither consults the ║
║    other; C2 sequences them (Axiom 3).                              ║
║                                                                      ║
║  DOCTRINAL INVARIANT (mirrors C2 Immutable Stop 4):                ║
║    A risk report with a missing metric is NEVER presented as        ║
║    within-limits. Gaps are flagged explicitly, never silently       ║
║    filled. RISK_DATA_INCOMPLETE outranks RISK_WITHIN_LIMITS.        ║
║                                                                      ║
║  REGULATORY ADDRESS:                                               ║
║    BCBS 239 P3 accuracy / P5 timeliness — automated risk aggregation║
║    SR 11-7 — risk monitoring; Tier 1 classification declared        ║
║    DORA — liquidity resilience (cash-buffer metric)                 ║
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

AGENT_RISK_VERSION = "0.1"
ROLE_ID = "AUR-J-RISK-001"

_DOCTRINE = os.path.join(os.path.dirname(__file__), "..", "..", "doctrine")
_RISK_THRESHOLDS = os.path.join(_DOCTRINE, "risk_thresholds_fixture.json")

# Rung ordering — higher index = more restrictive. Path selection takes
# the max across all metrics ("worst rung wins").
#
# Ordering is by ESCALATION STRENGTH, deliberately: a hard BREACH is the
# most restrictive (halt + dual authority) and must DOMINATE a concurrent
# DATA gap. If a metric is in visible breach while another metric is
# uncomputable, the disposition is RISK_LIMIT_BREACH (dual authority) —
# NOT RISK_DATA_INCOMPLETE (single-authority gap ack) — because a known
# breach can never earn a lighter ceremony just because data is also
# missing. The gap is still surfaced: the risk_report lists missing_metrics
# on every path. INCOMPLETE outranks WARN because a gap forces a halt while
# a warn does not. (Corrected 2026-07-04 after the interaction test caught
# the inverse ordering under-escalating a breach-plus-gap.)
_RUNG_WITHIN = 0
_RUNG_WARN = 1
_RUNG_INCOMPLETE = 2
_RUNG_BREACH = 3

_RUNG_TO_PATH = {
    _RUNG_WITHIN:     "RISK_WITHIN_LIMITS",
    _RUNG_WARN:       "RISK_WARN_THRESHOLD",
    _RUNG_INCOMPLETE: "RISK_DATA_INCOMPLETE",
    _RUNG_BREACH:     "RISK_LIMIT_BREACH",
}


class RiskReporting(JTACConcreteBase):
    """AUR-J-RISK-001 — Risk Reporting.

    WS-2.3 (2026-07-04): third Tier 2 role. Distinct provenance from the
    prior two — the risk SIGNALS existed (drawdown, concentration, cash
    floor bands) but only inside per-trade enforcement gates; no agent
    aggregated them into a periodic portfolio-level risk report. This role
    builds that aggregation and its escalation dispositions, referencing
    the existing thresholds consolidated into risk_thresholds_fixture.json.
    """

    role_id   = ROLE_ID
    role_name = "Risk Reporting"

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        self._risk_log_key = "c2_j_risk_log"
        self.load_approved_paths(role_id=self.role_id)
        self._thresholds_loaded = False
        self._metrics: dict = {}
        print(
            f"[RISK-REPORTING] Initialized — v{AGENT_RISK_VERSION} | "
            f"Role: {self.role_id} | Paths loaded: "
            f"{list(self._approved_paths.keys())}"
        )

    def _load_thresholds(self, source_path: Optional[str] = None) -> None:
        if self._thresholds_loaded:
            return
        path = source_path or _RISK_THRESHOLDS
        with open(path, "r") as fh:
            raw = json.load(fh)
        self._metrics = raw.get("metrics", {})
        self._thresholds_loaded = True

    # ─────────────────────────────────────────────────────────────────────────
    # PRIMARY TASK — PORTFOLIO RISK AGGREGATION
    # ─────────────────────────────────────────────────────────────────────────

    def assess_portfolio_risk(self, task_id: str, snapshot: dict):
        """Aggregate standing portfolio risk from a live-state *snapshot* and
        select the worst-rung disposition path.

        snapshot keys (all optional — a missing required metric routes to
        RISK_DATA_INCOMPLETE, never silently treated as clean):
          drawdown_pct                        — current drawdown %
          single_position_concentration_pct   — largest single position %
          sector_concentration_pct            — largest sector %
          liquidity_buffer_pct                — cash / portfolio value %

        Returns (JTACPathSelection, risk_report). The risk_report is always
        emitted regardless of path (BCBS 239 aggregation deliverable).
        """
        self._load_thresholds()
        report_metrics = []
        worst_rung = _RUNG_WITHIN

        for key, cfg in self._metrics.items():
            value = snapshot.get(key)
            if value is None:
                report_metrics.append({
                    "metric": key, "label": cfg.get("label", key),
                    "value": None, "status": "DATA_MISSING",
                })
                worst_rung = max(worst_rung, _RUNG_INCOMPLETE)
                continue
            direction = cfg.get("direction", "above")
            warn = cfg.get("warn_at")
            breach = cfg.get("breach_at")
            status, rung = self._classify(value, warn, breach, direction)
            report_metrics.append({
                "metric": key, "label": cfg.get("label", key),
                "value": value, "warn_at": warn, "breach_at": breach,
                "direction": direction, "status": status,
            })
            worst_rung = max(worst_rung, rung)

        path_id = _RUNG_TO_PATH[worst_rung]
        flagged = [m["metric"] for m in report_metrics
                   if m["status"] not in ("WITHIN", "DATA_MISSING")]
        missing = [m["metric"] for m in report_metrics if m["status"] == "DATA_MISSING"]

        rationale = self._rationale(path_id, flagged, missing)
        path = self.select_path_by_id(path_id)
        selection = self.build_path_selection(
            task_id=task_id, path=path, rationale=rationale, regulatory_context={},
        )

        risk_report = {
            "task_id": task_id,
            "role_id": self.role_id,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
            "disposition": path_id,
            "worst_rung": worst_rung,
            "metrics": report_metrics,
            "flagged_metrics": flagged,
            "missing_metrics": missing,
            "doctrine_version": self._state.get("doctrine_version", "unknown"),
        }

        with self._lock:
            log = self._state.setdefault(self._risk_log_key, [])
            log.insert(0, {
                "ts": risk_report["assessed_at"], "task_id": task_id,
                "role_id": self.role_id, "event_type": "RISK_ASSESSMENT",
                "disposition": path_id, "flagged": flagged, "missing": missing,
                "doctrine_version": risk_report["doctrine_version"],
            })
            if len(log) > 500:
                self._state[self._risk_log_key] = log[:500]

        return selection, risk_report

    @staticmethod
    def _classify(value, warn, breach, direction):
        """Return (status, rung). 'above' metrics breach when value >=
        threshold; 'below' metrics breach when value <= threshold."""
        if direction == "below":
            if breach is not None and value <= breach:
                return "BREACH", _RUNG_BREACH
            if warn is not None and value <= warn:
                return "WARN", _RUNG_WARN
            return "WITHIN", _RUNG_WITHIN
        # default: above
        if breach is not None and value >= breach:
            return "BREACH", _RUNG_BREACH
        if warn is not None and value >= warn:
            return "WARN", _RUNG_WARN
        return "WITHIN", _RUNG_WITHIN

    @staticmethod
    def _rationale(path_id, flagged, missing):
        if path_id == "RISK_DATA_INCOMPLETE":
            return (f"Risk picture incomplete — uncomputable metric(s): "
                    f"{', '.join(missing)}. Not presented as within-limits; "
                    f"gap flagged for acknowledgment (never silently filled).")
        if path_id == "RISK_LIMIT_BREACH":
            return (f"Hard risk limit breached on: {', '.join(flagged)}. "
                    f"Halt-and-pend; dual authority (CRO + Executive) required.")
        if path_id == "RISK_WARN_THRESHOLD":
            return (f"Warn threshold reached on: {', '.join(flagged)}. "
                    f"CRO acknowledgment recorded; not a halt.")
        return "All risk metrics below warn thresholds — portfolio within limits."

    # ─────────────────────────────────────────────────────────────────────────
    # AGENT INTERFACE
    # ─────────────────────────────────────────────────────────────────────────

    def advise(self, intent: Intent) -> Advisory:
        return Advisory(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            summary="Portfolio risk aggregation advisory",
            recommendation={"risk": "pending_assessment"},
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
            "version":        AGENT_RISK_VERSION,
            "role_id":        self.role_id,
            "status":         "ACTIVE",
            "phase":          "WS-2.3 — portfolio risk aggregation & reporting",
            "approved_paths": list(self._approved_paths.keys()),
            "sr_11_7_tier":   "Tier 1",
            "scope_note":     (
                "Third Tier 2 workforce role (AUR-J-PATHSET-RISK-001). "
                "Aggregates drawdown, concentration, sector, and liquidity "
                "metrics against risk_thresholds_fixture.json; worst-rung "
                "disposition. Distinct from per-trade risk gating."
            ),
            "guardrails":     [
                "Approved paths only",
                "No release without approval lineage",
                "Gaps flagged, never silently filled",
                "Doctrine over optimization",
                "No self-initiation",
            ],
        }


# ── Path callables ────────────────────────────────────────────────────────────
# Referenced by callable_ref in aureon/doctrine/jtac_paths/AUR-J-RISK-001.json.

def _path_within_limits(task_id: str, **_ignored) -> dict:
    return {"path_id": "RISK_WITHIN_LIMITS", "task_id": task_id,
            "outcome": "WITHIN_LIMITS", "continue": True}


def _path_warn_threshold(task_id: str, **_ignored) -> dict:
    return {"path_id": "RISK_WARN_THRESHOLD", "task_id": task_id,
            "outcome": "WARN_ACK_REQUIRED", "continue": True}


def _path_limit_breach(task_id: str, **_ignored) -> dict:
    return {"path_id": "RISK_LIMIT_BREACH", "task_id": task_id,
            "outcome": "HALT_PENDING_DUAL_AUTHORITY", "continue": False}


def _path_data_incomplete(task_id: str, **_ignored) -> dict:
    return {"path_id": "RISK_DATA_INCOMPLETE", "task_id": task_id,
            "outcome": "HALT_PENDING_GAP_ACK", "continue": False}
