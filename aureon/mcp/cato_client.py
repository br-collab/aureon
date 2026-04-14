"""
aureon.mcp.cato_client — Cato doctrine gate (in-process Python implementation).

This is the internal Python counterpart to the external Cato MCP server
(https://github.com/br-collab/Cato---FICC-MCP). The MCP server exists so
LLM tools (Claude Desktop, etc.) can call the same doctrine logic over
JSON-RPC. Aureon itself runs the same logic in-process for zero-overhead
pre-trade gating — no subprocess, no JSON-RPC, no stdio marshalling.

Both the MCP server and this module implement the same deterministic
gate so that the governance decision is identical regardless of caller.

Version parity: this module mirrors the Cato MCP server v0.2.0 doctrine.
It is multi-chain (Ethereum L1, Base L2, Arbitrum L2, Solana) with a
documented Fed L1 placeholder for tokenized Fed reserves (pending
GENIUS Act / Duffie 2025 PORTS proposal).

What this module does
---------------------
1. Accepts a `chain_state` dict fetched by the caller (I/O lives in
   server.py, not here — this module stays pure for testability).
2. Applies the Cato doctrine:

    ESCALATE  if OFR stress > 1.0                   (systemic stress)
    HOLD      if OFR stress > 0.5 OR gas > 50 gwei  (non-systemic friction)
    PROCEED   otherwise                             (atomic settlement viable)

3. Selects a recommended chain among live rails (PROCEED case only).
4. Ranks rails by all-in cost for a given notional.

Reference: Duffie (2025) "The Case for PORTS" — Brookings Institution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


CATO_DOCTRINE_VERSION = "0.2.1"
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

# Price fallbacks — used only when CoinGecko is unreachable and the caller
# doesn't supply a live `prices` dict. The doctrine principle: live prices
# everywhere, fallbacks only when the feed breaks. server.py fetches live
# ETH/SOL from CoinGecko in _cato_refresh_inputs() and threads the scalars
# into every function below via the `prices` parameter. Mirrors the Cato
# MCP server v0.2.1 ETH_PRICE_FALLBACK / SOL_PRICE_FALLBACK constants.
ETH_PRICE_FALLBACK = 3500.0   # USD per ETH
SOL_PRICE_FALLBACK = 150.0    # USD per SOL

# Settlement speeds (informational, surfaced in output).
CHAIN_SPEED = {
    "ethereum": "12s",
    "base": "2s",
    "arbitrum": "2s",
    "solana": "400ms",
}

# Supported rail identifiers. The fed_l1 placeholder is documented but
# intentionally never live — Cato reserves the slot for tokenized Fed
# reserves once PORTS (Duffie 2025) or the GENIUS Act ships.
SUPPORTED_CHAINS = ("ethereum", "base", "arbitrum", "solana")

SOLANA_NOTE = (
    "Solana 400ms finality eliminates T+1 window entirely at near-zero "
    "cost. Network outage history (2022-2023) requires doctrine-level "
    "resilience planning. Fallback: Base L2."
)
FED_L1_NOTE = (
    "Federal Reserve tokenized deposits (reserves) not yet available for "
    "on-chain settlement. PORTS (Duffie 2025) proposes sovereign "
    "instrument bridging this gap. Cato will route to Fed L1 when "
    "available. Monitor: GENIUS Act, CBDC working groups."
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _coerce_float(value: Any) -> Optional[float]:
    """Best-effort float coercion. Returns None for missing/unparseable."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _empty_chain_state() -> dict:
    """Return a chain_state with every rail marked unavailable.
    Used as a fallback when the caller hasn't populated the cache yet."""
    unavailable_evm = {
        "gas_gwei": None,
        "settlement_speed": None,
        "status": "unavailable",
    }
    return {
        "ethereum": {**unavailable_evm, "settlement_speed": CHAIN_SPEED["ethereum"]},
        "base":     {**unavailable_evm, "settlement_speed": CHAIN_SPEED["base"]},
        "arbitrum": {**unavailable_evm, "settlement_speed": CHAIN_SPEED["arbitrum"]},
        "solana": {
            "fee_lamports": None,
            "fee_usd_estimate": None,
            "settlement_speed": CHAIN_SPEED["solana"],
            "status": "unavailable",
        },
        "fed_l1": {
            "status": "not_yet_issued",
            "note": FED_L1_NOTE,
        },
    }


def _get_chain_state(chain_state: Optional[dict]) -> dict:
    """Normalize caller-supplied chain_state — returns empty-rails default
    if the caller didn't supply one yet."""
    if not chain_state:
        return _empty_chain_state()
    # Ensure every expected key is present so downstream access is safe.
    base = _empty_chain_state()
    for key in ("ethereum", "base", "arbitrum", "solana", "fed_l1"):
        if key in chain_state:
            base[key] = chain_state[key]
    return base


