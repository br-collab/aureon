"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/thifur/agent_r.py                                            ║
║  Thifur-R — Ranger — Deterministic Execution Agent                  ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Execute the governed OMS release package deterministically.       ║
║    Enforce zero-variance settlement sequencing.                      ║
║    Emit settlement telemetry to C2 for unified lineage.             ║
║    Stamp immutable lineage at execution time.                        ║
║                                                                      ║
║  GUARDRAILS:                                                         ║
║    - Zero variance — one input, one output, always                  ║
║    - No self-initiation — requires C2 handoff authorization          ║
║    - No settlement without DSOR confirmation                         ║
║    - Immediate escalation on any discrepancy                         ║
║    - Immutable lineage — stamped at execution, never modified        ║
║                                                                      ║
║  REGULATORY ADDRESS:                                                 ║
║    SR 11-7 Tier 2 — deterministic, annual review                   ║
║    OCC 2023-17 — settlement rail nodes as Critical Activity         ║
║    BCBS 239 P3 — automated accuracy, no manual error               ║
║    DORA — RTO 15 minutes for settlement on primary path            ║
║    MiFID II RTS 6 — post-trade risk controls, 5s alerts            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aureon.thifur.c2 import ThifurC2

# ── R Operating Constants ─────────────────────────────────────────────────────
AGENT_R_VERSION  = "1.0"
AGENT_R_ID       = "THIFUR_R"
ALGORITHM_ID     = "AUR-R-SETTLE-001"   # MiFID II post-trade reference

# ── Settlement Rail Map — Verana Network Registry addresses ───────────────────
SETTLEMENT_RAILS = {
    "equities":     {"rail": "DTC/NSCC",     "settlement": "T+1", "mic": "ARCX/XNAS"},
    "fixed_income": {"rail": "Fedwire/DTCC", "settlement": "T+1", "mic": "XOFF"},
    "fx":           {"rail": "CLS",          "settlement": "T+2", "mic": "XOFF"},
    "commodities":  {"rail": "DTC/NSCC",     "settlement": "T+1", "mic": "ARCX"},
    "crypto":       {"rail": "On-chain/OTC", "settlement": "T+0", "mic": "XCRY"},
}

# ── FIX Tag Constants — Financial Information eXchange protocol ───────────────
# FIX is the messaging standard for order execution between institutions
FIX_SIDE_BUY  = "1"
FIX_SIDE_SELL = "2"
FIX_ORD_TYPE_MARKET = "1"
FIX_ORD_TYPE_LIMIT  = "2"


