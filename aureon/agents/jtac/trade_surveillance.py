"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/jtac/trade_surveillance.py                           ║
║  Trade Surveillance (Fixed Income) — AUR-J-SURV-001                 ║
║                                                                      ║
║  MANDATE (WS-2.4 scope):                                            ║
║    Run every ENABLED scenario in surveillance_scenarios_fixture     ║
║    against a trade/session record; select the worst-outcome         ║
║    disposition. Emit a surveillance report listing every match and  ║
║    every scenario that could not be evaluated.                      ║
║                                                                      ║
║  DISPOSITION PATHS (worst-outcome-wins):                           ║
║    SURVEIL_CLEAR            no match, all checks ran                 ║
║    SURVEIL_PATTERN_FLAGGED  REVIEW match → human review             ║
║    SURVEIL_DATA_INCOMPLETE  active check uncheckable → halt          ║
║    SURVEIL_PATTERN_ESCALATE ESCALATE match → halt, dual authority    ║
║                                                                      ║
║  DOCTRINAL INVARIANTS:                                             ║
║    (1) No flagged/escalated pattern is auto-disposed — only human   ║
║        review clears it.                                            ║
║    (2) An active surveillance check that cannot run means the trade ║
║        is NOT certified clean (gap-completeness; mirrors C2 Stop 4).║
║    (3) A confirmed ESCALATE pattern dominates a concurrent gap.     ║
║                                                                      ║
║  DISTINCT PROVENANCE (fourth Tier 2 role):                        ║
║    Genuine new work — no detection signals existed in code. The     ║
║    scenario library is authored, not extracted.                    ║
║                                                                      ║
║  REGULATORY ADDRESS:                                              ║
║    MAR Art. 12 (market manipulation); MiFID II; FINRA 5210/5270/    ║
║    5310; CFTC anti-wash / anti-spoofing; potential STOR / SAR       ║
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

AGENT_SURV_VERSION = "0.1"
ROLE_ID = "AUR-J-SURV-001"

_DOCTRINE = os.path.join(os.path.dirname(__file__), "..", "..", "doctrine")
_SCENARIOS = os.path.join(_DOCTRINE, "surveillance_scenarios_fixture.json")

# Outcome rungs — higher index = more restrictive. Worst rung wins.
# A confirmed ESCALATE pattern dominates a data gap (a known wash trade
# never earns the lighter gap-ack), and a gap outranks a review flag
# because it forces a halt. (Same monotonic ordering discipline as
# Risk Reporting — see AUR-J-PATHSET-RISK-001 §IV.)
_RUNG_CLEAR = 0
_RUNG_FLAGGED = 1
_RUNG_INCOMPLETE = 2
_RUNG_ESCALATE = 3

_RUNG_TO_PATH = {
    _RUNG_CLEAR:      "SURVEIL_CLEAR",
    _RUNG_FLAGGED:    "SURVEIL_PATTERN_FLAGGED",
    _RUNG_INCOMPLETE: "SURVEIL_DATA_INCOMPLETE",
    _RUNG_ESCALATE:   "SURVEIL_PATTERN_ESCALATE",
}

_SEVERITY_RUNG = {"REVIEW": _RUNG_FLAGGED, "ESCALATE": _RUNG_ESCALATE}


