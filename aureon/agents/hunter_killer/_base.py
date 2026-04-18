"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/agents/hunter_killer/_base.py                                ║
║  Thifur-H — Hunter-Killer — Adaptive Intelligence Agent             ║
║                                                                      ║
║  ACTIVATION STATUS: DECLARED — NOT ACTIVATED                        ║
║                                                                      ║
║  This module is a declared capability shell.                         ║
║  No function in this file executes a market action.                  ║
║  No function in this file connects to a live data feed.              ║
║  No function in this file generates an executable signal.            ║
║                                                                      ║
║  Activation requires:                                                ║
║    1. SR 11-7 Tier 1 independent model validation — completed        ║
║       and signed by MRM committee before any domain activation       ║
║    2. EU AI Act conformity assessment — completed before EU          ║
║       deployment                                                     ║
║    3. MiFID II RTS 6 algorithm inventory registration —              ║
║       AUR-H-SIC-001, AUR-H-PRED-001 registered before activation    ║
║    4. Tier 2 human authority sign-off on each domain activation      ║
║    5. C2 sequencing protocol confirmed operational                   ║
║                                                                      ║
║  MANDATE (when activated):                                           ║
║    Domain 1 — SIC Pricing Mismatch Detection                        ║
║    Domain 2 — Predictive Markets Integration                         ║
║    Domain 3 — Execution Strategy Optimization                        ║
║                                                                      ║
║  GUARDRAILS (immutable regardless of activation status):             ║
║    - Objective function supremacy — never redefines own objective    ║
║    - Doctrine over optimization — no efficient but non-compliant     ║
║      action executes                                                 ║
║    - Risk parameter hard stops — breach triggers auto-suspension     ║
║    - Emergency suspension — any Tier 1 authority, immediate          ║
║    - No activation without independent validation                    ║
║    - Explainability before execution — if it cannot be explained     ║
║      in human-readable terms before execution, it does not execute   ║
║                                                                      ║
║  REGULATORY ADDRESS:                                                 ║
║    SR 11-7 Tier 1 — adaptive optimization, material financial impact ║
║    MiFID II RTS 6 — kill switch, price collars, self-assessment     ║
║    EU AI Act — high-risk, conformity assessment, EU database         ║
║    DORA — TLPT (Threat-Led Penetration Testing) annual scope        ║
║    BCBS 239 P5 — real-time timeliness, continuous telemetry         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aureon.agents.base import HunterKillerAgent, NotActivatedError, Intent, Advisory

if TYPE_CHECKING:
    from aureon.agents.c2.coordinator import ThifurC2

# ── H Operating Constants ─────────────────────────────────────────────────────
AGENT_H_VERSION  = "0.1-shell"
AGENT_H_ID       = "THIFUR_H"
ACTIVATION_STATE = "DECLARED"   # DECLARED | VALIDATED | ACTIVE — never self-modify

