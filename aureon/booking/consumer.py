"""
aureon.booking.consumer
=======================
Books cash, positions and trades from execution fills, once each (AUR-I-02).

``book_fill`` is the only place a governed decision changes economic state.
It takes a venue fill, never an approval. A fill already booked is
acknowledged as a duplicate and changes nothing, so redelivery after a retry
or restart cannot double-book.

A fill that cannot be booked (a BUY the cash cannot fund, a SELL of shares not
held) is refused whole and recorded as a booking break. Nothing is partially
booked: recording a partial position nobody executed would invent one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aureon.approval_service.release import ReleaseAuthorized
from aureon.booking.reconcile import compare_intent_with_execution
from aureon.integration_adapters.paper_venue import PaperFill

__all__ = ["BookingOutcome", "book_fill"]

MAX_BOOKED_FILL_IDS = 5000


@dataclass(frozen=True)
class BookingOutcome:
    status: str  # BOOKED | DUPLICATE | REFUSED
    fill_id: str
    trade: dict[str, Any] | None
    error: str | None
    reconciliation: list[dict[str, Any]]
    portfolio_before: dict[str, Any] | None


def _apply_fill(state: dict[str, Any], fill: PaperFill) -> tuple[bool, str | None]:
    """Mutate positions and cash for ``fill``. The caller holds the state lock."""
    symbol = fill.symbol
    shares = float(Decimal(fill.quantity))
    price = float(Decimal(fill.price))
    notional = shares * price

    if fill.action == "BUY":
        # A cash floor, absent until 14 March 2026: a runaway loop of sixty GLD
        # buys took a $100M book to -$54,785,875.20 (the aureon_state_persist.*
        # snapshots at the repository root). A BUY that cannot be paid for is
        # refused whole, never partially booked.
        available_cash = state.get("cash", 0.0)
        if notional > available_cash:
            return False, (
                f"BUY blocked - notional {notional:,.2f} exceeds available "
                f"cash {available_cash:,.2f}. A purchase that cannot be "
                f"funded is not booked and is not partially booked."
            )
        state.setdefault("positions", []).append({
            "symbol":      symbol,
            "asset_class": fill.asset_class,
            "shares":      shares,
            "cost":        round(price, 2),
            "agent":       "THIFUR_H",
        })
        state["cash"] = available_cash - notional
        return True, None

    positions = state.get("positions", [])
    available = sum(p.get("shares", 0) for p in positions if p["symbol"] == symbol)
    if available < shares:
        return False, (
            f"SELL blocked — available {symbol} shares {available:,.0f} "
            f"< requested {shares:,.0f}"
        )
    remaining = shares
    new_positions = []
    for pos in positions:
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
    state["cash"] = state.get("cash", 0.0) + notional
    return True, None


def book_fill(
    state: dict[str, Any],
    fill: PaperFill,
    release: ReleaseAuthorized,
    *,
    decision: Mapping[str, Any],
    on_break: Callable[[dict[str, Any]], None] | None = None,
) -> BookingOutcome:
    """Book ``fill`` for ``release``. The caller holds the state lock."""
    booked = state.setdefault("booked_fill_ids", [])
    if fill.fill_id in booked:
        return BookingOutcome("DUPLICATE", fill.fill_id, None, None, [], None)
    if fill.release_id != release.release_id or fill.decision_id != release.decision_id:
        return BookingOutcome(
            "REFUSED", fill.fill_id, None,
            f"fill {fill.fill_id} is for release {fill.release_id}, not {release.release_id}",
            [], None,
        )

    portfolio_before = {
        "portfolio_value": state.get("portfolio_value", 0.0),
        "cash":            state.get("cash", 0.0),
        "drawdown":        state.get("drawdown", 0.0),
        "n_positions":     len(state.get("positions", [])),
    }
    ok, error = _apply_fill(state, fill)
    reconciliation = compare_intent_with_execution(
        {"symbol": release.symbol, "action": release.action,
         "shares": release.quantity, "intended_price": release.reference_price,
         "notional": release.notional},
        {"symbol": fill.symbol, "action": fill.action, "shares": fill.quantity,
         "price": fill.price, "notional": fill.notional},
    )
    if not ok:
        brk = {
            "type": "BOOKING_REFUSED", "fill_id": fill.fill_id,
            "release_id": release.release_id, "decision_id": release.decision_id,
            "error": error, "ts": fill.filled_at.isoformat(),
        }
        state.setdefault("booking_breaks", []).insert(0, brk)
        if on_break is not None:
            on_break(brk)
        return BookingOutcome("REFUSED", fill.fill_id, None, error, reconciliation,
                              portfolio_before)

    booked.append(fill.fill_id)
    del booked[:-MAX_BOOKED_FILL_IDS]
    trade = {
        **dict(decision),
        "status":             "FILLED",
        "exec_price":         round(float(Decimal(fill.price)), 2),
        "shares":             float(Decimal(fill.quantity)),
        "notional":           round(float(Decimal(fill.notional)), 2),
        "authority_hash":     release.authority_hash,
        "final_approvals":    list(release.approvals),
        "release_target":     release.release_target,
        "release_id":         release.release_id,
        "release_outcome":    "FILLED",
        "fill_id":            fill.fill_id,
        "venue":              fill.venue,
        "provenance":         fill.provenance.value,
        # How the price was obtained, not only when (W2-ADD-03). A trade booked
        # at a simulated price says so on the record.
        "price_source":       fill.price_source,
        "price_observed_at":  fill.price_observed_at.isoformat(),
        "reconciliation":     "MATCHED" if not reconciliation else "DISCREPANCY",
        "ts":                 fill.filled_at.isoformat(),
    }
    state.setdefault("trades", []).insert(0, trade)
    if reconciliation:
        brk = {
            "type": "EXECUTION_DISCREPANCY", "fill_id": fill.fill_id,
            "release_id": release.release_id, "decision_id": release.decision_id,
            "mismatches": reconciliation, "ts": fill.filled_at.isoformat(),
        }
        state.setdefault("booking_breaks", []).insert(0, brk)
        if on_break is not None:
            on_break(brk)
    return BookingOutcome("BOOKED", fill.fill_id, trade, None, reconciliation, portfolio_before)
