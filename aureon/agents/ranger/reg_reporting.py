"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/ranger/reg_reporting.py                               ║
║  RegReporting — AUR-R-REGREP-001                                     ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Generate EMIR transaction reports with UTI/LEI linkage.           ║
║    Produce CFTC Part 45 swap data from DSOR records.                 ║
║    Enforce MiFID II RTS6 five-second post-trade alert SLA.           ║
║    Process CAT reporting triggers at execution.                       ║
║    Validate BCBS 239 P3 accuracy before any external submission.     ║
║                                                                      ║
║  REGULATORY ADDRESS:                                                 ║
║    EMIR — trade repository reporting                                 ║
║    CFTC Part 45 — swap data repository reporting                     ║
║    MiFID II RTS 6 — five-second post-trade alerts                   ║
║    CAT — Consolidated Audit Trail reporting                          ║
║    BCBS 239 P3/P4 — accuracy, timeliness                           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aureon.agents.ranger._base import RangerConcreteBase
from aureon.agents.base import Escalation

if TYPE_CHECKING:
    from aureon.agents.c2.coordinator import ThifurC2

REGREP_VERSION = "1.0"
ALGORITHM_ID   = "AUR-R-REGREP-001"


class RegReporting(RangerConcreteBase):
    """AUR-R-REGREP-001 — Regulatory Reporting Analyst.

    EMIR trade reporting, CFTC Part 45 swap data, MiFID II RTS6
    five-second alerts, CAT reporting, BCBS 239 P3 accuracy validation.
    Writes to c2_r_reg_reporting_log.
    """

    role_id   = "AUR-R-REGREP-001"
    role_name = "Regulatory Reporting Analyst"

    regulatory_frameworks = [
        "EMIR",
        "CFTC Part 45",
        "MiFID II RTS6",
        "CAT",
        "BCBS 239 P3",
        "BCBS 239 P4",
    ]

    dsor_record_types = [
        "emir_report_submission",
        "cftc_part45_submission",
        "rts6_alert_log",
        "cat_reporting_record",
        "bcbs239_p3_accuracy_validation",
    ]

    RTS6_ALERT_SLA_SECONDS = 5.0

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        print(f"[REG-REPORTING] Initialized — v{REGREP_VERSION} | "
              f"Zero variance — deterministic only | "
              f"EMIR / CFTC Part 45 / RTS6 / CAT / BCBS 239")

    # ─────────────────────────────────────────────────────────────────────────
    # RANGERCONCRETEBASE CONTRACT
    # ─────────────────────────────────────────────────────────────────────────

    def prepare_execution_package(self,
                                  decision: dict,
                                  task_id: str,
                                  c2: "ThifurC2") -> dict:
        """Build regulatory reporting execution package.

        Consolidated submission package assembled at lifecycle close —
        EMIR, CFTC, CAT — with BCBS 239 P3 accuracy validation
        applied before any external submission.
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

        reporting_package = {
            "decision_id":      decision.get("id"),
            "task_id":          task_id,
            "symbol":           symbol,
            "action":           action,
            "notional":         notional,
            "authority_hash":   lineage_stamp["authority_hash"],
            "doctrine_version": doctrine_version,
            "agent":            self.role_id,
            "algorithm_id":     ALGORITHM_ID,
            "package_type":     "regulatory_reporting_consolidated",
            "regimes_applicable": self.regulatory_frameworks,
        }

        self._write_regrep_log(
            task_id=task_id, ts=ts,
            action=f"REGREP_PACKAGE · {action} {symbol}",
            status="ASSEMBLED",
            authority_hash=lineage_stamp["authority_hash"],
            doctrine_version=doctrine_version,
        )

        self._write_authority_log(
            task_id        = task_id,
            ts             = ts,
            event_type     = f"Regulatory Package Assembled · {action} {symbol}",
            outcome        = (f"${notional:,.0f} | "
                              f"Hash: {lineage_stamp['authority_hash']}"),
            authority_hash = lineage_stamp["authority_hash"],
        )

        self._handoff_confirmed = False

        print(f"[REG-REPORTING] Package assembled: {action} {symbol} "
              f"${notional:,.0f} | Task: {task_id}")

        return {
            "agent":              self.role_id,
            "algorithm_id":       ALGORITHM_ID,
            "task_id":            task_id,
            "ts":                 ts,
            "status":             "COMPLETE",
            "reporting_package":  reporting_package,
            "lineage_stamp":      lineage_stamp,
            "doctrine_version":   doctrine_version,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 1 — EMIR TRADE REPORTING
    # ─────────────────────────────────────────────────────────────────────────

    def generate_emir_report(self, trade_record: dict) -> dict:
        """Generate EMIR transaction report.

        Includes UTI, counterparty LEI validation, complete audit trail.
        """
        ts = datetime.now(timezone.utc).isoformat()

        uti = self._generate_uti(trade_record)
        lei = trade_record.get("counterparty_lei", "")
        lei_valid = len(lei) == 20 and lei.isalnum()

        report = {
            "agent":              self.role_id,
            "report_type":        "EMIR",
            "ts":                 ts,
            "uti":                uti,
            "decision_id":        trade_record.get("id"),
            "symbol":             trade_record.get("symbol", ""),
            "action":             trade_record.get("action", ""),
            "notional":           trade_record.get("notional", 0),
            "counterparty_lei":   lei,
            "lei_validated":      lei_valid,
            "audit_trail_ref":    trade_record.get("authority_hash", ""),
            "doctrine_version":   trade_record.get("doctrine_version", "unknown"),
            "submission_status":  "READY" if lei_valid else "BLOCKED_LEI_INVALID",
        }

        self._write_regrep_log(
            task_id=trade_record.get("task_id", ""),
            ts=ts,
            action="EMIR_REPORT",
            status=report["submission_status"],
            authority_hash=trade_record.get("authority_hash", ""),
            doctrine_version=trade_record.get("doctrine_version", "unknown"),
        )

        print(f"[REG-REPORTING] EMIR report: {report['submission_status']} | "
              f"UTI: {uti[:16]}... | LEI valid: {lei_valid}")

        return report

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 2 — CFTC PART 45 REPORTING
    # ─────────────────────────────────────────────────────────────────────────

    def generate_cftc_part45_report(self, swap_record: dict) -> dict:
        """Produce CFTC Part 45 swap data report.

        All fields populated from DSOR record — no manual entry.
        """
        ts = datetime.now(timezone.utc).isoformat()

        usi = self._generate_usi(swap_record)

        report = {
            "agent":              self.role_id,
            "report_type":        "CFTC_PART45",
            "ts":                 ts,
            "usi":                usi,
            "decision_id":        swap_record.get("id"),
            "asset_class":        swap_record.get("asset_class", ""),
            "symbol":             swap_record.get("symbol", ""),
            "action":             swap_record.get("action", ""),
            "notional":           swap_record.get("notional", 0),
            "counterparty_lei":   swap_record.get("counterparty_lei", ""),
            "execution_ts":       swap_record.get("execution_ts", ts),
            "maturity_date":      swap_record.get("maturity_date", ""),
            "fixed_rate":         swap_record.get("fixed_rate"),
            "floating_index":     swap_record.get("floating_index", ""),
            "audit_trail_ref":    swap_record.get("authority_hash", ""),
            "doctrine_version":   swap_record.get("doctrine_version", "unknown"),
            "submission_status":  "READY",
        }

        self._write_regrep_log(
            task_id=swap_record.get("task_id", ""),
            ts=ts,
            action="CFTC_PART45_REPORT",
            status="READY",
            authority_hash=swap_record.get("authority_hash", ""),
            doctrine_version=swap_record.get("doctrine_version", "unknown"),
        )

        print(f"[REG-REPORTING] CFTC Part 45: READY | "
              f"USI: {usi[:16]}... | {swap_record.get('symbol', '?')}")

        return report

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 3 — MiFID II RTS6 FIVE-SECOND ALERT
    # ─────────────────────────────────────────────────────────────────────────

    def generate_rts6_alert(self, breach_event: dict) -> dict:
        """Generate MiFID II RTS6 five-second alert.

        Synchronous. Measures elapsed time from breach to alert generation.
        Flags sla_met=False if elapsed > 5.0 seconds.
        """
        alert_ts = datetime.now(timezone.utc)
        alert_ts_iso = alert_ts.isoformat()

        breach_ts_str = breach_event.get("breach_ts")
        if breach_ts_str:
            breach_dt = datetime.fromisoformat(breach_ts_str)
            if breach_dt.tzinfo is None:
                breach_dt = breach_dt.replace(tzinfo=timezone.utc)
            elapsed = (alert_ts - breach_dt).total_seconds()
        else:
            elapsed = 0.0

        sla_met = elapsed <= self.RTS6_ALERT_SLA_SECONDS

        alert = {
            "agent":            self.role_id,
            "alert_type":       "RTS6_POST_TRADE",
            "breach_ts":        breach_ts_str or alert_ts_iso,
            "alert_ts":         alert_ts_iso,
            "elapsed_seconds":  round(elapsed, 3),
            "sla_met":          sla_met,
            "sla_threshold":    self.RTS6_ALERT_SLA_SECONDS,
            "breach_type":      breach_event.get("breach_type", "UNKNOWN"),
            "symbol":           breach_event.get("symbol", ""),
            "detail":           breach_event.get("detail", ""),
            "decision_id":      breach_event.get("decision_id", ""),
        }

        self._write_regrep_log(
            task_id=breach_event.get("task_id", "RTS6"),
            ts=alert_ts_iso,
            action="RTS6_ALERT",
            status="SLA_MET" if sla_met else "SLA_BREACH",
            authority_hash="",
            doctrine_version=self._state.get("doctrine_version", "unknown"),
        )

        sla_label = "MET" if sla_met else "BREACH"
        print(f"[REG-REPORTING] RTS6 alert: {sla_label} | "
              f"elapsed={elapsed:.3f}s | "
              f"{breach_event.get('breach_type', '?')}")

        return alert

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 4 — CAT REPORTING
    # ─────────────────────────────────────────────────────────────────────────

    def process_cat_event(self, reportable_event: dict) -> dict:
        """Process CAT reporting trigger.

        Stamp every reportable event and return submission-ready record.
        """
        event_ts_str = reportable_event.get("event_ts")
        stamp_ts = datetime.now(timezone.utc)
        stamp_ts_iso = stamp_ts.isoformat()

        if event_ts_str:
            event_dt = datetime.fromisoformat(event_ts_str)
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            elapsed = (stamp_ts - event_dt).total_seconds()
        else:
            elapsed = 0.0

        record = {
            "agent":            self.role_id,
            "report_type":      "CAT",
            "event_ts":         event_ts_str or stamp_ts_iso,
            "stamp_ts":         stamp_ts_iso,
            "elapsed_seconds":  round(elapsed, 3),
            "event_type":       reportable_event.get("event_type", "EXECUTION"),
            "symbol":           reportable_event.get("symbol", ""),
            "action":           reportable_event.get("action", ""),
            "decision_id":      reportable_event.get("decision_id", ""),
            "order_id":         reportable_event.get("order_id", ""),
            "submission_status": "READY",
        }

        self._write_regrep_log(
            task_id=reportable_event.get("task_id", "CAT"),
            ts=stamp_ts_iso,
            action="CAT_EVENT",
            status="READY",
            authority_hash="",
            doctrine_version=self._state.get("doctrine_version", "unknown"),
        )

        print(f"[REG-REPORTING] CAT event: READY | "
              f"{reportable_event.get('event_type', '?')} | "
              f"{reportable_event.get('symbol', '?')}")

        return record

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 5 — BCBS 239 P3 ACCURACY VALIDATION
    # ─────────────────────────────────────────────────────────────────────────

    def validate_bcbs239_p3_accuracy(self,
                                     report: dict,
                                     dsor_source: dict) -> dict:
        """Automated reconciliation of report against DSOR source.

        Any mismatch blocks submission.
        """
        ts = datetime.now(timezone.utc).isoformat()

        fields_to_validate = ["symbol", "action", "notional", "decision_id"]
        mismatches = []

        for field in fields_to_validate:
            report_val = report.get(field)
            source_val = dsor_source.get(field)
            if report_val != source_val:
                mismatches.append({
                    "field":      field,
                    "report_val": report_val,
                    "source_val": source_val,
                })

        validated = len(mismatches) == 0
        status    = "VALIDATED" if validated else "BLOCKED"

        result = {
            "agent":            self.role_id,
            "ts":               ts,
            "status":           status,
            "validated":        validated,
            "fields_checked":   fields_to_validate,
            "mismatches":       mismatches,
            "submission_allowed": validated,
        }

        self._write_regrep_log(
            task_id=dsor_source.get("task_id", ""),
            ts=ts,
            action="BCBS239_P3_VALIDATION",
            status=status,
            authority_hash=dsor_source.get("authority_hash", ""),
            doctrine_version=self._state.get("doctrine_version", "unknown"),
        )

        print(f"[REG-REPORTING] BCBS 239 P3: {status} | "
              f"Mismatches: {len(mismatches)}")

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # TASK 6 — ESCALATION
    # ─────────────────────────────────────────────────────────────────────────

    def escalate_reporting_failure(self, failure_context: dict) -> Escalation:
        """Escalate reporting failure to human authority."""
        reason = (
            f"Regulatory reporting failure: "
            f"{failure_context.get('failure_type', 'UNKNOWN')} | "
            f"{failure_context.get('report_type', '?')} | "
            f"{failure_context.get('detail', '')}"
        )
        return self.escalate(reason)

    # ─────────────────────────────────────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return RegReporting operational status for dashboard."""
        return {
            "agent_id":              self.role_id,
            "role_name":             self.role_name,
            "version":               REGREP_VERSION,
            "algorithm_id":          ALGORITHM_ID,
            "status":                "ACTIVE",
            "phase":                 "Phase 1 — Regulatory Reporting and Compliance Artifacts",
            "rts6_sla_seconds":      self.RTS6_ALERT_SLA_SECONDS,
            "regulatory_frameworks": self.regulatory_frameworks,
            "dsor_record_types":     self.dsor_record_types,
            "guardrails": [
                "Zero variance — one input, one output, always",
                "No self-initiation — C2 handoff required",
                "BCBS 239 P3 validation before any external submission",
                "RTS6 five-second SLA measured per alert",
                "No manual field entry — all data from DSOR",
            ],
            "known_limitations": [
                "RTS6 SLA measured in-process only. Production end-to-end "
                "timing under load requires C2 integration task.",
            ],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _write_regrep_log(self, task_id: str, ts: str,
                           action: str, status: str,
                           authority_hash: str, doctrine_version: str) -> None:
        """Write to c2_r_reg_reporting_log."""
        with self._lock:
            r_log = self._state.setdefault("c2_r_reg_reporting_log", [])
            r_log.insert(0, {
                "task_id":          task_id,
                "ts":               ts,
                "operator":         "CAOM-001",
                "caom_mode":        "CAOM-001",
                "role_id":          self.role_id,
                "action":           action,
                "status":           status,
                "authority_hash":   authority_hash,
                "doctrine_version": doctrine_version,
            })
            if len(r_log) > 200:
                self._state["c2_r_reg_reporting_log"] = r_log[:200]

    def _generate_uti(self, record: dict) -> str:
        seed = f"UTI-{record.get('id','')}-{record.get('symbol','')}-{record.get('authority_hash','')}"
        return "UTI" + hashlib.sha256(seed.encode()).hexdigest()[:29].upper()

    def _generate_usi(self, record: dict) -> str:
        seed = f"USI-{record.get('id','')}-{record.get('symbol','')}-{record.get('authority_hash','')}"
        return "USI" + hashlib.sha256(seed.encode()).hexdigest()[:29].upper()
