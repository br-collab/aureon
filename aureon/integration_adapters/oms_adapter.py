"""OMS handoff boundary for governed parent-order release."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_parent_order_handoff(decision: dict[str, Any], authority_hash: str) -> dict[str, Any]:
    """Build the governed OMS handoff packet for a Phase 1 parent-order release."""
    return {
        "handoff_type": "OMS_PARENT_ORDER",
        "decision_id": decision["id"],
        "symbol": decision["symbol"],
        "action": decision["action"],
        "shares": decision["shares"],
        "notional": decision["notional"],
        "authority_hash": authority_hash,
        "release_ts": datetime.now(timezone.utc).isoformat(),
        "governed_release": True,
    }


def send(decision: dict[str, Any], authority_hash: str) -> dict[str, Any]:
    """
    Prototype OMS send boundary.
    In Phase 1 this returns the governed parent-order handoff payload that
    would be transmitted to the OMS adapter layer.
    """
    return build_parent_order_handoff(decision, authority_hash)
