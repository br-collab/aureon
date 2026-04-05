"""
aureon.approval_service.service
================================
Human-in-the-loop (HITL) decision resolution for Aureon Grid 3.

Handles the core approve/reject lifecycle:
  - Validates the decision exists and the system is not halted
  - Records partial approvals (multi-role workflows)
  - On full approval: applies the trade, builds the compliance report
  - On rejection: marks the decision cancelled
  - Stamps every action with a deterministic authority hash
"""

import hashlib
from datetime import datetime, timezone


def resolve_pending_decision(
    *,
    state,
    lock,
    decision_id,
    resolution,
    approval_role,
    build_trade_report,
):
    """
    Resolve a pending decision as APPROVED or REJECTED.

    Parameters
    ----------
    state : dict
        The live aureon_state dictionary (mutated in-place under *lock*).
    lock : threading.Lock
        The state lock.
    decision_id : str
        ID of the decision to resolve.
    resolution : str
        "APPROVED" or "REJECTED".
    approval_role : str
        The role of the approving/rejecting authority (e.g. "TRADER").
    build_trade_report : callable
        ``_build_trade_report(decision, exec_price, authority_hash,
        gate_results, portfolio_before)`` — builds the compliance artifact.

    Returns
    -------
    dict
        Keys: status, resolution, decision_id, hash, report_id,
              decision, trade_report.

    Raises
    ------
    LookupError
        If *decision_id* is not found in pending_decisions.
    RuntimeError
        If the system halt is active (status 423) or the trade cannot
        be applied (status 409).
    ValueError
        If *resolution* is not "APPROVED" or "REJECTED".
    """
    if resolution not in ("APPROVED", "REJECTED"):
        raise ValueError(f"Invalid resolution: {resolution!r}")

    ts = datetime.now(timezone.utc).isoformat()
    authority_hash = hashlib.sha256(
        f"AUREON-{resolution}-{decision_id}-{approval_role}-{ts}".encode()
    ).hexdigest()[:16].upper()

    with lock:
        # ── Halt check ────────────────────────────────────────────
        if state.get("halt_active"):
            raise RuntimeError(
                f"SYSTEM HALTED — {state.get('halt_reason', 'emergency halt active')}"
            )

        # ── Find the decision ─────────────────────────────────────
        pending = state.get("pending_decisions", [])
        decision = next((d for d in pending if d["id"] == decision_id), None)
        if decision is None:
            raise LookupError(f"Decision {decision_id!r} not found")

        if resolution == "REJECTED":
            # ── Rejection path ────────────────────────────────────
            pending[:] = [d for d in pending if d["id"] != decision_id]
            decision["status"] = "REJECTED"

            state["authority_log"].insert(0, {
                "id":        f"HAD-{decision_id[-8:]}",
                "ts":        ts,
                "tier":      "Tier 1 — Human Authority",
                "type":      f"REJECT {decision['action']} {decision['symbol']}",
                "authority": approval_role,
                "outcome":   f"REJECTED — ${decision.get('notional', 0):,}",
                "hash":      authority_hash,
            })

            return {
                "status":      "rejected",
                "resolution":  "REJECTED",
                "decision_id": decision_id,
                "hash":        authority_hash,
                "report_id":   None,
                "decision":    decision,
                "trade_report": None,
            }

        # ── Approval path ─────────────────────────────────────────
        current = list(decision.get("current_approvals", []))
        if approval_role not in current:
            current.append(approval_role)
        decision["current_approvals"] = current

        required = list(decision.get("required_approvals", []))
        all_approved = all(r in current for r in required)

        if not all_approved:
            # Partial approval — record and return "pending" status
            state["authority_log"].insert(0, {
                "id":        f"HAD-{decision_id[-8:]}",
                "ts":        ts,
                "tier":      "Tier 1 — Human Authority",
                "type":      f"PARTIAL APPROVE {decision['action']} {decision['symbol']}",
                "authority": approval_role,
                "outcome":   f"Role {approval_role} approved — awaiting {set(required) - set(current)}",
                "hash":      authority_hash,
            })
            return {
                "status":      "pending",
                "resolution":  "APPROVED",
                "decision_id": decision_id,
                "hash":        authority_hash,
                "report_id":   None,
                "decision":    decision,
                "trade_report": None,
            }

        # ── Full approval — execute the trade ─────────────────────
        exec_price = float(
            state.get("prices", {}).get(decision["symbol"], decision.get("price", 0))
        )
        if exec_price <= 0:
            exec_price = float(decision.get("price", 0))

        portfolio_before = {
            "portfolio_value": state.get("portfolio_value", 0.0),
            "cash":            state.get("cash", 0.0),
            "drawdown":        state.get("drawdown", 0.0),
            "n_positions":     len(state.get("positions", [])),
        }

        # Apply the trade to positions and cash
        ok, err = _apply_trade(state, decision, exec_price)
        if not ok:
            raise RuntimeError(err or "Trade application failed")

        # Remove from pending queue
        pending[:] = [d for d in pending if d["id"] != decision_id]
        decision["status"] = "APPROVED"

        notional = decision["shares"] * exec_price

        # Record in trades log
        trade_record = {
            **decision,
            "exec_price":        round(exec_price, 2),
            "notional":          round(notional, 2),
            "authority_hash":    authority_hash,
            "final_approvals":   current,
            "required_approvals": required,
            "release_target":    decision.get("release_target", "OMS"),
            "release_outcome":   "RELEASED",
            "ts":                ts,
        }
        state.setdefault("trades", []).insert(0, trade_record)

        # Authority log entry
        state["authority_log"].insert(0, {
            "id":        f"HAD-{decision_id[-8:]}",
            "ts":        ts,
            "tier":      "Tier 1 — Human Authority",
            "type":      f"APPROVE {decision['action']} {decision['symbol']}",
            "authority": approval_role,
            "outcome":   f"APPROVED — ${notional:,.0f} @ ${exec_price:.2f}",
            "hash":      authority_hash,
        })

    # ── Build compliance report (outside lock to avoid deadlock) ──
    trade_report = None
    try:
        trade_report = build_trade_report(
            decision,
            exec_price,
            authority_hash,
            [],   # gate_results — populated by pre-trade check
            portfolio_before,
        )
        with lock:
            state.setdefault("trade_reports", []).insert(0, trade_report)
    except Exception as exc:
        print(f"[AUREON] Trade report build failed: {exc}")

    report_id = trade_report["report_id"] if trade_report else None

    return {
        "status":      "ok",
        "resolution":  "APPROVED",
        "decision_id": decision_id,
        "hash":        authority_hash,
        "report_id":   report_id,
        "decision":    decision,
        "trade_report": trade_report,
    }


