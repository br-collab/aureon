"""Approval boundary enforcing DSOR release control before OMS/EMS handoff."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone
from typing import Any, Callable

from aureon.approval_service.routing import apply_routing
from aureon.approval_service.release_control import approve_role, can_release
from aureon.core.models import GovernedDecision


def apply_approved_trade(state: dict[str, Any], decision: dict[str, Any], exec_price: float) -> tuple[bool, str | None]:
    """Apply an already-approved trade to local prototype state."""
    symbol = decision["symbol"]
    shares = decision["shares"]
    asset_class = decision["asset_class"]
    notional = shares * exec_price

    if decision["action"] == "BUY":
        state["positions"].append(
            {"symbol": symbol, "asset_class": asset_class, "shares": shares, "cost": round(exec_price, 2), "agent": "THIFUR_H"}
        )
        state["cash"] -= notional
        return True, None

    remaining = shares
    matched_positions = [p for p in state["positions"] if p["symbol"] == symbol]
    available = sum(p.get("shares", 0) for p in matched_positions)
    if available < shares:
        return False, f"SELL blocked — available {symbol} shares {available:,.0f} < requested {shares:,.0f}"

    new_positions = []
    for pos in state["positions"]:
        if pos["symbol"] != symbol or remaining <= 0:
            new_positions.append(pos)
            continue
        lot_shares = pos.get("shares", 0)
        to_sell = min(lot_shares, remaining)
        remaining -= to_sell
        left = lot_shares - to_sell
        if left > 0:
            updated = dict(pos)
            updated["shares"] = left
            new_positions.append(updated)
    state["positions"] = new_positions
    state["cash"] += notional
    return True, None


def resolve_pending_decision(
    *,
    state: dict[str, Any],
    lock: Any,
    decision_id: str,
    resolution: str,
    approval_role: str,
    build_trade_report: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """
    Enforce Phase 1 release control:
    no governed release and no OMS/EMS handoff until required approval is complete.
    """
    if resolution not in ("APPROVED", "REJECTED"):
        raise ValueError("resolution must be APPROVED or REJECTED")

    with lock:
        if state["halt_active"] and resolution == "APPROVED":
            raise RuntimeError("SYSTEM HALTED — execution blocked. Resume system before approving trades.")

        decision_raw = next((d for d in state["pending_decisions"] if d["id"] == decision_id), None)
        if not decision_raw:
            raise LookupError("decision not found")

        decision_model = apply_routing(GovernedDecision.from_mapping(decision_raw))
        authority_hash = hashlib.sha256(f"{decision_id}{resolution}".encode()).hexdigest()[:16].upper()
        state["authority_log"].insert(
            0,
            {
                "id": f"HAD-{random.randint(1000, 9999)}",
                "ts": datetime.now(timezone.utc).isoformat(),
                "tier": "Tier 1",
                "type": f"Trade {resolution}: {decision_model.action} {decision_model.symbol}",
                "authority": approval_role,
                "outcome": resolution,
                "hash": authority_hash,
            },
        )

        result: dict[str, Any] = {
            "status": "ok",
            "resolution": resolution,
            "decision_id": decision_id,
            "hash": authority_hash,
            "report_id": None,
            "trade_report": None,
            "decision": decision_model.to_mapping(),
        }

        if resolution == "APPROVED":
            decision_model = approve_role(decision_model, approval_role)
            if not can_release(decision_model):
                updated = decision_model.to_mapping()
                updated["status"] = "PENDING_APPROVALS"
                state["pending_decisions"] = [
                    updated if d["id"] == decision_id else d for d in state["pending_decisions"]
                ]
                result["status"] = "pending_approvals"
                result["decision"] = updated
                return result

            state["pending_decisions"] = [d for d in state["pending_decisions"] if d["id"] != decision_id]
            decision = decision_model.to_mapping()
            exec_price = state["prices"].get(decision["symbol"], decision["price"])
            portfolio_snapshot = {
                "cash": state["cash"],
                "portfolio_value": state["portfolio_value"],
                "drawdown": state["drawdown"],
                "n_positions": len(state["positions"]),
            }
            ok, exec_error = apply_approved_trade(state, decision, exec_price)
            if not ok:
                state["pending_decisions"].insert(0, decision)
                raise RuntimeError(exec_error or "trade application failed")

            state["trades"].insert(
                0,
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "action": decision["action"],
                    "symbol": decision["symbol"],
                    "asset_class": decision["asset_class"],
                    "shares": decision["shares"],
                    "price": round(exec_price, 2),
                    "notional": decision["notional"],
                    "agent": "THIFUR_H",
                    "decision_id": decision_id,
                    "signal_type": decision.get("signal_type"),
                    "human_approved": True,
                    "release_target": decision.get("release_target", "OMS"),
                    "final_approvals": list(decision.get("current_approvals", [])),
                    "required_approvals": list(decision.get("required_approvals", [])),
                    "release_outcome": "RELEASED",
                    "hash": authority_hash,
                },
            )

            gate_results = state.get("_pretrade_cache", {}).get(decision_id, {}).get("checks", [])
            trade_report = build_trade_report(
                decision=decision,
                exec_price=exec_price,
                authority_hash=authority_hash,
                gate_results=gate_results,
                portfolio_before=portfolio_snapshot,
            )
            state["trade_reports"].insert(0, trade_report)
            result["report_id"] = trade_report.get("report_id")
            result["trade_report"] = trade_report
            result["decision"] = decision

        else:
            state["pending_decisions"] = [d for d in state["pending_decisions"] if d["id"] != decision_id]
        return result