def _eth_gas(chain_state: dict) -> Optional[float]:
    """Pull Ethereum L1 gas gwei from a normalized chain_state."""
    return _coerce_float(chain_state.get("ethereum", {}).get("gas_gwei"))


# ── Cost helpers (mirror Cato MCP v0.2.1 — live prices) ─────────────────────

def _ficc_cost(notional_usd: float, sofr_pct: float, term_days: int) -> float:
    """FICC rail: 0.5 bps clearing fee net of 40% netting, annualized
    to the term, plus SOFR cost of capital for the term."""
    clearing = notional_usd * 0.00005 * (1 - 0.4) * (term_days / 360.0)
    coc = notional_usd * (sofr_pct / 100.0) * (term_days / 360.0)
    return clearing + coc


def _evm_l1_cost(gas_gwei: Optional[float], eth_price_usd: Optional[float] = None) -> Optional[float]:
    """EVM rail: gas_gwei × 65000 gas × 1e-9 × live ETH price.

    The gwei→ETH conversion is 1e-9 (corrected from the v0.1.0 1e-10 typo
    that was caught in commit ff87291 before first real-world use).
    Falls back to ETH_PRICE_FALLBACK only if the caller didn't supply a
    live eth_price_usd."""
    if gas_gwei is None:
        return None
    price = eth_price_usd if eth_price_usd is not None else ETH_PRICE_FALLBACK
    return gas_gwei * 65000 * 1e-9 * price


def _solana_cost(fee_lamports: Optional[float], sol_price_usd: Optional[float] = None) -> Optional[float]:
    """Solana rail: total lamports × 1e-9 × live SOL price.

    Falls back to SOL_PRICE_FALLBACK only if the caller didn't supply a
    live sol_price_usd."""
    if fee_lamports is None:
        return None
    price = sol_price_usd if sol_price_usd is not None else SOL_PRICE_FALLBACK
    return fee_lamports * 1e-9 * price


def _resolve_prices(prices: Optional[dict]) -> dict:
    """Normalize a caller-supplied prices dict. Returns a dict with at
    least {eth, sol, source, fallback_used}. If the caller passes None,
    falls back to the static constants and marks the result accordingly
    so the output's `price_sources` block reflects the degraded state."""
    if prices and prices.get("eth") is not None and prices.get("sol") is not None:
        return {
            "eth": float(prices["eth"]),
            "sol": float(prices["sol"]),
            "source": prices.get("source", "caller_supplied"),
            "timestamp": prices.get("timestamp"),
            "fallback_used": bool(prices.get("fallback_used", False)),
        }
    return {
        "eth": ETH_PRICE_FALLBACK,
        "sol": SOL_PRICE_FALLBACK,
        "source": "static_fallback",
        "timestamp": None,
        "fallback_used": True,
    }


# ── Tokenized settlement context ─────────────────────────────────────────────

def tokenized_settlement_context(
    *,
    sofr_rate: Optional[float],
    ofr_stress: Optional[float],
    chain_state: Optional[dict] = None,
) -> dict:
    """
    Build the tokenized-settlement context payload — same schema as the
    MCP `get_tokenized_settlement_context` tool. Uses Ethereum L1 gas as
    the single scalar for the posture calculation (matches v0.1.0 / v0.2.0
    MCP tool behavior — the posture is about ETH specifically, not the
    cheapest L2).
    """
    state = _get_chain_state(chain_state)
    gas_gwei = _eth_gas(state)
    ofr = ofr_stress if ofr_stress is not None else 0.0

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
        "source": "Aureon (in-process Cato v0.2.0)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gas_gwei": gas_gwei,
        "sofr_rate": sofr_rate,
        "ofr_stress": ofr,
        "settlement_posture": posture,
    }


# ── Atomic settlement gate (multi-chain) ─────────────────────────────────────

def _pick_recommended_chain(chain_state: dict) -> Optional[str]:
    """Cheapest-wins chain picker for the gate (trade-size-agnostic).

    Priority order (matches MCP v0.2.0 `get_atomic_settlement_gate`):
      1. Solana if fee_usd < $0.01
      2. Base   if base_gas < 1 gwei
      3. Ethereum if it has live data
      4. None
    """
    sol_fee = _coerce_float(chain_state.get("solana", {}).get("fee_usd_estimate"))
    base_gas = _coerce_float(chain_state.get("base", {}).get("gas_gwei"))
    eth_gas = _eth_gas(chain_state)
    if sol_fee is not None and sol_fee < 0.01:
        return "solana"
    if base_gas is not None and base_gas < 1:
        return "base"
    if eth_gas is not None:
        return "ethereum"
    return None