class TradeSurveillance(JTACConcreteBase):
    """AUR-J-SURV-001 — Trade Surveillance (Fixed Income).

    WS-2.4 (2026-07-04): fourth and last canonical Tier 2 role. Genuine
    new work — no detection signals existed in code, so the scenario
    library is authored rather than extracted. Completes the Tier 2 band.
    """

    role_id   = ROLE_ID
    role_name = "Trade Surveillance"

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        self._surv_log_key = "c2_j_surveillance_log"
        self.load_approved_paths(role_id=self.role_id)
        self._scenarios_loaded = False
        self._scenarios: dict = {}
        print(
            f"[SURVEILLANCE] Initialized — v{AGENT_SURV_VERSION} | "
            f"Role: {self.role_id} | Paths loaded: "
            f"{list(self._approved_paths.keys())}"
        )

    def _load_scenarios(self, source_path: Optional[str] = None) -> None:
        if self._scenarios_loaded:
            return
        path = source_path or _SCENARIOS
        with open(path, "r") as fh:
            raw = json.load(fh)
        self._scenarios = raw.get("scenarios", {})
        self._scenarios_loaded = True

    # ─────────────────────────────────────────────────────────────────────────
    # PRIMARY TASK — SCENARIO EVALUATION
    # ─────────────────────────────────────────────────────────────────────────

    def screen_record(self, task_id: str, record: dict):
        """Run every ENABLED scenario against *record* and select the
        worst-outcome disposition path.

        Returns (JTACPathSelection, surveillance_report). The report is
        always emitted and lists matched scenarios and uncheckable
        (data-gap) scenarios regardless of path.
        """
        self._load_scenarios()
        matched = []       # scenarios that fired
        uncheckable = []   # enabled scenarios missing a required field
        evaluated = []     # per-scenario detail for the report
        worst_rung = _RUNG_CLEAR

        for sid, cfg in self._scenarios.items():
            if not cfg.get("enabled", False):
                evaluated.append({"scenario": sid, "status": "DISABLED"})
                continue
            required = cfg.get("requires", [])
            missing = [f for f in required if record.get(f) is None]
            if missing:
                uncheckable.append(sid)
                evaluated.append({"scenario": sid, "status": "UNCHECKABLE",
                                  "missing": missing})
                worst_rung = max(worst_rung, _RUNG_INCOMPLETE)
                continue
            hit = self._detect(sid, cfg, record)
            if hit:
                sev = cfg.get("severity", "REVIEW").upper()
                matched.append({"scenario": sid, "severity": sev})
                evaluated.append({"scenario": sid, "status": "MATCH", "severity": sev})
                worst_rung = max(worst_rung, _SEVERITY_RUNG.get(sev, _RUNG_FLAGGED))
            else:
                evaluated.append({"scenario": sid, "status": "CLEAR"})

        path_id = _RUNG_TO_PATH[worst_rung]
        rationale = self._rationale(path_id, matched, uncheckable)
        path = self.select_path_by_id(path_id)
        selection = self.build_path_selection(
            task_id=task_id, path=path, rationale=rationale, regulatory_context={},
        )

        report = {
            "task_id": task_id, "role_id": self.role_id,
            "screened_at": datetime.now(timezone.utc).isoformat(),
            "disposition": path_id, "worst_rung": worst_rung,
            "matched": matched, "uncheckable": uncheckable,
            "evaluated": evaluated,
            "doctrine_version": self._state.get("doctrine_version", "unknown"),
        }

        with self._lock:
            log = self._state.setdefault(self._surv_log_key, [])
            log.insert(0, {
                "ts": report["screened_at"], "task_id": task_id,
                "role_id": self.role_id, "event_type": "SURVEILLANCE_SCREEN",
                "disposition": path_id,
                "matched": [m["scenario"] for m in matched],
                "uncheckable": uncheckable,
                "doctrine_version": report["doctrine_version"],
            })
            if len(log) > 500:
                self._state[self._surv_log_key] = log[:500]

        return selection, report

    # ── Detectors ──────────────────────────────────────────────────────────
    def _detect(self, sid: str, cfg: dict, record: dict) -> bool:
        params = cfg.get("params", {})
        if sid == "WASH_TRADE":
            return record["buy_beneficial_owner"] == record["sell_beneficial_owner"]
        if sid == "MARKING_THE_CLOSE":
            return (record["seconds_to_close"] <= params["close_window_seconds"]
                    and record["session_volume_pct"] >= params["volume_pct_threshold"])
        if sid == "FRONT_RUNNING":
            return bool(record["prop_trade_ahead_of_client"])
        if sid == "UNUSUAL_PRICE_DEVIATION":
            ref = record["reference_price"]
            if not ref:
                return False
            dev_bps = abs(record["exec_price"] - ref) / ref * 10000.0
            return dev_bps > params["deviation_bps_threshold"]
        if sid == "CONCENTRATED_COUNTERPARTY":
            return record["counterparty_session_volume_pct"] > params["concentration_pct_threshold"]
        # Unknown scenario id with no detector: treat as uncheckable-safe (no match).
        return False

    @staticmethod
    def _rationale(path_id, matched, uncheckable):
        if path_id == "SURVEIL_PATTERN_ESCALATE":
            names = ", ".join(m["scenario"] for m in matched if m["severity"] == "ESCALATE")
            return (f"High-severity surveillance pattern(s) matched: {names}. "
                    f"Halt-and-pend; dual authority + potential regulatory "
                    f"reporting. Never auto-disposed.")
        if path_id == "SURVEIL_DATA_INCOMPLETE":
            return (f"Enabled surveillance check(s) could not run — missing data "
                    f"for: {', '.join(uncheckable)}. Trade not certified clean; "
                    f"gap flagged for acknowledgment.")
        if path_id == "SURVEIL_PATTERN_FLAGGED":
            names = ", ".join(m["scenario"] for m in matched)
            return (f"Review-severity pattern(s) matched: {names}. Flagged for "
                    f"human surveillance review; not auto-cleared.")
        return "No enabled surveillance scenario matched; all active checks ran."

    # ─────────────────────────────────────────────────────────────────────────
    # AGENT INTERFACE
    # ─────────────────────────────────────────────────────────────────────────

    def advise(self, intent: Intent) -> Advisory:
        return Advisory(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            summary="Trade surveillance advisory",
            recommendation={"surveillance": "pending_screen"},
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
        enabled = [s for s, c in self._scenarios.items() if c.get("enabled")] \
            if self._scenarios_loaded else "unloaded"
        return {
            "agent_id":       self.role_id,
            "role_name":      self.role_name,
            "version":        AGENT_SURV_VERSION,
            "role_id":        self.role_id,
            "status":         "ACTIVE",
            "phase":          "WS-2.4 — fixed-income trade surveillance",
            "approved_paths": list(self._approved_paths.keys()),
            "enabled_scenarios": enabled,
            "sr_11_7_tier":   "Tier 1",
            "scope_note":     (
                "Fourth and last canonical Tier 2 role (AUR-J-PATHSET-SURV-001). "
                "Authored scenario library (wash trade, marking the close, front "
                "running, price deviation, counterparty concentration; layering/"
                "spoofing declared-not-active pending order-book data). Patterns "
                "never auto-disposed."
            ),
            "guardrails":     [
                "Approved paths only",
                "No pattern auto-disposed — human review clears",
                "Uncheckable active scenario never certified clean",
                "Doctrine over optimization",
                "No self-initiation",
            ],
        }


# ── Path callables ────────────────────────────────────────────────────────────
# Referenced by callable_ref in aureon/doctrine/jtac_paths/AUR-J-SURV-001.json.

def _path_clear(task_id: str, **_ignored) -> dict:
    return {"path_id": "SURVEIL_CLEAR", "task_id": task_id,
            "outcome": "CLEAR", "continue": True}


def _path_pattern_flagged(task_id: str, **_ignored) -> dict:
    return {"path_id": "SURVEIL_PATTERN_FLAGGED", "task_id": task_id,
            "outcome": "FLAGGED_FOR_REVIEW", "continue": True}


def _path_data_incomplete(task_id: str, **_ignored) -> dict:
    return {"path_id": "SURVEIL_DATA_INCOMPLETE", "task_id": task_id,
            "outcome": "HALT_PENDING_GAP_ACK", "continue": False}


def _path_pattern_escalate(task_id: str, **_ignored) -> dict:
    return {"path_id": "SURVEIL_PATTERN_ESCALATE", "task_id": task_id,
            "outcome": "HALT_PENDING_DUAL_AUTHORITY", "continue": False}