def _apply_trade(state, decision, exec_price):
    """
    Mutate *state* to reflect an approved trade.

    BUY  → append a new position lot, deduct cash.
    SELL → reduce existing lots FIFO, add cash.

    Returns (ok: bool, error_message: str | None).
    Must be called while holding the state lock.
    """
    symbol     = decision["symbol"]
    shares     = decision["shares"]
    asset_class = decision["asset_class"]
    notional   = shares * exec_price

    if decision["action"] == "BUY":
        state.setdefault("positions", []).append({
            "symbol":      symbol,
            "asset_class": asset_class,
            "shares":      shares,
            "cost":        round(exec_price, 2),
            "agent":       "THIFUR_H",
        })
        state["cash"] = state.get("cash", 0.0) - notional
        return True, None

    # SELL — FIFO lot reduction
    remaining = shares
    positions = state.get("positions", [])
    available = sum(p.get("shares", 0) for p in positions if p["symbol"] == symbol)
    if available < shares:
        return False, (
            f"SELL blocked — available {symbol} shares {available:,.0f} "
            f"< requested {shares:,.0f}"
        )

    new_positions = []
    for pos in positions:
        if pos["symbol"] != symbol or remaining <= 0:
            new_positions.append(pos)
            continue
        lot_shares = pos.get("shares", 0)
        to_sell    = min(lot_shares, remaining)
        remaining -= to_sell
        left       = lot_shares - to_sell
        if left > 0:
            updated = dict(pos)
            updated["shares"] = left
            new_positions.append(updated)

    state["positions"] = new_positions
    state["cash"] = state.get("cash", 0.0) + notional
    return True, None
