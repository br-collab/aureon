"""
aureon.mcp.cato_client — Cato doctrine gate (in-process Python implementation).

This is the internal Python counterpart to the external Cato MCP server
(https://github.com/br-collab/Cato---FICC-MCP). The MCP server exists so
LLM tools (Claude Desktop, etc.) can call the same doctrine logic over
JSON-RPC. Aureon itself runs the same logic in-process for zero-overhead
pre-trade gating — no subprocess, no JSON-RPC, no stdio marshalling.

Both the MCP server and this module implement the same deterministic
gate so that the governance decision is identical regardless of caller.

What this module does
---------------------
Reads live SOFR, OFR financial stress index, and Ethereum gas price,
then applies the Cato doctrine:

    ESCALATE  if OFR stress index > 1.0                  (systemic stress)
    HOLD      if OFR stress > 0.5 OR ETH gas > 50 gwei   (non-systemic friction)
    PROCEED   otherwise                                  (atomic settlement viable)

The decision carries a `recommended_rail` of "atomic" (PROCEED),
"traditional" (HOLD), or "human_authority" (ESCALATE).

Reference: Duffie (2025) "The Case for PORTS" — Brookings Institution.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional


CATO_DOCTRINE_VERSION = "0.1.0"
CATO_GATE_LABEL = f"Verana L0 — Cato settlement gate v{CATO_DOCTRINE_VERSION}"

# Doctrine thresholds (see Duffie 2025, Brookings Institution).
CATO_OFR_ESCALATE_THRESHOLD = 1.0
CATO_OFR_HOLD_THRESHOLD = 0.5
CATO_GAS_GWEI_HOLD_THRESHOLD = 50.0

# Settlement-posture bands for the tokenized-settlement context tool.
CATO_POSTURE_MONITOR_GAS = 30.0
CATO_POSTURE_MONITOR_STRESS = 0.5
CATO_POSTURE_ELEVATED_GAS = 50.0
CATO_POSTURE_ELEVATED_STRESS = 1.0


def _coerce_float(value: Any) -> Optional[float]:
    """Best-effort float coercion. Returns None for missing/unparseable values."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tokenized_settlement_context(
    *,
    sofr_rate: Optional[float],
    ofr_stress: Optional[float],
    gas_gwei: Optional[float],
) -> dict:
    """
    Build the tokenized-settlement context payload — identical schema to the
    MCP `get_tokenized_settlement_context` tool. Inputs are already-extracted
    scalars so this function does no I/O.
    """
    ofr = ofr_stress if ofr_stress is not None else 0.0
    posture: str
    if ofr > CATO_POSTURE_ELEVATED_STRESS or (
        gas_gwei is not None and gas_gwei > CATO_POSTURE_ELEVATED_GAS
    ):
        posture = "elevated"
    elif ofr > CATO_POSTURE_MONITOR_STRESS or (
        gas_gwei is not None and gas_gwei > CATO_POSTURE_MONITOR_GAS
    ):
        posture = "monitor"
    else:
        posture = "favorable"

    return {
        "source": "Aureon (in-process Cato)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gas_gwei": gas_gwei,
        "sofr_rate": sofr_rate,
        "ofr_stress": ofr,
        "settlement_posture": posture,
    }


