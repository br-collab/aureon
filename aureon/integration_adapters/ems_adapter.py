"""EMS release boundary for specific desk configurations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_execution_release(decision: dict[str, Any], authority_hash: str) -> dict[str, Any]:
    """Build the EMS release packet when a desk executes directly from the EMS."""
    return {
        "handoff_type": "EMS_RELEASE",
        "decision_id": decision["id"],
        "symbol": decision["symbol"],
        "action": decision["action"],
        "shares": decision["shares"],
        "authority_hash": authority_hash,
        "release_ts": datetime.now(timezone.utc).isoformat(),
        "governed_release": True,
    }
