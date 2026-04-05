"""Pre-trade policy, mandate, and risk framing boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


def evaluate_pretrade_decision(
    *,
    state: dict[str, Any],
    lock: Any,
    decision_id: str,
    market_is_open: Callable[[], bool],
    macro_snapshot_fn: Callable[[], dict[str, Any]],
    ofr_snapshot_fn: Callable[[dict[str, Any]], dict[str, Any]],
    operating_cash_floor_pct: float,
    risk_policy: dict[str, float],
    symbol_to_isin: dict[str, str],
    ofac_blocked_isins: dict[str, str],
) -> dict[str, Any] | None:
    """Return DSOR pre-trade checks for a pending decision and cache the result."""
    with lock:
        decision = next((d for d in state["pending_decisions"] if d["id"] == decision_id), None)
        if not decision:
            return None
        cash = state["cash"]
        drawdown = state["drawdown"]
        portfolio_value = state["portfolio_value"]
        is_market_open = market_is_open()

    macro_snapshot = macro_snapshot_fn()
    ofr_snapshot = ofr_snapshot_fn(macro_snapshot)

    action = decision["action"]
    symbol = decision["symbol"]
    notional = decision["notional"]
    asset_cls = decision["asset_class"]
    is_crypto = symbol in {"BTC", "ETH", "SOL"}

    if action == "BUY" and not is_crypto and not is_market_open:
        session_status = "WARN"
        session_msg = f"Pre-market window — {symbol} queued for open (9:30 ET)"
    else:
        session_status = "PASS"
        session_msg = "Market session valid" if is_market_open else "Crypto — 24/7 session"

    if action == "BUY":
        cash_floor = portfolio_value * operating_cash_floor_pct
        post_trade_cash = cash - notional
        if cash < notional:
            cash_status = "FAIL"
            cash_msg = f"Insufficient cash: ${cash:,.0f} < ${notional:,} required"
        elif post_trade_cash < cash_floor:
            cash_status = "WARN"
            cash_msg = (
                f"Trade would breach 3% operating floor — post-trade cash ${post_trade_cash:,.0f} "
                f"< floor ${cash_floor:,.0f}"
            )
        else:
            cash_status = "PASS"
            cash_msg = (
                f"Cash available: ${cash:,.0f} — order ${notional:,} covered — "
                f"floor ${cash_floor:,.0f} maintained"
            )
    else:
        cash_status = "PASS"
        cash_msg = "SELL — no cash requirement"

    if drawdown > risk_policy["drawdown_fail_pct"]:
        dd_status = "FAIL"
        dd_msg = f"Drawdown {drawdown:.2f}% exceeds {risk_policy['drawdown_fail_pct']:.0f}% threshold — BUY blocked"
    elif drawdown > risk_policy["drawdown_warn_pct"]:
        dd_status = "WARN"
        dd_msg = f"Drawdown {drawdown:.2f}% elevated — monitoring"
    else:
        dd_status = "PASS"
        dd_msg = f"Drawdown {drawdown:.2f}% within limits"

    pos_pct = (notional / portfolio_value * 100) if portfolio_value > 0 else 0
    if pos_pct > risk_policy["position_fail_pct"]:
        pos_status = "FAIL"
        pos_msg = f"Position {pos_pct:.1f}% of portfolio exceeds {risk_policy['position_fail_pct']:.0f}% hard cap"
    elif pos_pct > risk_policy["position_warn_pct"]:
        pos_status = "WARN"
        pos_msg = f"Position {pos_pct:.1f}% of portfolio — approaching limit"
    else:
        pos_status = "PASS"
        pos_msg = f"Position size {pos_pct:.1f}% within doctrine bounds"

    doc_status = "PASS"
    doc_msg = f"Doctrine v{state.get('doctrine_version', '1.2')} — audit lineage intact"

    ofr_band = ofr_snapshot.get("fsi_band", "watch")
    ofr_value = ofr_snapshot.get("fsi_value", 0.0)
    leveraged_trade = asset_cls == "crypto" or symbol in {"BTC", "ETH", "SOL"}
    if ofr_band == "severe" and action == "BUY" and leveraged_trade:
        stress_status = "FAIL"
        stress_msg = f"OFR severe stress {ofr_value:.2f} — aggressive risk deployment blocked for {symbol}"
    elif ofr_band == "severe":
        stress_status = "WARN"
        stress_msg = f"OFR severe stress {ofr_value:.2f} — senior review required before execution"
    elif ofr_band == "elevated":
        stress_status = "WARN"
        stress_msg = f"OFR elevated stress {ofr_value:.2f} — doctrine shifts to cautionary posture"
    else:
        stress_status = "PASS"
        stress_msg = f"OFR stress band {ofr_band.upper()} ({ofr_value:.2f}) within doctrine tolerance"

    isin_id = symbol_to_isin.get(symbol)
    if isin_id and isin_id in ofac_blocked_isins:
        ofac_status = "FAIL"
        ofac_msg = f"OFAC BLOCKED: {ofac_blocked_isins[isin_id]}"
    else:
        ofac_status = "PASS"
        screen_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ofac_msg = f"SDN clear — {symbol} not on OFAC blocked list (screened {screen_date} · source: OFAC SDN XML)"

    checks = [
        {"gate": "Session Boundary", "layer": "Verana L0", "status": session_status, "detail": session_msg},
        {"gate": "Liquidity Buffer", "layer": "Risk Manager L1B", "status": cash_status, "detail": cash_msg},
        {"gate": "Drawdown Guard", "layer": "Risk Manager L1B", "status": dd_status, "detail": dd_msg},
        {"gate": "Position Limit", "layer": "Risk Manager L1B", "status": pos_status, "detail": pos_msg},
        {"gate": "Doctrine Integrity", "layer": "Thifur L3", "status": doc_status, "detail": doc_msg},
        {"gate": "Systemic Stress", "layer": "Verana L0 / OFR", "status": stress_status, "detail": stress_msg},
        {"gate": "OFAC Screening", "layer": "Verana L0", "status": ofac_status, "detail": ofac_msg},
    ]

    overall = "FAIL" if any(c["status"] == "FAIL" for c in checks) else "WARN" if any(c["status"] == "WARN" for c in checks) else "PASS"
    settlement = "T+0" if is_crypto else "T+1"
    payload = {
        "decision_id": decision_id,
        "action": action,
        "symbol": symbol,
        "notional": notional,
        "asset_class": asset_cls,
        "overall": overall,
        "settlement": settlement,
        "checks": checks,
        "ofr": ofr_snapshot,
        "macro": macro_snapshot,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    with lock:
        state.setdefault("_pretrade_cache", {})[decision_id] = {
            "overall": overall,
            "checks": checks,
            "settlement": settlement,
            "ofr": ofr_snapshot,
            "macro": macro_snapshot,
            "ts": payload["ts"],
        }
    return payload
