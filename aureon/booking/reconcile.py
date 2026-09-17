"""
aureon.booking.reconcile
========================
Compare what was authorized with what independently executed (AUR-I-06).

Before Wave 2 the C2 lifecycle built its execution confirmation from the
approved decision and reconciled it against the same decision, so it could
never find a difference. The execution side now comes from a venue fill.

Symbol, action and quantity must match exactly. Price and notional are
compared with a tolerance, because a market fill legitimately differs from the
reference price the decision carried; a move beyond the tolerance is a break.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

__all__ = ["PRICE_TOLERANCE_BPS", "compare_intent_with_execution"]

#: 2% — wider than a normal paper fill's drift from a decision priced minutes
#: earlier, narrow enough to catch a wrong instrument price or a stale intent.
PRICE_TOLERANCE_BPS = 200

EXACT_FIELDS = ("symbol", "action", "shares")
TOLERANCE_FIELDS = (("price", "intended_price"), ("notional", "notional"))


def _number(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _same(intent: Any, executed: Any) -> bool:
    a, b = _number(intent), _number(executed)
    if a is not None and b is not None:
        return a == b
    return intent == executed


def compare_intent_with_execution(
    intent: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    tolerance_bps: int = PRICE_TOLERANCE_BPS,
) -> list[dict[str, Any]]:
    """Differences between ``intent`` and ``execution``; empty when they reconcile.

    ``intent`` uses the DSORIntent field names (``intended_price``); ``execution``
    uses ExecutionConfirmation's (``price``). A missing execution value is a
    difference; a missing intent price or notional has nothing to compare.
    """
    mismatches: list[dict[str, Any]] = []
    for field in EXACT_FIELDS:
        if not _same(intent.get(field), execution.get(field)):
            mismatches.append({"field": field, "expected": intent.get(field),
                               "actual": execution.get(field)})
    for exec_field, intent_field in TOLERANCE_FIELDS:
        expected = _number(intent.get(intent_field))
        actual = _number(execution.get(exec_field))
        if expected is None or expected == 0:
            continue
        if actual is None:
            mismatches.append({"field": exec_field, "expected": intent.get(intent_field),
                               "actual": execution.get(exec_field)})
            continue
        deviation_bps = abs(actual - expected) / abs(expected) * 10_000
        if deviation_bps > tolerance_bps:
            mismatches.append({
                "field": exec_field,
                "expected": intent.get(intent_field),
                "actual": execution.get(exec_field),
                "deviation_bps": float(round(deviation_bps, 1)),
                "tolerance_bps": tolerance_bps,
            })
    return mismatches
