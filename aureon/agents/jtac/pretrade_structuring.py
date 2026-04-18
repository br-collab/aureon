"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/jtac/pretrade_structuring.py                          ║
║  Thifur-J — JTAC — Bounded Autonomy Agent                           ║
║                                                                      ║
║  MANDATE (Phase 1):                                                  ║
║    Structure the governed pre-trade decision record.                 ║
║    Validate policy and mandate compliance.                           ║
║    Route approval lineage.                                           ║
║    Govern tokenized asset lifecycle state (declared, Phase 2+).     ║
║    Emit lifecycle telemetry to C2.                                   ║
║                                                                      ║
║  GUARDRAILS:                                                         ║
║    - Approved paths only — never generates a new routing path        ║
║    - Doctrine over code — smart contract logic never overrides       ║
║    - No release without approval lineage                             ║
║    - Eligibility before routing                                      ║
║    - Jurisdictional attribution before execution                     ║
║                                                                      ║
║  REGULATORY ADDRESS:                                                 ║
║    SR 11-7 Tier 1 — independent validation before deployment        ║
║    EU AI Act — high-risk, conformity assessment required            ║
║    MiFID II RTS 6 — AUR-J-TRADE-001 algorithm inventory            ║
║    DORA — ICT third-party registry for all lifecycle nodes          ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aureon.agents.base import JTACAgent, Intent, Advisory, Tasking, Result

if TYPE_CHECKING:
    from aureon.agents.c2.coordinator import ThifurC2

# ── J Operating Constants ─────────────────────────────────────────────────────
AGENT_J_VERSION   = "1.0"
AGENT_J_ID        = "THIFUR_J"
ALGORITHM_ID      = "AUR-J-TRADE-001"   # MiFID II RTS 6 Algorithm Inventory ID

# ── Approved Routing Paths — JTAC selects among these, never generates new ────
# Phase 1: Equities electronic execution to OMS
# Phase 2+: Tokenized asset lifecycle, cross-border flows
APPROVED_RELEASE_TARGETS = {"OMS", "EMS"}
APPROVED_ASSET_CLASSES   = {"equities", "fixed_income", "fx", "commodities", "crypto"}

# ── Mandate Constraints — Mentat L1 doctrine-defined ──────────────────────────
MANDATE_LIMITS = {
    "max_single_position_pct": 0.15,   # 15% hard stop — position concentration
    "max_crypto_pct":          0.10,   # 10% crypto allocation limit
    "min_cash_floor_pct":      0.03,   # 3% operating cash floor — never breach
    "max_notional_tier1":  2_000_000,  # ≥$2M requires Tier 1 PM sign-off
    "max_notional_tier2":  5_000_000,  # ≥$5M requires Tier 2 approval
    "ofac_blocked_isins": {            # OFAC SDN hard stops
        "PDVSA_BOND_2027",
        "IRAN_BOND_2024",
        "RUSAL_CONV_2025",
        "NORD_STREAM_2",
    },
}

# ── Gate Definitions — MiFID II RTS 6 pre-trade risk controls ─────────────────
GATES = [
    ("OFAC_SDN_CHECK",       "Kaladan L2",    "OFAC sanctions screening — hard stop"),
    ("MANDATE_ELIGIBILITY",  "Thifur-J",      "Mandate and investment policy compliance"),
    ("POSITION_CONCENTRATION","Thifur-J",     "Single-position concentration limit"),
    ("CASH_FLOOR",           "Mentat L1",     "Operating cash floor preservation"),
    ("ASSET_CLASS_LIMIT",    "Thifur-J",      "Asset class allocation limit"),
    ("NOTIONAL_AUTHORITY",   "Thifur-J",      "Notional-based approval tier routing"),
    ("APPROVAL_LINEAGE",     "Kaladan L2",    "Human approval lineage completeness"),
    ("RELEASE_TARGET",       "Thifur-J",      "Approved release target validation"),
]