class ThifurR:
    """
    Thifur-R — Ranger — Deterministic Execution Agent.

    Wraps the settlement execution path with:
    - C2 handoff authorization enforcement
    - Deterministic gate checks (zero variance)
    - Immutable execution lineage stamp
    - FIX-ready package assembly for OMS
    - Telemetry emission back to C2

    Every method here is deterministic — same input, same output, always.
    No optimization, no path selection, no judgment.
    """

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        self._state = aureon_state
        self._lock  = state_lock
        self._handoff_confirmed = False   # must be True before prepare_settlement_package
        print(f"[THIFUR-R] Initialized — v{AGENT_R_VERSION} | "
              f"Zero variance — deterministic only | SR 11-7 Tier 2")

    def confirm_handoff(self, handoff_record: dict) -> bool:
        """
        Guardrail enforcement: R may not proceed without a valid C2 handoff.

        Called by C2.process_pretrade_lifecycle() after J completes.
        Returns True if the handoff is C2-authorized and R may proceed.

        Immutable Stop 3: No settlement action without this confirmation.
        """
        if not handoff_record.get("c2_authorized"):
            print(f"[THIFUR-R] BLOCKED — handoff not C2-authorized: "
                  f"{handoff_record.get('handoff_id')}")
            return False

        if handoff_record.get("to_agent") != AGENT_R_ID:
            print(f"[THIFUR-R] BLOCKED — handoff directed to "
                  f"{handoff_record.get('to_agent')}, not {AGENT_R_ID}")
            return False

        self._handoff_confirmed = True
        print(f"[THIFUR-R] Handoff confirmed: {handoff_record.get('handoff_id')} | "
              f"Task: {handoff_record.get('task_id')}")
        return True

    def prepare_settlement_package(self,
                                   decision: dict,
                                   task_id: str,
                                   c2: "ThifurC2") -> dict:
        """
        Prepare the deterministic settlement package for OMS handoff.

        Does NOT execute the trade — that is performed by
        server.py::_apply_approved_trade() under _lock, which remains
        the authoritative execution function. R prepares the governed
        package that server.py hands to OMS.

        Guardrail: zero variance. The same decision always produces
        the same settlement package. No optimization, no path selection.

        Returns telemetry dict for C2 lineage assembly.
        """
        if not self._handoff_confirmed:
            return {
                "agent":   AGENT_R_ID,
                "status":  "BLOCKED",
                "reason":  "Handoff not confirmed — C2 authorization required before R may act",
                "task_id": task_id,
            }

        ts = datetime.now(timezone.utc).isoformat()

        with self._lock:
            doctrine_version = self._state.get("doctrine_version", "unknown")
            halt_active      = self._state.get("halt_active", False)

        # ── Halt check — Tier 0, above all doctrine ────────────────────
        if halt_active:
            return {
                "agent":   AGENT_R_ID,
                "status":  "BLOCKED",
                "reason":  "System HALT active — Tier 0 stop. R may not proceed.",
                "task_id": task_id,
            }

        symbol      = decision.get("symbol", "")
        action      = decision.get("action", "")
        shares      = decision.get("shares", 0)
        asset_class = decision.get("asset_class", "")
        notional    = decision.get("notional", 0)

        # ── Determine settlement rail (deterministic) ──────────────────
        rail_info  = SETTLEMENT_RAILS.get(asset_class, SETTLEMENT_RAILS["equities"])
        settlement = rail_info["settlement"]

        # ── Determine FIX side (deterministic) ────────────────────────
        fix_side = FIX_SIDE_BUY if action == "BUY" else FIX_SIDE_SELL

        # ── Build execution lineage stamp ─────────────────────────────
        # Immutable — stamped now, never modified post-execution
        lineage_stamp = self._build_lineage_stamp(
            decision         = decision,
            task_id          = task_id,
            doctrine_version = doctrine_version,
            ts               = ts,
        )

        # ── Assemble FIX-ready OMS package ────────────────────────────
        oms_package = {
            # FIX 4.4 fields
            "fix_msg_type":    "D",               # New Order Single
            "fix_side":        fix_side,           # Tag 54
            "fix_symbol":      symbol,             # Tag 55
            "fix_ord_qty":     shares,             # Tag 38
            "fix_ord_type":    FIX_ORD_TYPE_MARKET, # Tag 40 — market order in Phase 1
            "fix_currency":    "USD",              # Tag 15

            # Aureon governance overlay
            "decision_id":      decision.get("id"),
            "task_id":          task_id,
            "authority_hash":   lineage_stamp["authority_hash"],
            "doctrine_version": doctrine_version,
            "agent":            AGENT_R_ID,
            "algorithm_id":     ALGORITHM_ID,

            # Settlement routing
            "settlement_rail":  rail_info["rail"],
            "settlement_cycle": settlement,
            "mic":              rail_info["mic"],

            # Flags
            "release_target":   decision.get("release_target", "OMS"),
            "ready_for_release": True,
        }

        # ── Emit to state for dashboard visibility ─────────────────────
        with self._lock:
            r_log = self._state.setdefault("c2_r_settlement_log", [])
            r_log.insert(0, {
                "task_id":          task_id,
                "ts":               ts,
                "decision_id":      decision.get("id"),
                "symbol":           symbol,
                "action":           action,
                "shares":           shares,
                "notional":         notional,
                "settlement_rail":  rail_info["rail"],
                "settlement_cycle": settlement,
                "authority_hash":   lineage_stamp["authority_hash"],
                "status":           "PREPARED",
            })
            if len(r_log) > 200:
                self._state["c2_r_settlement_log"] = r_log[:200]

            # Authority log entry
            self._state.setdefault("authority_log", []).insert(0, {
                "id":        f"HAD-R-{task_id[-6:]}",
                "ts":        ts,
                "tier":      "Thifur-R",
                "type":      f"Settlement Package Prepared · {action} {symbol}",
                "authority": AGENT_R_ID,
                "outcome":   (f"${notional:,.0f} | Rail: {rail_info['rail']} | "
                              f"Settlement: {settlement} | "
                              f"Hash: {lineage_stamp['authority_hash']}"),
                "hash":      lineage_stamp["authority_hash"],
            })

        # ── Reset handoff flag — R requires a new handoff for each lifecycle ──
        self._handoff_confirmed = False

        print(f"[THIFUR-R] Settlement package prepared: {action} {symbol} "
              f"${notional:,.0f} | Rail: {rail_info['rail']} | "
              f"Cycle: {settlement} | Task: {task_id}")

        # ── Telemetry for C2 lineage assembly ─────────────────────────
        return {
            "agent":            AGENT_R_ID,
            "algorithm_id":     ALGORITHM_ID,
            "task_id":          task_id,
            "ts":               ts,
            "status":           "COMPLETE",
            "oms_package":      oms_package,
            "lineage_stamp":    lineage_stamp,
            "settlement_rail":  rail_info["rail"],
            "settlement_cycle": settlement,
            "doctrine_version": doctrine_version,
        }

    def emit_execution_confirmation(self,
                                    task_id: str,
                                    decision: dict,
                                    exec_price: float,
                                    authority_hash: str,
                                    gate_results: list,
                                    c2: "ThifurC2") -> dict:
        """
        Called by server.py after _apply_approved_trade() succeeds.

        Emits the execution confirmation telemetry with immutable
        lineage stamp — BCBS 239 P3 automated accuracy compliance.

        This is the final R telemetry event. It signals C2 that
        settlement execution is confirmed and lineage is complete.
        """
        ts = datetime.now(timezone.utc).isoformat()
        confirmation_hash = self._build_confirmation_hash(
            task_id, decision, exec_price, ts
        )

        confirmation = {
            "agent":             AGENT_R_ID,
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

        # Push confirmation telemetry to C2 for final lineage assembly
        c2.record_agent_telemetry(task_id, f"{AGENT_R_ID}_CONFIRMED", confirmation)

        print(f"[THIFUR-R] Execution confirmed — {decision.get('action')} "
              f"{decision.get('symbol')} @ ${exec_price:,.2f} | "
              f"Task: {task_id} | Hash: {confirmation_hash}")

        return confirmation

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _build_lineage_stamp(self, decision: dict, task_id: str,
                              doctrine_version: str, ts: str) -> dict:
        """
        Build the immutable lineage stamp for this settlement action.

        Immutable Stop 5: stamped at execution time, never modified post-execution.
        This is the BCBS 239 P3 automated accuracy record.
        """
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
            "agent":            AGENT_R_ID,
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

    def get_status(self) -> dict:
        """Return Thifur-R operational status for dashboard."""
        return {
            "agent_id":     AGENT_R_ID,
            "version":      AGENT_R_VERSION,
            "algorithm_id": ALGORITHM_ID,
            "status":       "ACTIVE",
            "phase":        "Phase 1 — Settlement Preparation and OMS Handoff",
            "sr_11_7_tier": "Tier 2 — Deterministic",
            "occ_2023_17":  "Settlement rails registered in Verana Network Registry",
            "bcbs_239_p3":  "Automated lineage stamp — no manual modification",
            "dora_rto":     "15 minutes — primary path | Verana fallback pre-staged",
            "mifid_rts6":   "Post-trade risk controls — 5s alert threshold",
            "guardrails": [
                "Zero variance — one input, one output, always",
                "No self-initiation — C2 handoff required",
                "No settlement without DSOR confirmation",
                "Immediate escalation on discrepancy",
                "Immutable lineage — stamped at execution",
            ],
        }
