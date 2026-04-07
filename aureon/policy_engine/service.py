"""
aureon.policy_engine.service
=============================
Pre-trade compliance gate evaluation for Aureon Grid 3.

Runs the full pre-trade gate sequence for a pending decision:
  - Market status (session boundary)
  - Cash sufficiency
  - Position concentration limit
  - Drawdown limit
  - OFAC / SDN sanctions screening
  - Macro stress overlay (FRED / OFR)

Returns a structured payload suitable for the /api/decisions/<id>/pretrade
endpoint, or None if the decision_id is not found.
"""

from datetime import datetime, timezone


def evaluate_pretrade_decision(
    *,
    state,
    lock,
    decision_id,
    market_is_open,
    macro_snapshot_fn,
    ofr_snapshot_fn,
    operating_cash_floor_pct,
    risk_policy,
    symbol_to_isin,
    ofac_blocked_isins,
):
    """
    Evaluate all pre-trade gates for *decision_id*.

    Parameters
    ----------
    state : dict
        The live aureon_state dictionary.
    lock : threading.Lock
        The state lock — acquired internally for reads.
    decision_id : str
        The decision to evaluate.
    market_is_open : callable
        Zero-argument callable returning bool.
    macro_snapshot_fn : callable
        Returns a dict of macro indicators (may be empty).
    ofr_snapshot_fn : callable
        Returns a dict of OFR stress indicators (may be empty).
    operating_cash_floor_pct : float
        Fraction of portfolio value that must remain as liquid cash.
    risk_policy : dict
        Keys: drawdown_warn_pct, drawdown_fail_pct,
              position_warn_pct, position_fail_pct, var_limit_pct.
    symbol_to_isin : dict
        Maps ticker symbols to ISIN identifiers for SDN lookup.
    ofac_blocked_isins : dict
        Maps blocked ISINs to their sanction description.

    Returns
    -------
    dict or None
        Structured gate payload, or None if decision not found.
    """
    with lock:
        decision = next(
            (d for d in state.get("pending_decisions", []) if d["id"] == decision_id),
            None,
        )
        if decision is None:
            return None

        portfolio_value = state.get("portfolio_value", 0.0)
        cash            = state.get("cash", 0.0)
        drawdown        = state.get("drawdown", 0.0)
        positions       = list(state.get("positions", []))
        prices          = dict(state.get("prices", {}))

    gates = []

    # ── Gate 1: Market session boundary ───────────────────────────
    CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL"}
    symbol = decision.get("symbol", "")
    is_crypto = symbol in CRYPTO_SYMBOLS
    market_open = market_is_open()
    if is_crypto or market_open:
        gates.append({
            "gate":   "MARKET_STATUS",
            "layer":  "Verana L0",
            "status": "PASS",
            "detail": "24/7 crypto market" if is_crypto else "US equity session open",
        })
    else:
        gates.append({
            "gate":   "MARKET_STATUS",
            "layer":  "Verana L0",
            "status": "WARN",
            "detail": "US equity/FX market closed — execution will queue for next session",
        })

    # ── Gate 2: Cash sufficiency (BUY only) ───────────────────────
    # SELL orders generate cash — no cash floor check needed.
    notional    = decision.get("notional", 0)
    action      = decision.get("action", "BUY")
    if action == "SELL":
        gates.append({
            "gate":   "CASH_SUFFICIENCY",
            "layer":  "Kaladan L2",
            "status": "PASS",
            "detail": f"SELL order — generates ${notional:,.0f} cash, no floor check required",
        })
    else:
        cash_floor  = portfolio_value * operating_cash_floor_pct
        cash_avail  = max(0.0, cash - cash_floor)
        if cash_avail >= notional:
            gates.append({
                "gate":   "CASH_SUFFICIENCY",
                "layer":  "Kaladan L2",
                "status": "PASS",
                "detail": f"Available: ${cash_avail:,.0f} ≥ Notional: ${notional:,.0f}",
            })
        else:
            gates.append({
                "gate":   "CASH_SUFFICIENCY",
                "layer":  "Kaladan L2",
                "status": "FAIL",
                "detail": f"Available: ${cash_avail:,.0f} < Notional: ${notional:,.0f} — insufficient cash",
            })

    # ── Gate 3: Single-position concentration limit ───────────────
    # Checks the specific symbol being traded, not the whole asset class.
    # Asset class allocations (e.g. 45% equities) are doctrine-mandated
    # and should not be flagged here. The relevant risk is a single name
    # becoming too dominant in the portfolio.
    symbol = decision.get("symbol", "")
    pos_value = sum(
        pos["shares"] * prices.get(pos["symbol"], pos.get("cost", 0))
        for pos in positions
        if pos.get("symbol") == symbol
    )
    pos_pct  = (pos_value / portfolio_value * 100) if portfolio_value > 0 else 0.0
    warn_pct = risk_policy.get("position_warn_pct", 20.0)
    fail_pct = risk_policy.get("position_fail_pct", 35.0)
    if pos_pct >= fail_pct:
        pos_status = "FAIL"
        pos_detail = f"{symbol} at {pos_pct:.1f}% of portfolio — exceeds single-position limit {fail_pct:.0f}%"
    elif pos_pct >= warn_pct:
        pos_status = "WARN"
        pos_detail = f"{symbol} at {pos_pct:.1f}% of portfolio — approaching limit {fail_pct:.0f}%"
    else:
        pos_status = "PASS"
        pos_detail = f"{symbol} at {pos_pct:.1f}% of portfolio — within limits"
    gates.append({
        "gate":   "POSITION_CONCENTRATION",
        "layer":  "Mentat L1",
        "status": pos_status,
        "detail": pos_detail,
    })

    # ── Gate 4: Drawdown limit ─────────────────────────────────────
    dd_warn = risk_policy.get("drawdown_warn_pct", 5.0)
    dd_fail = risk_policy.get("drawdown_fail_pct", 8.0)
    if drawdown >= dd_fail:
        dd_status = "FAIL"
        dd_detail = f"Drawdown {drawdown:.2f}% — exceeds hard limit {dd_fail:.0f}%"
    elif drawdown >= dd_warn:
        dd_status = "WARN"
        dd_detail = f"Drawdown {drawdown:.2f}% — approaching limit {dd_fail:.0f}%"
    else:
        dd_status = "PASS"
        dd_detail = f"Drawdown {drawdown:.2f}% — within policy"
    gates.append({
        "gate":   "DRAWDOWN_LIMIT",
        "layer":  "Mentat L1",
        "status": dd_status,
        "detail": dd_detail,
    })

    # ── Gate 5: OFAC / SDN sanctions screening ────────────────────
    isin = symbol_to_isin.get(symbol)
    if isin and isin in ofac_blocked_isins:
        gates.append({
            "gate":   "OFAC_SDN_SCREEN",
            "layer":  "Verana L0",
            "status": "FAIL",
            "detail": f"BLOCKED — {ofac_blocked_isins[isin]}",
        })
    else:
        gates.append({
            "gate":   "OFAC_SDN_SCREEN",
            "layer":  "Verana L0",
            "status": "PASS",
            "detail": "No SDN / sanctions match",
        })

    # ── Gate 6: Macro stress overlay ──────────────────────────────
    try:
        macro = macro_snapshot_fn() or {}
        ofr   = ofr_snapshot_fn()   or {}
        stress_score = ofr.get("stress_score", 0.0)
        if stress_score > 0.7:
            macro_status = "WARN"
            macro_detail = f"OFR stress score {stress_score:.2f} — elevated systemic risk"
        else:
            macro_status = "PASS"
            macro_detail = f"OFR stress score {stress_score:.2f} — normal"
    except Exception:
        macro_status = "PASS"
        macro_detail = "Macro overlay unavailable — proceeding"
    gates.append({
        "gate":   "MACRO_STRESS_OVERLAY",
        "layer":  "Verana L0",
        "status": macro_status,
        "detail": macro_detail,
    })

    # ── Aggregate result ──────────────────────────────────────────
    statuses = [g["status"] for g in gates]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "WARN" in statuses:
        overall = "WARN"
    else:
        overall = "PASS"

    return {
        "decision_id": decision_id,
        "symbol":      symbol,
        "action":      decision.get("action"),
        "notional":    notional,
        "overall":     overall,
        "gates":       gates,
        "ts":          datetime.now(timezone.utc).isoformat(),
    }