def atomic_settlement_gate(
    *,
    sofr_rate: Optional[float],
    ofr_stress: Optional[float],
    chain_state: Optional[dict] = None,
    prices: Optional[dict] = None,
) -> dict:
    """
    Deterministic Cato doctrine gate v0.2.1.

    Uses Ethereum L1 gas as the primary threshold input (mirrors MCP
    server — the 50 gwei HOLD threshold is ETH-specific, because a gas
    spike on ETH L1 signals network-wide congestion that also slows L2s).
    Returns PROCEED/HOLD/ESCALATE + recommended_chain for the PROCEED
    case, plus solana_note, fed_l1_note, and a `price_sources` block
    reflecting the live CoinGecko ETH/SOL prices the caller supplied.
    """
    resolved_prices = _resolve_prices(prices)
    state = _get_chain_state(chain_state)
    eth_gas = _eth_gas(state)
    ofr = ofr_stress if ofr_stress is not None else 0.0

    reasons: list[str] = []
    decision = "PROCEED"
    recommended_rail = "atomic"

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
        if eth_gas is not None and eth_gas > CATO_GAS_GWEI_HOLD_THRESHOLD:
            decision = "HOLD"
            reasons.append(
                f"ETH gas at {eth_gas:.1f} gwei — "
                f"above {CATO_GAS_GWEI_HOLD_THRESHOLD:.0f} gwei doctrine threshold"
            )
        if decision == "HOLD":
            recommended_rail = "traditional"
        else:
            reasons.append("All doctrine thresholds clear — atomic settlement viable")
            recommended_rail = "atomic"

    recommended_chain = _pick_recommended_chain(state) if decision == "PROCEED" else None

    posture = tokenized_settlement_context(
        sofr_rate=sofr_rate, ofr_stress=ofr_stress, chain_state=state,
    )

    return {
        "gate_decision": decision,
        "reasons": reasons,
        "recommended_rail": recommended_rail,
        "recommended_chain": recommended_chain,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "doctrine": CATO_GATE_LABEL,
        "inputs": {
            "sofr_rate": sofr_rate,
            "ofr_stress": ofr,
            "gas_gwei": eth_gas,
            "settlement_posture": posture["settlement_posture"],
        },
        "chain_state": state,
        "price_sources": {
            "eth_usd": resolved_prices["eth"],
            "sol_usd": resolved_prices["sol"],
            "source": resolved_prices["source"],
            "timestamp": resolved_prices["timestamp"],
            "fallback_used": resolved_prices["fallback_used"],
        },
        "thresholds": {
            "escalate_ofr": CATO_OFR_ESCALATE_THRESHOLD,
            "hold_ofr": CATO_OFR_HOLD_THRESHOLD,
            "hold_gas_gwei": CATO_GAS_GWEI_HOLD_THRESHOLD,
        },
        "solana_note": SOLANA_NOTE,
        "fed_l1_note": FED_L1_NOTE,
    }


# ── Compare settlement rails (multi-chain) ───────────────────────────────────

def _route_recommended_rail(
    *,
    notional_usd: float,
    ofr_stress: float,
    chain_state: dict,
) -> str:
    """Cato v0.2.0 notional-aware routing. Mirrors MCP server routing
    block exactly."""
    eth_gas = _eth_gas(chain_state)
    base_gas = _coerce_float(chain_state.get("base", {}).get("gas_gwei"))
    solana_fee_usd = _coerce_float(chain_state.get("solana", {}).get("fee_usd_estimate"))

    if ofr_stress > 0.5:
        return "ficc_traditional"
    if notional_usd > 10_000_000 and eth_gas is not None and eth_gas < 30:
        return "ethereum_l1"
    if solana_fee_usd is not None and solana_fee_usd < 0.01:
        return "solana"
    if base_gas is not None and base_gas < 1:
        return "base"
    if eth_gas is not None and eth_gas > 50:
        return "ficc_traditional"
    return "ethereum_l1"