# ── Algorithm Inventory — MiFID II RTS 6 ──────────────────────────────────────
# Registered before activation. Not active until Tier 2 approval.
ALGORITHM_REGISTRY = {
    "AUR-H-SIC-001": {
        "name":        "SIC Pricing Mismatch Detector",
        "domain":      "Domain 1 — SIC Spread Detection",
        "status":      "DECLARED",
        "description": (
            "Monitors the three-price spread between USD NAV of underlying "
            "US ETF, EUR/GBP NAV of UCITS wrapper on LSE, and MXN price on "
            "BMV SIC. Surfaces dislocations exceeding doctrine-defined "
            "thresholds accounting for FX conversion, Indeval settlement lag, "
            "and market-making spread. Advisory output only — no execution."
        ),
        "activation_requirements": [
            "SR 11-7 Tier 1 independent validation",
            "MiFID II RTS 6 algorithm inventory registration",
            "Tier 2 human authority sign-off",
            "C2 sequencing protocol confirmed",
            "Three live price feeds validated: Twelve Data (USD/EUR), "
            "BMV SIC feed (MXN), Indeval settlement calendar",
        ],
    },
    "AUR-H-PRED-001": {
        "name":        "Predictive Markets Timing Layer",
        "domain":      "Domain 2 — Predictive Markets Integration",
        "status":      "DECLARED",
        "description": (
            "Layers Kalshi, Polymarket, or equivalent prediction market "
            "contract prices over the SIC mismatch signal. When prediction "
            "market probability on a macro event (Fed decision, MXN "
            "volatility, Mexican political event) crosses a doctrine-defined "
            "threshold while the SIC spread is open — surfaces the combined "
            "signal for human authority review. The mismatch detects where. "
            "The prediction market detects when. Human authority decides if."
        ),
        "activation_requirements": [
            "AUR-H-SIC-001 active and validated first",
            "SR 11-7 Tier 1 independent validation for combined signal",
            "Prediction market API connections established and tested",
            "Kalshi/Polymarket data classified under regulatory framework",
            "Tier 2 human authority sign-off",
        ],
    },
    "AUR-H-EXEC-001": {
        "name":        "Execution Strategy Optimizer",
        "domain":      "Domain 3 — Execution Optimization",
        "status":      "DECLARED",
        "description": (
            "VWAP (Volume Weighted Average Price), TWAP (Time Weighted "
            "Average Price), and POV (Percentage of Volume) strategy "
            "recommendation within doctrine-defined objective functions. "
            "Venue and routing optimization for BMV SIC, LSE, and US "
            "primary market legs of the SIC arbitrage trade. Advisory "
            "output only — no autonomous execution."
        ),
        "activation_requirements": [
            "AUR-H-SIC-001 and AUR-H-PRED-001 active and validated",
            "SR 11-7 Tier 1 independent validation",
            "MiFID II RTS 6 kill switch, price collars, execution throttles",
            "EU AI Act conformity assessment",
            "Tier 2 human authority sign-off per domain",
        ],
    },
}

# ── SIC Spread Parameters — Doctrine-Defined, Not Self-Modifiable ─────────────
# These thresholds are set by Mentat doctrine.
# Thifur-H reads them. It never writes them.
SIC_SPREAD_PARAMS = {
    # Minimum spread (in basis points) to surface a signal
    # Below this threshold = noise, not signal
    "min_signal_threshold_bps":     25,

    # Maximum spread before position sizing hard stop triggers
    # Above this = abnormal dislocation, escalate to human authority
    "max_spread_hard_stop_bps":     200,

    # FX conversion buffer — MXN/USD/EUR triangulation tolerance
    "fx_buffer_bps":                8,

    # Indeval settlement lag adjustment — T+2 SIC vs T+1 US
    "settlement_lag_adjustment_bps": 5,

    # Market-making spread assumption for BMV SIC instruments
    "bmv_market_making_bps":        12,

    # Maximum position size as % of portfolio — hard stop
    "max_position_pct":             0.05,   # 5% hard stop

    # Predictive market probability threshold for timing signal
    "pred_market_min_probability":  0.65,   # 65% minimum conviction

    # Combined signal minimum — spread AND prediction market must both qualify
    "combined_signal_min_bps":      35,
}

# ── Price Feed Configuration — Declared, Not Connected ────────────────────────
# Feeds are defined here. They are not connected until activation.
PRICE_FEED_CONFIG = {
    "usd_etf_feed": {
        "provider":    "Twelve Data",
        "api_ref":     "TWELVE_DATA_API_KEY",
        "instruments": ["SPY", "TLT", "AGG", "GLD", "USO"],
        "currency":    "USD",
        "status":      "DECLARED — not connected",
    },
    "ucits_lse_feed": {
        "provider":    "Twelve Data / LSE direct",
        "api_ref":     "TWELVE_DATA_API_KEY",
        "instruments": ["CSPX.L", "ITPS.L", "AGGG.L"],   # LSE UCITS equivalents
        "currency":    "GBP/EUR",
        "status":      "DECLARED — not connected",
    },
    "bmv_sic_feed": {
        "provider":    "BMV market data / SIC feed",
        "api_ref":     "BMV_SIC_API_KEY",
        "instruments": ["SIC-mapped symbols"],
        "currency":    "MXN",
        "status":      "DECLARED — feed not established",
    },
    "predictive_markets": {
        "kalshi": {
            "provider": "Kalshi",
            "api_ref":  "KALSHI_API_KEY",
            "markets":  ["Fed rate decision", "MXN volatility events"],
            "status":   "DECLARED — not connected",
        },
        "polymarket": {
            "provider": "Polymarket",
            "api_ref":  "POLYMARKET_API_KEY",
            "markets":  ["Mexican election", "Macro events"],
            "status":   "DECLARED — not connected",
        },
    },
}


