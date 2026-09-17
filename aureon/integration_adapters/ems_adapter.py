"""
aureon.integration_adapters.ems_adapter
========================================
Execution Management System (EMS) adapter for Aureon Grid 3.

In production this would connect to an algorithmic execution venue
(e.g. Bloomberg EMSX, Fidessa, or a direct DMA gateway).  In the
current prototype it builds a structured execution release packet
and returns it for storage in integration_handoffs.
"""

from datetime import datetime, timezone


def build_execution_release(decision, authority_hash: str, approved_intent: dict | None = None) -> dict:
    """
    Build a governed execution release packet for the EMS.

    Parameters
    ----------
    decision : dict
        The approved pending decision.
    authority_hash : str
        SHA-256 authority hash stamped at approval.
    approved_intent : dict, optional
        The sealed ApprovedIntentEnvelope (JSON form), carried unchanged with
        its digest (W2B-5).

    Returns
    -------
    dict
        Structured EMS release packet.
    """
    ts = datetime.now(timezone.utc).isoformat()

    packet = {
        "type":           "EMS_RELEASE",
        "decision_id":    decision.get("id", ""),
        "action":         decision.get("action", ""),
        "symbol":         decision.get("symbol", ""),
        "asset_class":    decision.get("asset_class", ""),
        "shares":         decision.get("shares", 0),
        "price":          decision.get("price", 0.0),
        "notional":       decision.get("notional", 0),
        "product_type":   decision.get("product_type", ""),
        "authority_hash": authority_hash,
        "release_target": "EMS",
        "algo":           "VWAP",          # default execution algorithm
        "urgency":        "NORMAL",
        "ts":             ts,
        "status":         "SENT",
    }
    if approved_intent is not None:
        packet["approved_intent"]        = approved_intent
        packet["approved_intent_digest"] = approved_intent["digest"]

    print(
        f"[EMS] Execution release — {packet['action']} {packet['symbol']} "
        f"${packet['notional']:,.0f} | decision: {packet['decision_id']}"
    )

    return packet