def atomic_settlement_gate(
    *,
    sofr_rate: Optional[float],
    ofr_stress: Optional[float],
    gas_gwei: Optional[float],
) -> dict:
    """
    Deterministic Cato doctrine gate. Returns the PROCEED/HOLD/ESCALATE
    decision in the same shape as the MCP `get_atomic_settlement_gate` tool.

    Inputs are already-extracted scalars so this function does no I/O. The
    caller is responsible for fetching SOFR, OFR stress, and ETH gas from
    whichever cached sources are available (market_loop background refresh
    in the Aureon case).
    """
    ofr = ofr_stress if ofr_stress is not None else 0.0
    reasons: list[str] = []
    decision = "PROCEED"
    recommended_rail = "atomic"

    # ESCALATE first — systemic stress overrides everything else.
    if ofr > CATO_OFR_ESCALATE_THRESHOLD:
        decision = "ESCALATE"
        recommended_rail = "human_authority"
        reasons.append(
            f"OFR stress index at {ofr:.2f} — "
            f"systemic stress threshold (>{CATO_OFR_ESCALATE_THRESHOLD}) breached"
        )
    else:
        if ofr > CATO_OFR_HOLD_THRESHOLD:
            decision = "HOLD"
            reasons.append(
                f"OFR stress index at {ofr:.2f} — "
                f"above-average stress (>{CATO_OFR_HOLD_THRESHOLD})"
            )
        if gas_gwei is not None and gas_gwei > CATO_GAS_GWEI_HOLD_THRESHOLD:
            decision = "HOLD"
            reasons.append(
                f"ETH gas at {gas_gwei:.1f} gwei — "
                f"above {CATO_GAS_GWEI_HOLD_THRESHOLD:.0f} gwei doctrine threshold"
            )
        if decision == "HOLD":
            recommended_rail = "traditional"
        else:
            reasons.append("All doctrine thresholds clear — atomic settlement viable")
            recommended_rail = "atomic"

    posture = tokenized_settlement_context(
        sofr_rate=sofr_rate,
        ofr_stress=ofr_stress,
        gas_gwei=gas_gwei,
    )

    return {
        "gate_decision": decision,
        "reasons": reasons,
        "recommended_rail": recommended_rail,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "doctrine": CATO_GATE_LABEL,
        "inputs": {
            "sofr_rate": sofr_rate,
            "ofr_stress": ofr,
            "gas_gwei": gas_gwei,
            "settlement_posture": posture["settlement_posture"],
        },
        "thresholds": {
            "escalate_ofr": CATO_OFR_ESCALATE_THRESHOLD,
            "hold_ofr": CATO_OFR_HOLD_THRESHOLD,
            "hold_gas_gwei": CATO_GAS_GWEI_HOLD_THRESHOLD,
        },
    }


def compare_settlement_rails(
    *,
    notional_usd: float,
    term_days: int,
    sofr_pct: float,
    gas_gwei: Optional[float],
    eth_price_proxy: float = 1800.0,
) -> dict:
    """
    Port of the Cato `compare_settlement_rails` tool. Uses the v0.1.0
    formulas with the CORRECTED gwei→ETH conversion (1e-9).
    """
    # FICC traditional rail.
    ficc_clearing = notional_usd * 0.00005 * (1 - 0.4) * (term_days / 360.0)
    ficc_cost_of_capital = notional_usd * (sofr_pct / 100.0) * (term_days / 360.0)
    ficc_cost_usd = ficc_clearing + ficc_cost_of_capital

    # Atomic on-chain rail. 1e-9 = gwei → ETH.
    onchain_cost_usd: Optional[float]
    if gas_gwei is None:
        onchain_cost_usd = None
    else:
        onchain_cost_usd = gas_gwei * 65000 * 1e-9 * eth_price_proxy

    if onchain_cost_usd is None:
        cheaper_rail = "ficc"
        cost_savings_usd = None
    elif onchain_cost_usd < ficc_cost_usd:
        cheaper_rail = "onchain"
        cost_savings_usd = round(ficc_cost_usd - onchain_cost_usd, 4)
    else:
        cheaper_rail = "ficc"
        cost_savings_usd = round(onchain_cost_usd - ficc_cost_usd, 4)

    return {
        "source": "Aureon (in-process Cato)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inputs": {"notional_usd": notional_usd, "term_days": term_days},
        "market_state": {
            "sofr_pct": sofr_pct,
            "eth_gas_gwei": gas_gwei,
            "eth_price_proxy": eth_price_proxy,
        },
        "ficc_cost_usd": round(ficc_cost_usd, 4),
        "onchain_cost_usd": round(onchain_cost_usd, 4) if onchain_cost_usd is not None else None,
        "cheaper_rail": cheaper_rail,
        "cost_savings_usd": cost_savings_usd,
        "doctrine_note": (
            "On-chain atomic DvP eliminates T+1 counterparty risk window. "
            "FICC clearing provides netting benefit at scale."
        ),
    }