class ThifurJ(JTACAgent):
    """
    Thifur-J — JTAC — Bounded Autonomy Agent.

    Phase 1 scope: pre-trade structuring, policy validation, approval routing,
    mandate compliance, and settlement package preparation for C2 handoff to R.

    JTAC principle: selects among pre-approved paths, never generates new ones.
    """

    role_id = "AUR-J-TRADE-001"

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        print(f"[THIFUR-J] Initialized — v{AGENT_J_VERSION} | "
              f"Algorithm ID: {ALGORITHM_ID} | SR 11-7 Tier 1 declared")

    def structure_pretrade_record(self,
                                  decision: dict,
                                  task_id: str,
                                  c2: "ThifurC2") -> dict:
        """
        Primary Phase 1 function.

        Takes a pending decision that has passed human approval and:
        1. Runs all pre-trade gates in sequence
        2. Builds the governed pre-trade decision record
        3. Validates approval lineage completeness
        4. Returns telemetry for C2 lineage assembly

        Guardrail: approved paths only — J selects OMS or EMS, never invents
        a third path. Doctrine over code — any smart contract flag suspends
        execution and escalates.

        Returns a result dict with status PASS | WARN | BLOCKED.
        BLOCKED means the lifecycle must not proceed to R.
        """
        ts = datetime.now(timezone.utc).isoformat()

        with self._lock:
            portfolio_value = self._state.get("portfolio_value", 50_000_000)
            cash            = self._state.get("cash", 0)
            positions       = list(self._state.get("positions", []))
            prices          = dict(self._state.get("prices", {}))
            doctrine_version = self._state.get("doctrine_version", "unknown")

        # ── Run all pre-trade gates ────────────────────────────────────
        gate_results = []
        overall_status = "PASS"
        block_reason   = None

        for gate_id, layer, description in GATES:
            gate_result = self._run_gate(
                gate_id         = gate_id,
                layer           = layer,
                description     = description,
                decision        = decision,
                portfolio_value = portfolio_value,
                cash            = cash,
                positions       = positions,
                prices          = prices,
            )
            gate_results.append(gate_result)

            if gate_result["status"] == "FAIL":
                overall_status = "BLOCKED"
                block_reason   = f"{gate_id}: {gate_result['detail']}"
                break   # Guardrail: first FAIL stops the sequence
            elif gate_result["status"] == "WARN" and overall_status == "PASS":
                overall_status = "WARN"

        # ── Doctrine override check — smart contract conflict ──────────
        if decision.get("has_smart_contract"):
            gate_results.append({
                "gate":   "SMART_CONTRACT_OVERRIDE",
                "layer":  "Thifur-J",
                "status": "BLOCKED",
                "detail": ("Smart contract flag detected. Doctrine over code — "
                           "Thifur-J suspends and escalates to C2. "
                           "Mentat L1 authority required before proceeding."),
            })
            overall_status = "BLOCKED"
            block_reason   = "Smart contract override — Mentat doctrine authority required"

        # ── Determine approval tier required ──────────────────────────
        notional       = decision.get("notional", 0)
        approval_tier  = self._resolve_approval_tier(notional, decision)
        current_approvals = decision.get("current_approvals", [])
        lineage_complete  = self._validate_approval_lineage(
            current_approvals, approval_tier, decision
        )

        if not lineage_complete and overall_status != "BLOCKED":
            overall_status = "BLOCKED"
            block_reason   = (f"Approval lineage incomplete for tier {approval_tier}. "
                              f"Required: {approval_tier} | "
                              f"Current: {current_approvals}")

        # ── Determine approved release target ────────────────────────
        release_target = decision.get("release_target", "OMS")
        if release_target not in APPROVED_RELEASE_TARGETS:
            overall_status = "BLOCKED"
            block_reason   = (f"Release target '{release_target}' not in approved set "
                              f"{APPROVED_RELEASE_TARGETS}. "
                              "Guardrail: approved paths only.")

        # ── Build the governed pre-trade record ───────────────────────
        record_hash = self._build_record_hash(decision, gate_results, ts)

        pretrade_record = {
            "record_id":        f"PTR-{record_hash[:10]}",
            "task_id":          task_id,
            "created_ts":       ts,
            "agent":            AGENT_J_ID,
            "algorithm_id":     ALGORITHM_ID,
            "doctrine_version": doctrine_version,

            # ── Decision Identity ──────────────────────────────────
            "decision_id":   decision.get("id"),
            "action":        decision.get("action"),
            "symbol":        decision.get("symbol"),
            "asset_class":   decision.get("asset_class"),
            "shares":        decision.get("shares"),
            "notional":      notional,
            "signal_type":   decision.get("signal_type"),
            "rationale":     decision.get("rationale"),

            # ── Governance Block ───────────────────────────────────
            "gate_results":        gate_results,
            "overall_gate_status": overall_status,
            "approval_tier":       approval_tier,
            "approval_lineage":    current_approvals,
            "lineage_complete":    lineage_complete,
            "release_target":      release_target,

            # ── Risk State at Structuring ──────────────────────────
            "portfolio_value_at_structure": portfolio_value,
            "cash_at_structure":            cash,
            "cash_floor_required":          portfolio_value * MANDATE_LIMITS["min_cash_floor_pct"],

            # ── Phase 2+ Fields (declared, not active) ─────────────
            "is_tokenized":          decision.get("is_tokenized", False),
            "has_smart_contract":    decision.get("has_smart_contract", False),
            "cross_border":          decision.get("cross_border", False),
            "tokenized_lifecycle_state": None,   # Phase 2 activation

            # ── Result ─────────────────────────────────────────────
            "status":       overall_status,   # PASS | WARN | BLOCKED
            "block_reason": block_reason,
            "record_hash":  record_hash,
        }

        # ── Emit to authority log ─────────────────────────────────────
        self._emit_authority_log(pretrade_record)

        status_label = ("✓" if overall_status == "PASS"
                        else "⚠" if overall_status == "WARN"
                        else "✗")

        print(f"[THIFUR-J] Pre-trade record: {status_label} {overall_status} | "
              f"{decision.get('action')} {decision.get('symbol')} "
              f"${notional:,.0f} | "
              f"Gates: {sum(1 for g in gate_results if g['status']=='PASS')}/"
              f"{len(gate_results)} PASS | "
              f"Task: {task_id}")

        return pretrade_record

    # ─────────────────────────────────────────────────────────────────────────
    # GATE IMPLEMENTATIONS
    # ─────────────────────────────────────────────────────────────────────────

    def _run_gate(self, gate_id: str, layer: str, description: str,
                  decision: dict, portfolio_value: float, cash: float,
                  positions: list, prices: dict) -> dict:
        """Dispatch to the appropriate gate check. Returns gate result dict."""
        try:
            if gate_id == "OFAC_SDN_CHECK":
                return self._gate_ofac(gate_id, layer, description, decision)

            elif gate_id == "MANDATE_ELIGIBILITY":
                return self._gate_mandate(gate_id, layer, description, decision)

            elif gate_id == "POSITION_CONCENTRATION":
                return self._gate_concentration(gate_id, layer, description,
                                                 decision, portfolio_value, prices, positions)

            elif gate_id == "CASH_FLOOR":
                return self._gate_cash_floor(gate_id, layer, description,
                                              decision, portfolio_value, cash)

            elif gate_id == "ASSET_CLASS_LIMIT":
                return self._gate_asset_class_limit(gate_id, layer, description,
                                                     decision, portfolio_value, positions, prices)

            elif gate_id == "NOTIONAL_AUTHORITY":
                return self._gate_notional_authority(gate_id, layer, description, decision)

            elif gate_id == "APPROVAL_LINEAGE":
                return self._gate_approval_lineage_check(gate_id, layer, description, decision)

            elif gate_id == "RELEASE_TARGET":
                return self._gate_release_target(gate_id, layer, description, decision)

            else:
                return self._gate_pass(gate_id, layer, description)

        except Exception as exc:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "WARN",
                "detail": f"Gate evaluation error — {exc}. Flagged for review.",
            }

    def _gate_ofac(self, gate_id, layer, description, decision) -> dict:
        symbol = decision.get("symbol", "")
        SYMBOL_TO_ISIN = {
            "PDVSA": "PDVSA_BOND_2027",
            "IRAN":  "IRAN_BOND_2024",
            "RUSAL": "RUSAL_CONV_2025",
            "NORSTR": "NORD_STREAM_2",
        }
        isin = SYMBOL_TO_ISIN.get(symbol)
        if isin and isin in MANDATE_LIMITS["ofac_blocked_isins"]:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "FAIL",
                "detail": f"{symbol} maps to sanctioned ISIN {isin} — OFAC SDN hard stop",
            }
        return self._gate_pass(gate_id, layer, description)

    def _gate_mandate(self, gate_id, layer, description, decision) -> dict:
        asset_class = decision.get("asset_class", "")
        if asset_class not in APPROVED_ASSET_CLASSES:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "FAIL",
                "detail": f"Asset class '{asset_class}' not in mandate-approved set",
            }
        return self._gate_pass(gate_id, layer, description)

    def _gate_concentration(self, gate_id, layer, description,
                             decision, portfolio_value, prices, positions) -> dict:
        if decision.get("action") != "BUY":
            return self._gate_pass(gate_id, layer, description)
        notional = decision.get("notional", 0)
        conc_pct = (notional / portfolio_value) if portfolio_value > 0 else 0
        hard_stop = MANDATE_LIMITS["max_single_position_pct"]
        if conc_pct >= hard_stop:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "FAIL",
                "detail": (f"Position concentration {conc_pct*100:.1f}% >= "
                           f"hard stop {hard_stop*100:.0f}%"),
            }
        if conc_pct >= hard_stop * 0.75:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "WARN",
                "detail": (f"Position concentration {conc_pct*100:.1f}% — "
                           f"approaching {hard_stop*100:.0f}% limit"),
            }
        return {
            "gate":   gate_id,
            "layer":  layer,
            "status": "PASS",
            "detail": f"Concentration {conc_pct*100:.1f}% within mandate limits",
        }

    def _gate_cash_floor(self, gate_id, layer, description,
                          decision, portfolio_value, cash) -> dict:
        if decision.get("action") != "BUY":
            return self._gate_pass(gate_id, layer, description)
        notional    = decision.get("notional", 0)
        floor       = portfolio_value * MANDATE_LIMITS["min_cash_floor_pct"]
        cash_after  = cash - notional
        if cash_after < floor:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "FAIL",
                "detail": (f"Trade would breach cash floor. "
                           f"Cash after: ${cash_after:,.0f} < "
                           f"Floor: ${floor:,.0f}"),
            }
        return {
            "gate":   gate_id,
            "layer":  layer,
            "status": "PASS",
            "detail": f"Cash floor preserved — ${cash_after:,.0f} after trade",
        }

    def _gate_asset_class_limit(self, gate_id, layer, description,
                                 decision, portfolio_value, positions, prices) -> dict:
        asset_class = decision.get("asset_class", "")
        if asset_class != "crypto" or decision.get("action") != "BUY":
            return self._gate_pass(gate_id, layer, description)

        current_crypto = sum(
            p["shares"] * prices.get(p["symbol"], p.get("cost", 0))
            for p in positions if p.get("asset_class") == "crypto"
        )
        notional    = decision.get("notional", 0)
        new_crypto  = current_crypto + notional
        crypto_pct  = (new_crypto / portfolio_value) if portfolio_value > 0 else 0
        limit       = MANDATE_LIMITS["max_crypto_pct"]

        if crypto_pct > limit:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "FAIL",
                "detail": (f"Crypto allocation {crypto_pct*100:.1f}% > "
                           f"mandate limit {limit*100:.0f}%"),
            }
        if crypto_pct > limit * 0.85:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "WARN",
                "detail": (f"Crypto allocation {crypto_pct*100:.1f}% — "
                           f"approaching {limit*100:.0f}% limit"),
            }
        return self._gate_pass(gate_id, layer, description)

    def _gate_notional_authority(self, gate_id, layer, description, decision) -> dict:
        notional      = decision.get("notional", 0)
        tier1_limit   = MANDATE_LIMITS["max_notional_tier1"]
        tier2_limit   = MANDATE_LIMITS["max_notional_tier2"]
        approvals     = decision.get("current_approvals", [])
        has_pm        = decision.get("pm_signoff_required", False) or notional >= tier1_limit
        has_risk_ex   = decision.get("risk_exception", False)

        if notional >= tier2_limit:
            if "RISK_COMMITTEE" not in approvals and "TIER_2" not in approvals:
                return {
                    "gate":   gate_id,
                    "layer":  layer,
                    "status": "WARN",
                    "detail": (f"Notional ${notional:,.0f} >= Tier 2 threshold ${tier2_limit:,.0f}. "
                               f"Risk Committee sign-off flagged for review."),
                }
        elif notional >= tier1_limit:
            if has_pm and "PM" not in approvals and "PORTFOLIO_MANAGER" not in approvals:
                return {
                    "gate":   gate_id,
                    "layer":  layer,
                    "status": "WARN",
                    "detail": (f"Notional ${notional:,.0f} >= Tier 1 threshold ${tier1_limit:,.0f}. "
                               f"PM sign-off flagged."),
                }

        return {
            "gate":   gate_id,
            "layer":  layer,
            "status": "PASS",
            "detail": f"Notional authority ${notional:,.0f} within TRADER approval scope",
        }

    def _gate_approval_lineage_check(self, gate_id, layer, description, decision) -> dict:
        approvals = decision.get("current_approvals", [])
        required  = decision.get("required_approvals", ["TRADER"])
        if not approvals:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "FAIL",
                "detail": "No approvals recorded. Human authority lineage required before release.",
            }
        return {
            "gate":   gate_id,
            "layer":  layer,
            "status": "PASS",
            "detail": f"Approval lineage present: {approvals}",
        }

    def _gate_release_target(self, gate_id, layer, description, decision) -> dict:
        target = decision.get("release_target", "OMS")
        if target in APPROVED_RELEASE_TARGETS:
            return {
                "gate":   gate_id,
                "layer":  layer,
                "status": "PASS",
                "detail": f"Release target '{target}' in approved set",
            }
        return {
            "gate":   gate_id,
            "layer":  layer,
            "status": "FAIL",
            "detail": (f"Release target '{target}' not in approved set "
                       f"{APPROVED_RELEASE_TARGETS}"),
        }

    def _gate_pass(self, gate_id: str, layer: str, description: str) -> dict:
        return {
            "gate":   gate_id,
            "layer":  layer,
            "status": "PASS",
            "detail": description,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # APPROVAL TIER RESOLUTION
    # ─────────────────────────────────────────────────────────────────────────

    def _resolve_approval_tier(self, notional: float, decision: dict) -> str:
        """
        Determine which human authority tier is required for this decision.
        Maps to the Aureon Human Authority Doctrine tier structure.
        """
        if notional >= MANDATE_LIMITS["max_notional_tier2"]:
            return "TIER_2"
        if (notional >= MANDATE_LIMITS["max_notional_tier1"]
                or decision.get("pm_signoff_required")
                or decision.get("mandate_sensitive")
                or decision.get("policy_exception")):
            return "TIER_1"
        if decision.get("control_exception") or decision.get("risk_exception"):
            return "TIER_1_RISK"
        return "TRADER"

    def _validate_approval_lineage(self,
                                    current_approvals: list,
                                    approval_tier: str,
                                    decision: dict) -> bool:
        """
        Validate that the approval lineage satisfies the required tier.
        Returns True if complete, False if incomplete.
        """
        if not current_approvals:
            return False
        if approval_tier == "TRADER":
            return bool(current_approvals)
        if approval_tier in ("TIER_1", "TIER_1_RISK"):
            return any(a in current_approvals
                       for a in ["PM", "PORTFOLIO_MANAGER", "TIER_1", "RISK_MANAGER"])
        if approval_tier == "TIER_2":
            return any(a in current_approvals
                       for a in ["RISK_COMMITTEE", "TIER_2", "CRO"])
        return bool(current_approvals)

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _build_record_hash(self, decision: dict,
                            gate_results: list, ts: str) -> str:
        seed = (
            f"{decision.get('id')}"
            f"{decision.get('symbol')}"
            f"{decision.get('action')}"
            f"{decision.get('notional')}"
            f"{len(gate_results)}"
            f"{ts}"
        )
        return hashlib.sha256(seed.encode()).hexdigest()[:16].upper()

    def _emit_authority_log(self, record: dict) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "id":        f"HAD-J-{record['record_id']}",
            "ts":        ts,
            "tier":      "Thifur-J",
            "type":      f"Pre-Trade Structuring · {record['overall_gate_status']}",
            "authority": AGENT_J_ID,
            "outcome":   (f"{record['action']} {record['symbol']} "
                          f"${record['notional']:,.0f} | "
                          f"Gates: {record['overall_gate_status']} | "
                          f"Release: {record['release_target']}"),
            "hash":      record["record_hash"],
        }
        with self._lock:
            self._state.setdefault("authority_log", []).insert(0, entry)

    def advise(self, intent: Intent) -> Advisory:
        """Produce pre-trade governance advisory for an operator intent."""
        return Advisory(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            summary=f"JTAC pre-trade assessment for {intent.payload.get('symbol', '?')}",
            recommendation={"gates": "pending"},
            requires_approval=True,
        )

    def execute(self, tasking: Tasking) -> Result:
        """Execute pre-trade structuring via structure_pretrade_record."""
        return Result(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            outcome="DELEGATED",
            dsor_record_id=tasking.c2_tasking_id,
        )

    def get_status(self) -> dict:
        """Return Thifur-J operational status for dashboard."""
        return {
            "agent_id":      AGENT_J_ID,
            "version":       AGENT_J_VERSION,
            "algorithm_id":  ALGORITHM_ID,
            "status":        "ACTIVE",
            "phase":         "Phase 1 — Pre-Trade Structuring",
            "gates_defined": len(GATES),
            "sr_11_7_tier":  "Tier 1",
            "eu_ai_act":     "High-risk — declared, conformity assessment required at Phase 2",
            "mifid_rts6":    f"Algorithm inventory: {ALGORITHM_ID}",
            "guardrails":    [
                "Approved paths only",
                "Doctrine over code",
                "No release without approval lineage",
                "Eligibility before routing",
                "Jurisdictional attribution before execution",
            ],
        }
