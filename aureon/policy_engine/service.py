"""
aureon.policy_engine.service
=============================
Pre-trade compliance gate evaluation for Aureon Grid 3.

Every evaluation is persisted as a policy record bound to the decision's
content digest and the rule versions (aureon.policy_engine.binding). Approval
consumes that record: the gates bind, they do not merely advise (AUR-I-01).

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

from aureon.mcp.cato_client import _is_usable_stress_reading
from aureon.policy_engine.binding import (
    build_policy_record,
    persist_policy_record,
    pretrade_rules_digest,
)


def pro_forma_concentration_pct(*, positions, prices, symbol, action, notional, portfolio_value):
    """Percent of portfolio value in *symbol* before and after the proposed trade.

    The single concentration definition for every evaluation path (AUR-I-09):
    the pre-trade position in the symbol, valued at the latest price, plus the
    BUY notional or minus the SELL notional. A BUY moves value from cash into
    the position, so portfolio value is the denominator both times. Returns
    (None, None) when portfolio value is not positive: concentration cannot be
    computed, and the gate must not pass on that.
    """
    if not portfolio_value or portfolio_value <= 0:
        return None, None
    current = sum(
        pos["shares"] * prices.get(pos["symbol"], pos.get("cost", 0))
        for pos in positions
        if pos.get("symbol") == symbol
    )
    post = current + notional if action == "BUY" else max(0.0, current - notional)
    return current / portfolio_value * 100, post / portfolio_value * 100


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
    asset_class_gate_fn=None,
    now=None,
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

    now : datetime, optional
        Evaluation time (UTC); defaults to the current time.

    Returns
    -------
    dict or None
        Structured gate payload, or None if decision not found. ``disposition``
        is the kernel Disposition that binds approval; ``overall`` is the
        dashboard's status word. ``policy_record`` is the persisted record.
    """
    with lock:
        decision = next(
            (d for d in state.get("pending_decisions", []) if d["id"] == decision_id),
            None,
        )
        if decision is None:
            return None
        decision = dict(decision)

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

    # ── Gate 3: Single-position concentration limit (pro forma) ───
    # Checks the specific symbol being traded, not the whole asset class.
    # Asset class allocations (e.g. 45% equities) are doctrine-mandated
    # and should not be flagged here. The relevant risk is a single name
    # becoming too dominant in the portfolio — after this trade, not before.
    symbol = decision.get("symbol", "")
    warn_pct = risk_policy.get("position_warn_pct", 20.0)
    fail_pct = risk_policy.get("position_fail_pct", 35.0)
    pre_pct, pos_pct = pro_forma_concentration_pct(
        positions=positions, prices=prices, symbol=symbol,
        action=action, notional=notional, portfolio_value=portfolio_value,
    )
    if pos_pct is None:
        pos_status = "INDETERMINATE"
        pos_detail = f"Portfolio value {portfolio_value!r} — concentration cannot be computed"
    elif pos_pct >= fail_pct:
        pos_status = "FAIL"
        pos_detail = (f"{symbol} {pre_pct:.1f}% → {pos_pct:.1f}% of portfolio after this "
                      f"{action} — exceeds single-position limit {fail_pct:.0f}%")
    elif pos_pct >= warn_pct:
        pos_status = "WARN"
        pos_detail = (f"{symbol} {pre_pct:.1f}% → {pos_pct:.1f}% of portfolio after this "
                      f"{action} — approaching limit {fail_pct:.0f}%")
    else:
        pos_status = "PASS"
        pos_detail = (f"{symbol} {pre_pct:.1f}% → {pos_pct:.1f}% of portfolio after this "
                      f"{action} — within limits")
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
    # Fails closed, matching Cato v0.3.1 (golden vector V16): a stress
    # reading that is missing, NaN or infinite — or a feed that cannot be
    # read at all — never reads as PASS. Required evidence is unavailable,
    # so the disposition is INDETERMINATE (AUR-I-10), not an overrideable HOLD.
    # ofr_snapshot_fn takes the macro snapshot, as evidence_service calls it.
    try:
        macro = macro_snapshot_fn() or {}
        ofr   = ofr_snapshot_fn(macro) or {}
        stress_reading = ofr.get("fsi_value")
        unusable = f"OFR stress reading is not a usable number (got {stress_reading!r})"
    except Exception as exc:
        ofr, stress_reading = {}, None
        unusable = f"OFR stress feed unavailable ({type(exc).__name__}: {exc})"
    source = ofr.get("source", "unknown")
    if not _is_usable_stress_reading(stress_reading):
        macro_status = "INDETERMINATE"
        macro_detail = f"{unusable} — indeterminate, not assumed clear; approval refused"
    elif stress_reading > 0.7:
        macro_status = "WARN"
        macro_detail = f"OFR stress {stress_reading:.2f} ({source}) — elevated systemic risk"
    else:
        macro_status = "PASS"
        macro_detail = f"OFR stress {stress_reading:.2f} ({source}) — normal"
    gates.append({
        "gate":   "MACRO_STRESS_OVERLAY",
        "layer":  "Verana L0",
        "status": macro_status,
        "detail": macro_detail,
    })

    # ── Asset-class-specific gates (convergence) ──────────────────
    # Append the ThifurJ asset-class gates (MiFIR transparency, tokenized
    # eligibility) so the live modal runs the same asset-class-aware checks
    # as the C2 lifecycle. Equities/unmapped -> [] (no change). Never fails
    # open: an error yields an INDETERMINATE gate, not a silent pass.
    if asset_class_gate_fn is not None:
        try:
            extra = asset_class_gate_fn(decision) or []
            if extra:
                gates.extend(extra)
        except Exception as exc:
            gates.append({
                "gate":   "ASSET_CLASS_DISPATCH",
                "layer":  "Thifur-J",
                "status": "INDETERMINATE",
                "detail": f"Asset-class gate evaluation error ({exc}) — not evaluated, not passed.",
            })

    # ── Bind: persist the result against the decision digest ─────
    record = build_policy_record(
        decision=decision,
        gates=gates,
        rules_digest=pretrade_rules_digest(
            risk_policy=risk_policy,
            operating_cash_floor_pct=operating_cash_floor_pct,
            ofac_blocked_isins=ofac_blocked_isins,
        ),
        inputs={
            "portfolio_value": portfolio_value,
            "cash": cash,
            "drawdown": drawdown,
            "price": prices.get(symbol),
            "concentration_pct_pre": pre_pct,
            "concentration_pct_pro_forma": pos_pct,
        },
        now=now or datetime.now(timezone.utc),
    )
    with lock:
        persist_policy_record(state, record)

    for gate, outcome in zip(gates, record.gates):
        gate["disposition"] = outcome.disposition.value
        gate["overrideable"] = outcome.overrideable

    # Dashboard status word. Precedence: FAIL/BLOCKED > INDETERMINATE > HOLD >
    # WARN > PASS. The binding value is ``disposition``.
    statuses = [g["status"] for g in gates]
    if "FAIL" in statuses or "BLOCKED" in statuses:
        overall = "FAIL"
    elif record.disposition.value == "INDETERMINATE":
        overall = "INDETERMINATE"
    elif "HOLD" in statuses:
        overall = "HOLD"
    elif "WARN" in statuses:
        overall = "WARN"
    else:
        overall = "PASS"

    return {
        "decision_id":    decision_id,
        "symbol":         symbol,
        "action":         decision.get("action"),
        "notional":       notional,
        "overall":        overall,
        "disposition":    record.disposition.value,
        "gates":          gates,
        "policy_record":  record.model_dump(mode="json"),
        "ts":             record.evaluated_at.isoformat(),
    }
