"""
aureon.integration_adapters.fix_adapter
========================================
FIX 4.4 protocol adapter for Aureon Grid 3.

In production this would connect to the prime broker's FIX gateway
using a FIX engine (e.g. QuickFIX/n).  In the current prototype it
provides structured FIX message builders for audit and logging.
"""

from datetime import datetime, timezone


def build_new_order_single(decision: dict, exec_price: float) -> dict:
    """
    Build a FIX 4.4 NewOrderSingle (MsgType=D) message dict.

    Parameters
    ----------
    decision : dict
        The approved pending decision.
    exec_price : float
        Limit price for the order.

    Returns
    -------
    dict
        FIX tag-value pairs as a Python dict.
    """
    SIDE_MAP = {"BUY": "1", "SELL": "2"}
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S.%f")[:-3]

    return {
        "8":   "FIX.4.4",                          # BeginString
        "35":  "D",                                 # MsgType = NewOrderSingle
        "49":  "AUREON",                            # SenderCompID
        "56":  "BROKER",                            # TargetCompID
        "11":  decision.get("id", ""),              # ClOrdID
        "55":  decision.get("symbol", ""),          # Symbol
        "54":  SIDE_MAP.get(decision.get("action", "BUY"), "1"),  # Side
        "38":  str(decision.get("shares", 0)),      # OrderQty
        "44":  str(round(exec_price, 4)),           # Price
        "40":  "2",                                 # OrdType = Limit
        "59":  "0",                                 # TimeInForce = Day
        "60":  ts,                                  # TransactTime
        "167": decision.get("fix_type", ""),        # SecurityType
        "460": str(decision.get("fix_product", "")),# Product
    }


def send_order(fix_message: dict) -> dict:
    """
    Simulate sending a FIX order to the gateway.

    Returns a simulated ExecutionReport (MsgType=8).
    """
    cl_ord_id = fix_message.get("11", "UNKNOWN")
    symbol    = fix_message.get("55", "UNKNOWN")
    print(f"[FIX] NewOrderSingle sent — ClOrdID: {cl_ord_id} | Symbol: {symbol}")

    return {
        "8":  "FIX.4.4",
        "35": "8",          # MsgType = ExecutionReport
        "11": cl_ord_id,
        "55": symbol,
        "39": "0",          # OrdStatus = New
        "150": "0",         # ExecType = New
        "17": f"EXEC-{cl_ord_id[-8:]}",
    }
