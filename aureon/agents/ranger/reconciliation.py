"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/ranger/reconciliation.py                              ║
║  Reconciliation — AUR-R-RECON-001                                    ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Match internal positions against custodian depot records.         ║
║    Identify and classify cash breaks across settlement accounts.     ║
║    Match executed trades against DSOR pre-trade records.             ║
║    Assemble root-cause lineage for break resolution.                 ║
║    Track resolution workflow — no autonomous resolution.             ║
║                                                                      ║
║  REGULATORY ADDRESS:                                                 ║
║    BCBS 239 P3 — accuracy, integrity, reconciliation lineage        ║
║    DORA — data integrity, ICT risk management                       ║
║    SR 11-7 Tier 2 — deterministic, annual review                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aureon.agents.ranger._base import RangerConcreteBase
from aureon.agents.base import Escalation

if TYPE_CHECKING:
    from aureon.agents.c2.coordinator import ThifurC2

RECON_VERSION = "1.0"
ALGORITHM_ID  = "AUR-R-RECON-001"

# ── Cash Break Classifications ────────────────────────────────────────────────
BREAK_URGENCY_THRESHOLDS = {
    "CRITICAL": 1_000_000,
    "HIGH":       100_000,
    "MEDIUM":      10_000,
}


class Reconciliation(RangerConcreteBase):
    """AUR-R-RECON-001 — Reconciliation Analyst.

    Depot vs ledger reconciliation, cash break identification,
    DSOR intent vs execution matching, root cause lineage assembly,
    resolution workflow tracking. Writes to c2_r_reconciliation_log.
    """

    role_id   = "AUR-R-RECON-001"
    role_name = "Reconciliation Analyst"

    regulatory_frameworks = [
        "BCBS 239 P3",
        "DORA",
        "SR 11-7 Tier 2",
    ]

    dsor_record_types = [
        "break_record",
        "root_cause_lineage",
        "resolution_confirmation",
        "audit_trail",
    ]

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        print(f"[RECON] Initialized — v{RECON_VERSION} | "
              f"Zero variance — deterministic only | BCBS 239 P3")

    # ─────────────────────────────────────────────────────────────────────────
    # RANGERCONCRETEBASE CONTRACT
    # ─────────────────────────────────────────────────────────────────────────

    def prepare_execution_package(self,
                                  decision: dict,
                                  task_id: str,
                                  c2: "ThifurC2") -> dict:
        """Build reconciliation execution package.

        For Reconciliation, this is the break identification +
        classification package that downstream consumers (human
        authority, C2 telemetry) use to initiate review.
        """
        blocked = self._check_handoff_and_halt(task_id)
        if blocked:
            return blocked

        ts = datetime.now(timezone.utc).isoformat()

        with self._lock:
            doctrine_version = self._state.get("doctrine_version", "unknown")

        symbol   = decision.get("symbol", "")
        action   = decision.get("action", "")
        notional = decision.get("notional", 0)

        lineage_stamp = self._build_lineage_stamp(
            decision         = decision,
            task_id          = task_id,
            doctrine_version = doctrine_version,
            ts               = ts,
        )

        recon_package = {
            "decision_id":      decision.get("id"),
            "task_id":          task_id,
            "symbol":           symbol,
            "action":           action,
            "notional":         notional,
            "authority_hash":   lineage_stamp["authority_hash"],
            "doctrine_version": doctrine_version,
            "agent":            self.role_id,
            "algorithm_id":     ALGORITHM_ID,
            "package_type":     "reconciliation_initiation",
        }

        self._write_recon_log(
            task_id=task_id, ts=ts,
            action=f"RECON_INIT · {action} {symbol}",
            status="INITIATED",
            authority_hash=lineage_stamp["authority_hash"],
            doctrine_version=doctrine_version,
            notional=notional, symbol=symbol,
        )

        self._write_authority_log(
            task_id        = task_id,
            ts             = ts,
            event_type     = f"Reconciliation Initiated · {action} {symbol}",
            outcome        = (f"${notional:,.0f} | "
                              f"Hash: {lineage_stamp['authority_hash']}"),
            authority_hash = lineage_stamp["authority_hash"],
        )

        self._handoff_confirmed = False

        print(f"[RECON] Package prepared: {action} {symbol} "
              f"${notional:,.0f} | Task: {task_id}")

        return {
            "agent":            self.role_id,
            "algorithm_id":     ALGORITHM_ID,
            "task_id":          task_id,
            "ts":               ts,
            "status":           "COMPLETE",
            "recon_package":    recon_package,
            "lineage_stamp":    lineage_stamp,
            "doctrine_version": doctrine_version,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 1 — DEPOT VS LEDGER RECONCILIATION
    # ─────────────────────────────────────────────────────────────────────────

    def reconcile_depot_vs_ledger(self,
                                  depot_positions: dict,
                                  ledger_positions: dict) -> dict:
        """Match internal position records against custodian depot records.

        depot_positions:  {symbol: shares, ...} from custodian
        ledger_positions: {symbol: shares, ...} from internal ledger
        """
        ts = datetime.now(timezone.utc).isoformat()

        all_symbols = set(depot_positions.keys()) | set(ledger_positions.keys())
        discrepancies = []

        for sym in sorted(all_symbols):
            depot_qty  = depot_positions.get(sym, 0)
            ledger_qty = ledger_positions.get(sym, 0)
            delta = depot_qty - ledger_qty
            if delta != 0:
                discrepancies.append({
                    "symbol":     sym,
                    "depot_qty":  depot_qty,
                    "ledger_qty": ledger_qty,
                    "delta":      delta,
                    "severity":   self._classify_severity(abs(delta)),
                })

        matched = len(discrepancies) == 0
        status  = "MATCHED" if matched else "DISCREPANCY"

        self._write_recon_log(
            task_id="DEPOT-RECON", ts=ts,
            action="DEPOT_VS_LEDGER",
            status=status,
            authority_hash="",
            doctrine_version=self._state.get("doctrine_version", "unknown"),
        )

        print(f"[RECON] Depot vs ledger: {status} | "
              f"{len(all_symbols)} symbols | "
              f"{len(discrepancies)} discrepancies")

        return {
            "agent":            self.role_id,
            "ts":               ts,
            "status":           status,
            "matched":          matched,
            "symbols_checked":  len(all_symbols),
            "discrepancies":    discrepancies,
            "discrepancy_count": len(discrepancies),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 2 — CASH BREAK IDENTIFICATION
    # ─────────────────────────────────────────────────────────────────────────

    def identify_cash_breaks(self,
                             settlement_account_snapshot: dict) -> list:
        """Identify and classify cash breaks across settlement accounts.

        settlement_account_snapshot: {account_id: {expected: float, actual: float}, ...}
        """
        ts = datetime.now(timezone.utc).isoformat()
        breaks = []

        for acct_id, balances in settlement_account_snapshot.items():
            expected = balances.get("expected", 0.0)
            actual   = balances.get("actual", 0.0)
            delta    = round(actual - expected, 2)

            if delta != 0:
                abs_delta = abs(delta)
                breaks.append({
                    "account_id": acct_id,
                    "expected":   expected,
                    "actual":     actual,
                    "delta":      delta,
                    "type":       "SURPLUS" if delta > 0 else "SHORTFALL",
                    "urgency":    self._classify_urgency(abs_delta),
                    "ts":         ts,
                })

        for brk in breaks:
            self._write_recon_log(
                task_id=f"CASH-BRK-{brk['account_id']}", ts=ts,
                action="CASH_BREAK",
                status=brk["urgency"],
                authority_hash="",
                doctrine_version=self._state.get("doctrine_version", "unknown"),
            )

        print(f"[RECON] Cash breaks: {len(breaks)} identified across "
              f"{len(settlement_account_snapshot)} accounts")

        return breaks

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 3 — DSOR INTENT VS EXECUTION MATCHING
    # ─────────────────────────────────────────────────────────────────────────

    def match_intent_vs_execution(self,
                                  dsor_intent: dict,
                                  execution_record: dict) -> dict:
        """Match executed trade against its DSOR pre-trade record.

        Audit chain is complete only when both legs confirm.
        """
        ts = datetime.now(timezone.utc).isoformat()

        fields_to_match = ["symbol", "action", "shares", "notional"]
        unmatched = []

        for field in fields_to_match:
            intent_val = dsor_intent.get(field)
            exec_val   = execution_record.get(field)
            if intent_val != exec_val:
                unmatched.append({
                    "field":    field,
                    "intent":   intent_val,
                    "executed": exec_val,
                })

        matched = len(unmatched) == 0
        status  = "MATCHED" if matched else "UNMATCHED"

        self._write_recon_log(
            task_id=dsor_intent.get("task_id", ""),
            ts=ts,
            action="INTENT_VS_EXECUTION",
            status=status,
            authority_hash=dsor_intent.get("authority_hash", ""),
            doctrine_version=self._state.get("doctrine_version", "unknown"),
        )

        print(f"[RECON] Intent vs execution: {status} | "
              f"{dsor_intent.get('symbol', '?')} | "
              f"Unmatched: {len(unmatched)}")

        return {
            "agent":          self.role_id,
            "ts":             ts,
            "decision_id":    dsor_intent.get("id"),
            "status":         status,
            "matched":        matched,
            "fields_checked": fields_to_match,
            "unmatched":      unmatched,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 4 — ROOT CAUSE LINEAGE ASSEMBLY
    # ─────────────────────────────────────────────────────────────────────────

    def assemble_root_cause_lineage(self, break_id: str) -> dict:
        """Assemble break lineage for human authority review.

        Scans reconciliation log and authority log for all entries
        related to the break, assembling the full handoff trail.
        """
        ts = datetime.now(timezone.utc).isoformat()

        with self._lock:
            recon_entries = [
                e for e in self._state.get("c2_r_reconciliation_log", [])
                if e.get("task_id") == break_id
            ]
            authority_entries = [
                e for e in self._state.get("authority_log", [])
                if break_id in e.get("outcome", "") or break_id in e.get("id", "")
            ]

        lineage = {
            "agent":               self.role_id,
            "break_id":            break_id,
            "assembled_ts":        ts,
            "source_system":       "aureon_state",
            "counterparty":        "custodian",
            "instrument":          recon_entries[0].get("symbol", "—") if recon_entries else "—",
            "timing":              recon_entries[0].get("ts", "—") if recon_entries else "—",
            "agent_handoff_trail": [e.get("action", "") for e in recon_entries],
            "authority_trail":     [e.get("type", "") for e in authority_entries],
            "recon_events":        len(recon_entries),
            "authority_events":    len(authority_entries),
        }

        print(f"[RECON] Root cause lineage assembled: {break_id} | "
              f"{len(recon_entries)} recon events, "
              f"{len(authority_entries)} authority events")

        return lineage

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 5 — RESOLUTION WORKFLOW
    # ─────────────────────────────────────────────────────────────────────────

    def track_resolution(self, break_id: str) -> dict:
        """Track break through resolution workflow.

        No autonomous resolution. Returns current state and
        pending human authority actions.
        """
        with self._lock:
            entries = [
                e for e in self._state.get("c2_r_reconciliation_log", [])
                if e.get("task_id") == break_id
            ]

        if not entries:
            return {
                "agent":    self.role_id,
                "break_id": break_id,
                "status":   "NOT_FOUND",
                "stages":   [],
            }

        stages = []
        for entry in reversed(entries):
            stages.append({
                "ts":     entry.get("ts"),
                "action": entry.get("action"),
                "status": entry.get("status"),
            })

        current_status = entries[0].get("status", "UNKNOWN")
        resolved = current_status == "RESOLVED"

        return {
            "agent":                    self.role_id,
            "break_id":                 break_id,
            "status":                   current_status,
            "resolved":                 resolved,
            "stages":                   stages,
            "stage_count":              len(stages),
            "pending_human_authority":  not resolved,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 6 — BREAK ESCALATION
    # ─────────────────────────────────────────────────────────────────────────

    def escalate_break(self, break_context: dict) -> Escalation:
        """No autonomous resolution. Package full context and escalate."""
        reason = (
            f"Reconciliation break: {break_context.get('type', 'UNKNOWN')} | "
            f"{break_context.get('symbol', break_context.get('account_id', '?'))} | "
            f"Delta: {break_context.get('delta', '?')}"
        )
        return self.escalate(reason)

    # ─────────────────────────────────────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return Reconciliation operational status for dashboard."""
        return {
            "agent_id":              self.role_id,
            "role_name":             self.role_name,
            "version":               RECON_VERSION,
            "algorithm_id":          ALGORITHM_ID,
            "status":                "ACTIVE",
            "phase":                 "Phase 1 — Cross-System Reconciliation and Break Management",
            "bcbs_239_p3":           "Accuracy and integrity — reconciliation lineage",
            "dora":                  "Data integrity — ICT risk management",
            "sr_11_7_tier":          "Tier 2 — Deterministic",
            "regulatory_frameworks": self.regulatory_frameworks,
            "dsor_record_types":     self.dsor_record_types,
            "guardrails": [
                "Zero variance — one input, one output, always",
                "No self-initiation — C2 handoff required",
                "No autonomous break resolution",
                "Immediate escalation on discrepancy",
                "Full root-cause lineage on every break",
            ],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _write_recon_log(self, task_id: str, ts: str,
                          action: str, status: str,
                          authority_hash: str, doctrine_version: str,
                          notional: float = 0, symbol: str = "") -> None:
        """Write to c2_r_reconciliation_log."""
        with self._lock:
            r_log = self._state.setdefault("c2_r_reconciliation_log", [])
            r_log.insert(0, {
                "task_id":          task_id,
                "ts":               ts,
                "operator":         "CAOM-001",
                "caom_mode":        "CAOM-001",
                "role_id":          self.role_id,
                "action":           action,
                "symbol":           symbol,
                "notional":         notional,
                "status":           status,
                "authority_hash":   authority_hash,
                "doctrine_version": doctrine_version,
            })
            if len(r_log) > 200:
                self._state["c2_r_reconciliation_log"] = r_log[:200]

    def _classify_severity(self, abs_delta: float) -> str:
        if abs_delta >= 10000:
            return "HIGH"
        if abs_delta >= 100:
            return "MEDIUM"
        return "LOW"

    def _classify_urgency(self, abs_amount: float) -> str:
        for urgency, threshold in BREAK_URGENCY_THRESHOLDS.items():
            if abs_amount >= threshold:
                return urgency
        return "LOW"
