"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/ranger/settlement_ops.py                              ║
║  SettlementOps — AUR-R-SETTLEMENT-001                                ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Prepare FIX 4.4 settlement packages for OMS handoff.              ║
║    Route to clearing rail deterministically by asset class.          ║
║    Stamp immutable lineage at execution time.                        ║
║    Write settlement-specific telemetry to c2_r_settlement_log.       ║
║                                                                      ║
║  REGULATORY ADDRESS:                                                 ║
║    OCC 2023-17 — settlement rail nodes as Critical Activity          ║
║    BCBS 239 P3 — automated accuracy, no manual error                ║
║    DORA — RTO 15 minutes for settlement on primary path             ║
║    MiFID II RTS 6 — post-trade risk controls, 5s alerts             ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aureon.agents.ranger._base import RangerConcreteBase

if TYPE_CHECKING:
    from aureon.agents.c2.coordinator import ThifurC2

# ── Settlement Rail Map — Verana Network Registry addresses ───────────────────
SETTLEMENT_RAILS = {
    "equities":     {"rail": "DTC/NSCC",     "settlement": "T+1", "mic": "ARCX/XNAS"},
    "fixed_income": {"rail": "Fedwire/DTCC", "settlement": "T+1", "mic": "XOFF"},
    "fx":           {"rail": "CLS",          "settlement": "T+2", "mic": "XOFF"},
    "commodities":  {"rail": "DTC/NSCC",     "settlement": "T+1", "mic": "ARCX"},
    "crypto":       {"rail": "On-chain/OTC", "settlement": "T+0", "mic": "XCRY"},
}

# ── FIX Tag Constants — Financial Information eXchange protocol ───────────────
FIX_SIDE_BUY  = "1"
FIX_SIDE_SELL = "2"
FIX_ORD_TYPE_MARKET = "1"
FIX_ORD_TYPE_LIMIT  = "2"

AGENT_R_VERSION = "1.0"
ALGORITHM_ID    = "AUR-R-SETTLE-001"


class SettlementOps(RangerConcreteBase):
    """AUR-R-SETTLEMENT-001 — Settlement Operations Analyst.

    FIX 4.4 package assembly, settlement rail routing (DTC/NSCC,
    Fedwire, CLS, on-chain), c2_r_settlement_log writes,
    BCBS 239 P3 payload.
    """

    role_id   = "AUR-R-SETTLEMENT-001"
    role_name = "Settlement Operations Analyst"

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        print(f"[SETTLEMENT-OPS] Initialized — v{AGENT_R_VERSION} | "
              f"Zero variance — deterministic only | SR 11-7 Tier 2")

    # ─────────────────────────────────────────────────────────────────────────
    # ROLE-SPECIFIC PACKAGE ASSEMBLY
    # ─────────────────────────────────────────────────────────────────────────

    def prepare_execution_package(self,
                                  decision: dict,
                                  task_id: str,
                                  c2: "ThifurC2") -> dict:
        """Prepare the deterministic settlement package for OMS handoff.

        Does NOT execute the trade — that is performed by
        server.py::_apply_approved_trade() under _lock, which remains
        the authoritative execution function. This prepares the governed
        package that server.py hands to OMS.
        """
        blocked = self._check_handoff_and_halt(task_id)
        if blocked:
            return blocked

        ts = datetime.now(timezone.utc).isoformat()

        with self._lock:
            doctrine_version = self._state.get("doctrine_version", "unknown")

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
            "agent":            self.role_id,
            "algorithm_id":     ALGORITHM_ID,

            # Settlement routing
            "settlement_rail":  rail_info["rail"],
            "settlement_cycle": settlement,
            "mic":              rail_info["mic"],

            # Flags
            "release_target":   decision.get("release_target", "OMS"),
            "ready_for_release": True,
        }

        # ── Emit to c2_r_settlement_log for dashboard visibility ──────
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

        # ── Authority log entry ───────────────────────────────────────
        self._write_authority_log(
            task_id        = task_id,
            ts             = ts,
            event_type     = f"Settlement Package Prepared · {action} {symbol}",
            outcome        = (f"${notional:,.0f} | Rail: {rail_info['rail']} | "
                              f"Settlement: {settlement} | "
                              f"Hash: {lineage_stamp['authority_hash']}"),
            authority_hash = lineage_stamp["authority_hash"],
        )

        # ── Reset handoff flag — requires new handoff for each lifecycle
        self._handoff_confirmed = False

        print(f"[SETTLEMENT-OPS] Package prepared: {action} {symbol} "
              f"${notional:,.0f} | Rail: {rail_info['rail']} | "
              f"Cycle: {settlement} | Task: {task_id}")

        # ── Telemetry for C2 lineage assembly ─────────────────────────
        return {
            "agent":            self.role_id,
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

    # ─────────────────────────────────────────────────────────────────────────
    # BACKWARD-COMPAT ALIAS
    # ─────────────────────────────────────────────────────────────────────────

    def prepare_settlement_package(self,
                                   decision: dict,
                                   task_id: str,
                                   c2: "ThifurC2") -> dict:
        """Legacy alias — delegates to prepare_execution_package."""
        return self.prepare_execution_package(decision, task_id, c2)

    # ─────────────────────────────────────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return Settlement Ops operational status for dashboard."""
        return {
            "agent_id":     self.role_id,
            "role_name":    self.role_name,
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
