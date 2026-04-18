"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/ranger/_base.py                                       ║
║  RangerConcreteBase — Generic Ranger machinery                       ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Enforce C2 handoff authorization for all Ranger roles.            ║
║    Emit execution telemetry to C2 for unified lineage assembly.     ║
║    Write authority_log entries on every lifecycle action.             ║
║    Delegate role-specific payload assembly to subclasses.            ║
║                                                                      ║
║  GUARDRAILS:                                                         ║
║    - Zero variance — one input, one output, always                  ║
║    - No self-initiation — requires C2 handoff authorization          ║
║    - Immediate escalation on any discrepancy                         ║
║    - Immutable lineage — stamped at execution, never modified        ║
║                                                                      ║
║  REGULATORY ADDRESS:                                                 ║
║    SR 11-7 Tier 2 — deterministic, annual review                   ║
║    BCBS 239 P3 — automated accuracy, no manual error               ║
║    MiFID II RTS 6 — post-trade risk controls, 5s alerts            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import hashlib
import threading
from abc import abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aureon.agents.base import RangerAgent, Intent, Advisory, Tasking, Result

if TYPE_CHECKING:
    from aureon.agents.c2.coordinator import ThifurC2

RANGER_VERSION = "1.0"


class RangerConcreteBase(RangerAgent):
    """Generic concrete base for all Thifur-R roles.

    Enforces C2 handoff, emits telemetry, writes authority_log.
    Role-specific payload assembly is the subclass's responsibility.
    """

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        self._handoff_confirmed = False

    # ─────────────────────────────────────────────────────────────────────────
    # C2 HANDOFF ENFORCEMENT
    # ─────────────────────────────────────────────────────────────────────────

    def confirm_handoff(self, handoff_record: dict) -> bool:
        """Guardrail: Ranger may not proceed without a valid C2 handoff."""
        if not handoff_record.get("c2_authorized"):
            print(f"[{self.role_id}] BLOCKED — handoff not C2-authorized: "
                  f"{handoff_record.get('handoff_id')}")
            return False

        if handoff_record.get("to_agent") not in (self.role_id, "THIFUR_R"):
            print(f"[{self.role_id}] BLOCKED — handoff directed to "
                  f"{handoff_record.get('to_agent')}, not {self.role_id}")
            return False

        self._handoff_confirmed = True
        print(f"[{self.role_id}] Handoff confirmed: "
              f"{handoff_record.get('handoff_id')} | "
              f"Task: {handoff_record.get('task_id')}")
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # EXECUTION TELEMETRY
    # ─────────────────────────────────────────────────────────────────────────

    def emit_execution_confirmation(self,
                                    task_id: str,
                                    decision: dict,
                                    exec_price: float,
                                    authority_hash: str,
                                    gate_results: list,
                                    c2: "ThifurC2") -> dict:
        """Emit execution confirmation telemetry to C2 — BCBS 239 P3."""
        ts = datetime.now(timezone.utc).isoformat()
        confirmation_hash = self._build_confirmation_hash(
            task_id, decision, exec_price, ts
        )

        confirmation = {
            "agent":             self.role_id,
            "task_id":           task_id,
            "event_type":        "EXECUTION_CONFIRMED",
            "ts":                ts,
            "decision_id":       decision.get("id"),
            "symbol":            decision.get("symbol"),
            "action":            decision.get("action"),
            "exec_price":        round(exec_price, 2),
            "shares":            decision.get("shares"),
            "notional":          round(decision.get("shares", 0) * exec_price, 2),
            "authority_hash":    authority_hash,
            "confirmation_hash": confirmation_hash,
            "gate_results":      gate_results,
            "status":            "CONFIRMED",
        }

        c2.record_agent_telemetry(task_id, f"{self.role_id}_CONFIRMED", confirmation)

        print(f"[{self.role_id}] Execution confirmed — "
              f"{decision.get('action')} {decision.get('symbol')} "
              f"@ ${exec_price:,.2f} | Task: {task_id} | "
              f"Hash: {confirmation_hash}")

        return confirmation

    # ─────────────────────────────────────────────────────────────────────────
    # ROLE-SPECIFIC ABSTRACT
    # ─────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def prepare_execution_package(self,
                                  decision: dict,
                                  task_id: str,
                                  c2: "ThifurC2") -> dict:
        """Role-specific package assembly. Subclass responsibility."""
        ...

    # ─────────────────────────────────────────────────────────────────────────
    # ABC METHOD IMPLEMENTATIONS
    # ─────────────────────────────────────────────────────────────────────────

    def advise(self, intent: Intent) -> Advisory:
        """Ranger agents do not advise — they execute deterministically."""
        return Advisory(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            summary="Ranger agent — deterministic execution only, no advisory",
            recommendation={},
            requires_approval=False,
        )

    def execute(self, tasking: Tasking) -> Result:
        """Execute a C2-issued tasking via role-specific package builder."""
        return Result(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            outcome="DELEGATED",
            dsor_record_id=tasking.c2_tasking_id,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # SHARED HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _build_lineage_stamp(self, decision: dict, task_id: str,
                              doctrine_version: str, ts: str) -> dict:
        """Build the immutable lineage stamp — BCBS 239 P3."""
        stamp_seed = (
            f"{task_id}"
            f"{decision.get('id')}"
            f"{decision.get('symbol')}"
            f"{decision.get('action')}"
            f"{decision.get('shares')}"
            f"{doctrine_version}"
            f"{ts}"
        )
        authority_hash = hashlib.sha256(stamp_seed.encode()).hexdigest()[:32].upper()

        return {
            "task_id":          task_id,
            "decision_id":      decision.get("id"),
            "stamped_ts":       ts,
            "doctrine_version": doctrine_version,
            "agent":            self.role_id,
            "authority_hash":   authority_hash,
            "immutable":        True,
            "bcbs_239_p3":      "AUTOMATED — no manual modification permitted",
        }

    def _build_confirmation_hash(self, task_id: str, decision: dict,
                                  exec_price: float, ts: str) -> str:
        seed = (
            f"CONFIRM"
            f"{task_id}"
            f"{decision.get('id')}"
            f"{exec_price}"
            f"{ts}"
        )
        return hashlib.sha256(seed.encode()).hexdigest()[:20].upper()

    def _write_authority_log(self, task_id: str, ts: str,
                              event_type: str, outcome: str,
                              authority_hash: str) -> None:
        """Write a standard authority_log entry."""
        with self._lock:
            self._state.setdefault("authority_log", []).insert(0, {
                "id":        f"HAD-R-{task_id[-6:]}",
                "ts":        ts,
                "tier":      "Thifur-R",
                "type":      event_type,
                "authority": self.role_id,
                "outcome":   outcome,
                "hash":      authority_hash,
            })

    def _check_handoff_and_halt(self, task_id: str) -> dict | None:
        """Pre-flight check: handoff confirmed + no system halt. Returns error dict or None."""
        if not self._handoff_confirmed:
            return {
                "agent":   self.role_id,
                "status":  "BLOCKED",
                "reason":  "Handoff not confirmed — C2 authorization required",
                "task_id": task_id,
            }

        with self._lock:
            halt_active = self._state.get("halt_active", False)

        if halt_active:
            return {
                "agent":   self.role_id,
                "status":  "BLOCKED",
                "reason":  "System HALT active — Tier 0 stop.",
                "task_id": task_id,
            }

        return None