class ThifurH(HunterKillerAgent):
    """
    Thifur-H — Hunter-Killer — Adaptive Intelligence Agent.

    ACTIVATION STATUS: DECLARED — NOT ACTIVATED

    This class defines the complete architecture of the Thifur-H
    alpha generation agent. No method in this class executes a
    market action, connects to a live feed, or generates an
    executable signal.

    The shell exists to:
    1. Declare the capability formally in the doctrine
    2. Define the activation requirements explicitly
    3. Establish the regulatory address before activation
    4. Demonstrate that Aureon governs intelligence before deploying it

    This is the governance statement. The capability follows the governance.
    Not the other way around.
    """

    role_id = "AUR-H-ADAPTIVE-001"

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        super().__init__(aureon_state, state_lock)
        self._active = False   # Never self-activates

        print(f"[THIFUR-H] Shell initialized — v{AGENT_H_VERSION} | "
              f"Status: {ACTIVATION_STATE} | "
              "No domains active — activation requires Tier 2 authority")

    # ─────────────────────────────────────────────────────────────────────────
    # DOMAIN 1 — SIC PRICING MISMATCH DETECTION (DECLARED)
    # ─────────────────────────────────────────────────────────────────────────

    def detect_sic_spread(self,
                           usd_etf_price: float,
                           ucits_lse_price: float,
                           bmv_sic_price: float,
                           fx_rates: dict,
                           task_id: str,
                           c2: "ThifurC2") -> dict:
        """
        DECLARED — NOT ACTIVATED.

        When activated:
        Calculates the three-way price spread between:
        - USD NAV of underlying US ETF
        - EUR/GBP NAV of UCITS wrapper on LSE
        - MXN price on BMV SIC

        Applies doctrine-defined adjustments for FX conversion,
        Indeval settlement lag, and BMV market-making spread.

        If spread exceeds SIC_SPREAD_PARAMS["min_signal_threshold_bps"]
        and is below SIC_SPREAD_PARAMS["max_spread_hard_stop_bps"],
        returns an advisory signal for C2 routing to human authority.

        Returns advisory dict — never an executable order.
        """
        self._activation_guard("detect_sic_spread", "AUR-H-SIC-001")
        return self._declared_response("detect_sic_spread")

    def _calculate_theoretical_sic_price(self,
                                          usd_price: float,
                                          fx_usd_mxn: float,
                                          settlement_lag_bps: float,
                                          market_making_bps: float) -> float:
        """
        DECLARED — NOT ACTIVATED.

        When activated:
        Derives the theoretical fair value of the UCITS instrument
        on BMV SIC from the underlying USD ETF price, applying
        FX conversion and institutional cost adjustments.

        theoretical_sic = usd_price * fx_usd_mxn
                          * (1 - settlement_lag_adjustment)
                          * (1 - market_making_spread)

        This is the theoretical price. The observed BMV price is the
        market price. The spread between them is the signal.
        """
        self._activation_guard("_calculate_theoretical_sic_price",
                                "AUR-H-SIC-001")
        return 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # DOMAIN 2 — PREDICTIVE MARKETS INTEGRATION (DECLARED)
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate_predictive_signal(self,
                                    sic_spread_bps: float,
                                    kalshi_contracts: list,
                                    polymarket_contracts: list,
                                    task_id: str,
                                    c2: "ThifurC2") -> dict:
        """
        DECLARED — NOT ACTIVATED.

        When activated:
        Layers prediction market probabilities over the SIC spread signal.

        Logic:
        1. SIC spread must exceed min_signal_threshold_bps
        2. At least one prediction market contract must exceed
           pred_market_min_probability on a relevant macro event
        3. Combined signal must exceed combined_signal_min_bps

        If all three conditions are met — surfaces a COMBINED_SIGNAL
        advisory to C2 for routing to human authority review.

        The mismatch tells you WHERE the trade is.
        The prediction market tells you WHEN.
        Human authority decides IF.

        Returns advisory dict — never an executable order.
        """
        self._activation_guard("evaluate_predictive_signal",
                                "AUR-H-PRED-001")
        return self._declared_response("evaluate_predictive_signal")

    def _score_macro_event_relevance(self,
                                      contract_title: str,
                                      contract_probability: float) -> float:
        """
        DECLARED — NOT ACTIVATED.

        When activated:
        Scores a prediction market contract for relevance to the
        SIC spread trade. Relevant events include:
        - Federal Reserve rate decisions (USD/MXN FX impact)
        - MXN volatility events (Banxico decisions, political events)
        - Mexican elections and policy changes
        - Global liquidity events (risk-off flows affecting EM)
        - US equity market structural events (ETF creation/redemption)

        Returns a relevance score 0.0-1.0.
        Score is an input to the combined signal. It is not the signal.
        """
        self._activation_guard("_score_macro_event_relevance",
                                "AUR-H-PRED-001")
        return 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # DOMAIN 3 — EXECUTION STRATEGY OPTIMIZATION (DECLARED)
    # ─────────────────────────────────────────────────────────────────────────

    def recommend_execution_strategy(self,
                                      signal: dict,
                                      portfolio_state: dict,
                                      task_id: str,
                                      c2: "ThifurC2") -> dict:
        """
        DECLARED — NOT ACTIVATED.

        When activated:
        Recommends execution strategy for the three-leg SIC trade:

        Leg 1 — BMV SIC: Buy/sell the UCITS instrument in MXN
        Leg 2 — LSE:     Opposing position in UCITS wrapper in GBP/EUR
        Leg 3 — US:      Delta hedge in underlying US ETF in USD

        Strategy options (advisory only):
        - VWAP: Volume Weighted Average Price — spread execution
          over session volume curve to minimize market impact
        - TWAP: Time Weighted Average Price — spread over fixed
          time window, appropriate for thin BMV SIC liquidity
        - POV:  Percentage of Volume — size relative to observed
          volume, appropriate for US ETF leg

        All recommendations route through C2 → J → R pipeline
        before any execution. This function never touches an order.

        Returns advisory dict with recommended strategy per leg.
        """
        self._activation_guard("recommend_execution_strategy",
                                "AUR-H-EXEC-001")
        return self._declared_response("recommend_execution_strategy")

    # ─────────────────────────────────────────────────────────────────────────
    # KILL SWITCH — MiFID II RTS 6 REQUIREMENT
    # ─────────────────────────────────────────────────────────────────────────

    def emergency_suspend(self, authority: str, reason: str) -> dict:
        """
        MiFID II RTS 6 Kill Switch — Level 1.

        Immediately suspends all Thifur-H advisory output.
        Any Tier 1 or above human authority may invoke this.
        No prior approval required. Resumption requires Tier 2.

        This method is available regardless of activation state.
        Even a declared-but-not-activated shell can be formally
        suspended — the governance record is the point.
        """
        ts = datetime.now(timezone.utc).isoformat()

        suspension = {
            "agent":     AGENT_H_ID,
            "event":     "EMERGENCY_SUSPENSION",
            "ts":        ts,
            "authority": authority,
            "reason":    reason,
            "tier":      "Level 1 — All Thifur-H domains suspended",
            "resumption": "Requires Tier 2 human authority sign-off",
            "mifid_ref": "MiFID II RTS 6 — Kill Switch",
        }

        with self._lock:
            self._state.setdefault("authority_log", []).insert(0, {
                "id":        f"HAD-H-SUSPEND-{ts[:10]}",
                "ts":        ts,
                "tier":      "Thifur-H Emergency Suspension",
                "type":      "KILL_SWITCH_LEVEL_1",
                "authority": authority,
                "outcome":   f"All H domains suspended. Reason: {reason}",
                "hash":      "SUSPENSION_RECORDED",
            })

        print(f"[THIFUR-H] ⚠ EMERGENCY SUSPENSION — Authority: {authority} | "
              f"Reason: {reason}")

        return suspension

    # ─────────────────────────────────────────────────────────────────────────
    # STATUS AND DASHBOARD
    # ─────────────────────────────────────────────────────────────────────────

    def advise(self, intent: Intent) -> Advisory:
        """Declared shell — returns not-activated advisory."""
        return Advisory(
            timestamp=datetime.now(timezone.utc),
            agent_role_id=self.role_id,
            summary="Thifur-H is declared but not activated",
            recommendation={},
            requires_approval=False,
        )

    def get_status(self) -> dict:
        """Return Thifur-H status for dashboard and regulatory display."""
        return {
            "agent_id":          AGENT_H_ID,
            "version":           AGENT_H_VERSION,
            "activation_status": ACTIVATION_STATE,
            "active":            False,
            "domains": {
                "AUR-H-SIC-001":  "DECLARED — SIC Pricing Mismatch Detector",
                "AUR-H-PRED-001": "DECLARED — Predictive Markets Timing Layer",
                "AUR-H-EXEC-001": "DECLARED — Execution Strategy Optimizer",
            },
            "price_feeds": {
                "usd_etf":          "DECLARED — not connected",
                "ucits_lse":        "DECLARED — not connected",
                "bmv_sic":          "DECLARED — feed not established",
                "predictive_markets": "DECLARED — not connected",
            },
            "activation_requirements": {
                "sr_11_7_tier_1":       "PENDING — independent validation required",
                "eu_ai_act":            "PENDING — conformity assessment required",
                "mifid_rts6_inventory": "PENDING — algorithm registration required",
                "tier_2_authority":     "PENDING — human sign-off required",
                "c2_sequencing":        "CONFIRMED — C2 operational",
            },
            "guardrails": [
                "Objective function supremacy — never redefines own objective",
                "Doctrine over optimization — no efficient but non-compliant action",
                "Risk parameter hard stops — breach triggers auto-suspension",
                "Emergency suspension — any Tier 1, immediate, no prior approval",
                "No activation without independent validation",
                "Explainability before execution",
            ],
            "sic_spread_params":    SIC_SPREAD_PARAMS,
            "algorithm_registry":   ALGORITHM_REGISTRY,
            "regulatory_note": (
                "Thifur-H is a declared capability. It is not activated. "
                "No market data is consumed. No signals are generated. "
                "Activation requires completed SR 11-7 Tier 1 validation, "
                "EU AI Act conformity assessment, MiFID II RTS 6 algorithm "
                "registration, and Tier 2 human authority sign-off per domain. "
                "The governance architecture precedes the capability. "
                "This is by design."
            ),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _activation_guard(self, method_name: str, algorithm_id: str) -> None:
        """
        Hard stop on any method call while not activated.

        Logs the attempt and raises — no silent failures.
        If this is raised in production, something tried to activate
        Thifur-H without going through the proper governance path.
        That is a doctrine breach, not a bug.
        """
        if not self._active:
            ts = datetime.now(timezone.utc).isoformat()
            with self._lock:
                self._state.setdefault("authority_log", []).insert(0, {
                    "id":        f"HAD-H-GUARD-{ts[:10]}",
                    "ts":        ts,
                    "tier":      "Thifur-H Activation Guard",
                    "type":      "UNAUTHORIZED_ACTIVATION_ATTEMPT",
                    "authority": "SYSTEM",
                    "outcome":   (f"Method {method_name} called on "
                                  f"{algorithm_id} while DECLARED. "
                                  "Activation requires Tier 2 authority."),
                    "hash":      "GUARD_TRIGGERED",
                })
            raise NotActivatedError(
                f"[THIFUR-H] ACTIVATION GUARD: {method_name} on "
                f"{algorithm_id} called while status is DECLARED. "
                "Tier 2 human authority sign-off required before activation."
            )

    def _declared_response(self, method_name: str) -> dict:
        """Standard response for any declared-but-not-activated method."""
        return {
            "agent":             AGENT_H_ID,
            "method":            method_name,
            "activation_status": ACTIVATION_STATE,
            "result":            None,
            "reason": (
                "Thifur-H is declared but not activated. "
                "This method returns no output until activation requirements "
                "are satisfied and Tier 2 human authority grants sign-off."
            ),
        }