def compare_settlement_rails(
    *,
    notional_usd: float,
    term_days: int,
    sofr_pct: float,
    ofr_stress: float = 0.0,
    chain_state: Optional[dict] = None,
    prices: Optional[dict] = None,
) -> dict:
    """
    Cato v0.2.1 multi-chain rail cost comparison.

    Returns a full rails table plus a ranked ordering (cheapest → most
    expensive) and a notional-aware recommended_rail. Rail costs use
    live CoinGecko ETH/SOL prices when the caller supplies a `prices`
    dict; otherwise falls back to the static constants (and marks
    fallback_used=True in the output's price_sources block).
    """
    resolved_prices = _resolve_prices(prices)
    state = _get_chain_state(chain_state)
    eth_gas = _eth_gas(state)
    base_gas = _coerce_float(state.get("base", {}).get("gas_gwei"))
    arb_gas = _coerce_float(state.get("arbitrum", {}).get("gas_gwei"))
    sol_fee_lamports = _coerce_float(state.get("solana", {}).get("fee_lamports"))
    sol_fee_usd = _coerce_float(state.get("solana", {}).get("fee_usd_estimate"))

    ficc_cost = _ficc_cost(notional_usd, sofr_pct, term_days)
    eth_cost = _evm_l1_cost(eth_gas, resolved_prices["eth"])
    base_cost = _evm_l1_cost(base_gas, resolved_prices["eth"])
    arb_cost = _evm_l1_cost(arb_gas, resolved_prices["eth"])
    sol_cost = _solana_cost(sol_fee_lamports, resolved_prices["sol"])

    rails_table = {
        "ficc_traditional": {
            "cost_usd": round(ficc_cost, 4),
            "speed": "T+1",
            "status": "live",
            "inputs": {
                "sofr_pct": sofr_pct,
                "term_days": term_days,
                "clearing_fee_bps": 0.5,
                "netting_benefit_pct": 40,
            },
        },
        "ethereum_l1": {
            "cost_usd": round(eth_cost, 4) if eth_cost is not None else None,
            "speed": CHAIN_SPEED["ethereum"],
            "status": state.get("ethereum", {}).get("status"),
            "inputs": {"gas_gwei": eth_gas, "gas_units": 65000, "eth_price_usd": resolved_prices["eth"]},
        },
        "base": {
            "cost_usd": round(base_cost, 4) if base_cost is not None else None,
            "speed": CHAIN_SPEED["base"],
            "status": state.get("base", {}).get("status"),
            "inputs": {"gas_gwei": base_gas, "gas_units": 65000, "eth_price_usd": resolved_prices["eth"]},
        },
        "arbitrum": {
            "cost_usd": round(arb_cost, 4) if arb_cost is not None else None,
            "speed": CHAIN_SPEED["arbitrum"],
            "status": state.get("arbitrum", {}).get("status"),
            "inputs": {"gas_gwei": arb_gas, "gas_units": 65000, "eth_price_usd": resolved_prices["eth"]},
        },
        "solana": {
            "cost_usd": round(sol_cost, 6) if sol_cost is not None else None,
            "speed": CHAIN_SPEED["solana"],
            "status": state.get("solana", {}).get("status"),
            "inputs": {"fee_lamports": sol_fee_lamports, "sol_price_usd": resolved_prices["sol"]},
        },
        "fed_l1": {
            "cost_usd": None,
            "speed": "instant",
            "status": "not_yet_issued",
            "note": "PORTS — Duffie 2025. Pending GENIUS Act.",
        },
    }

    # Ranked cheapest → most expensive, excluding null-cost rails.
    ranked = sorted(
        [
            {"rail": name, "cost_usd": r["cost_usd"], "speed": r["speed"], "status": r["status"]}
            for name, r in rails_table.items()
            if isinstance(r["cost_usd"], (int, float))
        ],
        key=lambda r: r["cost_usd"],
    )

    recommended = _route_recommended_rail(
        notional_usd=notional_usd,
        ofr_stress=ofr_stress,
        chain_state=state,
    )

    return {
        "source": "Aureon (in-process Cato v0.2.1)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "inputs": {"notional_usd": notional_usd, "term_days": term_days},
        "market_state": {
            "sofr_pct": sofr_pct,
            "ofr_stress": ofr_stress,
            "ethereum_gas_gwei": eth_gas,
            "base_gas_gwei": base_gas,
            "arbitrum_gas_gwei": arb_gas,
            "solana_fee_usd_estimate": sol_fee_usd,
            "eth_price_usd": resolved_prices["eth"],
            "sol_price_usd": resolved_prices["sol"],
        },
        "price_sources": {
            "eth_usd": resolved_prices["eth"],
            "sol_usd": resolved_prices["sol"],
            "source": resolved_prices["source"],
            "timestamp": resolved_prices["timestamp"],
            "fallback_used": resolved_prices["fallback_used"],
            "note": "Live prices via CoinGecko public API. For institutional deployment use a licensed price feed (Bloomberg BVAL, Refinitiv, Chainlink Price Feeds).",
        },
        "rails": rails_table,
        "ranked": ranked,
        "recommended_rail": recommended,
        "doctrine_note": (
            "On-chain atomic DvP eliminates T+1 counterparty risk window. "
            "FICC clearing provides netting benefit at scale. Cato v0.2.1 "
            "routes by notional, gas, and systemic stress — stress override "
            "is absolute."
        ),
        "fed_l1_note": FED_L1_NOTE,
    }
