"""
aureon.integration_adapters.oms_adapter
========================================
Order Management System (OMS) adapter for Aureon Grid 3.

In production this would connect to the prime broker's FIX gateway or
REST OMS API.  In the current prototype it logs the release packet and
returns a simulated acknowledgement.
"""


def send(packet: dict) -> dict:
    """
    Dispatch a governed release packet to the OMS.

    Parameters
    ----------
    packet : dict
        The release packet built by release_control.release_to_oms().

    Returns
    -------
    dict
        Simulated OMS acknowledgement with status and order reference.
    """
    decision_id = packet.get("decision_id", "UNKNOWN")
    symbol      = packet.get("symbol", "UNKNOWN")
    action      = packet.get("action", "UNKNOWN")
    notional    = packet.get("notional", 0)

    print(
        f"[OMS] Release received — {action} {symbol} "
        f"${notional:,.0f} | decision: {decision_id}"
    )

    # Simulated OMS acknowledgement
    return {
        "oms_status":   "ACCEPTED",
        "order_ref":    f"OMS-{decision_id[-8:]}",
        "decision_id":  decision_id,
        "symbol":       symbol,
        "action":       action,
        "notional":     notional,
    }
