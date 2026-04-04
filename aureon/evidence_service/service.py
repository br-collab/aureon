"""
aureon.evidence_service.service
================================
Trade report (compliance artifact) builder for Aureon Grid 3.

Produces a governance-enriched compliance record at the moment Kaladan
confirms execution.  Tape fields follow institutional standards:
  - ISIN (ISO 6166) as primary instrument identifier
  - CUSIP for US instruments
  - FIX 4.4 SecurityType (Tag 167) and Product (Tag 460)
  - LEI for entity identification (MiFID II counterparty disclosure)
  - MIC (ISO 10383) for execution venue
"""

from datetime import datetime, timezone


def build_trade_report(
    *,
    decision,
    exec_price,
    authority_hash,
    gate_results,
    portfolio_before,
    doctrine_version,
    instrument_ref,
    entity_lei,
    macro_snapshot_fn,
    ofr_snapshot_fn,
):
    """
    Build and return the governance-enriched compliance record.

    Parameters
    ----------
    decision : dict
        The approved pending decision dict.
    exec_price : float
        Actual execution price.
    authority_hash : str
        SHA-256 authority hash stamped at approval.
    gate_results : list[dict]
        Pre-trade gate results from the policy engine.
    portfolio_before : dict
        Snapshot of portfolio state before execution
        (keys: portfolio_value, cash, drawdown, n_positions).
    doctrine_version : str
        Active doctrine version string (e.g. "1.2").
    instrument_ref : dict
        Maps ticker symbols to institutional reference data
        (isin, cusip, fix_type, fix_product, mic, currency).
    entity_lei : str
        ISO 17442 LEI for the Aureon entity.
    macro_snapshot_fn : callable
        Zero-argument callable returning a macro indicator dict.
    ofr_snapshot_fn : callable
        Single-argument callable (macro_snapshot) returning OFR stress dict.

    Returns
    -------
    dict
        Compliance report record.  Includes ``pdf_bytes`` key if PDF
        generation succeeds (requires reportlab), otherwise None.
    """
    now_utc   = datetime.now(timezone.utc)
    exec_ts   = now_utc.isoformat()
    report_id = f"CTR-{decision['id'][-8:]}"

    CRYPTO     = {"BTC", "ETH", "SOL"}
    sym        = decision["symbol"]
    is_crypto  = sym in CRYPTO
    settlement = "T+0" if is_crypto else "T+1"

    try:
        macro_snapshot = macro_snapshot_fn() or {}
    except Exception:
        macro_snapshot = {}
    try:
        ofr_snapshot = ofr_snapshot_fn(macro_snapshot) or {}
    except Exception:
        ofr_snapshot = {}

    notional    = decision["shares"] * exec_price
    action_sign = -1 if decision["action"] == "BUY" else 1
    cash_after  = portfolio_before["cash"] + (action_sign * notional)

    pv               = portfolio_before["portfolio_value"]
    n_positions_pre  = portfolio_before["n_positions"]
    n_positions_post = (
        n_positions_pre + 1
        if decision["action"] == "BUY"
        else max(0, n_positions_pre - 1)
    )
    conc_pre   = (notional / pv * 100) if pv > 0 else 0
    conc_post  = conc_pre
    var_impact = (
        -(notional / pv * 0.08 * 100)
        if decision["action"] == "BUY"
        else (notional / pv * 0.05 * 100)
    ) if pv > 0 else 0

    ref = instrument_ref.get(sym, {})

    report = {
        "report_id":    report_id,
        "decision_id":  decision["id"],
        "generated_ts": exec_ts,
        "exec_ts":      exec_ts,
        "approval_ts":  exec_ts,

        # ── Trade Identity (institutional tape fields) ────────────
        "action":      decision["action"],
        "symbol":      sym,
        "isin":        ref.get("isin"),
        "cusip":       ref.get("cusip"),
        "fix_type":    ref.get("fix_type"),
        "fix_product": ref.get("fix_product"),
        "mic":         ref.get("mic"),
        "currency":    ref.get("currency", "USD"),
        "asset_class": decision["asset_class"],
        "shares":      decision["shares"],
        "exec_price":  round(exec_price, 2),
        "notional":    round(notional, 2),
        "settlement":  settlement,
        "agent":       "THIFUR_H",
        "authority_hash": authority_hash,
        "entity_lei":  entity_lei,

        # ── Governance Block ──────────────────────────────────────
        "doctrine_version":  doctrine_version,
        "tier_authority":    "Tier 1 — Human Authority",
        "approved_by":       "br@ravelobizdev.com",
        "gate_results":      gate_results,
        "frameworks_active": [
            "MiFID II Art.17/RTS6", "SR 11-7", "Basel III",
            "DORA Art.28", "Dodd-Frank 4a(1)",
        ],

        # ── Risk State at Execution ────────────────────────────────
        "drawdown_at_exec":        portfolio_before["drawdown"],
        "portfolio_value_at_exec": pv,
        "cash_before":             portfolio_before["cash"],
        "cash_after":              round(cash_after, 2),
        "position_conc_pre":       round(conc_pre, 2),
        "position_conc_post":      round(conc_post, 2),
        "var_impact":              round(var_impact, 4),
        "positions_post":          n_positions_post,
        "macro_regime_at_exec":    macro_snapshot.get("macro_regime"),
        "ofr_fsi_at_exec":         ofr_snapshot.get("fsi_value"),
        "ofr_band_at_exec":        ofr_snapshot.get("fsi_band"),
        "systemic_overlay_source": ofr_snapshot.get("source"),
    }

    # ── Optional PDF generation ────────────────────────────────────
    try:
        from server import _generate_compliance_pdf  # noqa: PLC0415
        report["pdf_bytes"] = _generate_compliance_pdf(report)
    except Exception as exc:
        print(f"[AUREON] PDF generation failed: {exc}")
        report["pdf_bytes"] = None

    return report
