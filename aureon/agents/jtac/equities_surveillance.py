"""Equities surveillance using Aureon's existing disposition ladder.

Phase A. Surveillance reads three named sources and nothing a caller assembles:

1. the L.C. (Legiones Cannenses) lifecycle export, ``lc.lifecycle_export/1``, written by
   ``lc.lifecycle_export`` from a sealed lifecycle register (order, account, symbol, side,
   quantity, price, fill time, and the venue event's provenance);
2. a close reference, ``aureon.close_reference/1``: the official close price and the
   session's total traded volume per symbol and session date, with its source named;
3. an account owner record, ``aureon.account_owners/1``: the beneficial owner of each account,
   with its source named.

Close price, session volume and beneficial owner are not L.C. facts, so the export does not
carry them. Anything missing or malformed in any source is ``SURVEIL_DATA_INCOMPLETE`` with
the missing item named, never a crash and never a clear. No run writes these files yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from aureon.agents.jtac.market_calendar import (
    CalendarIndeterminateError,
    load_us_equities_calendar,
)

NEW_YORK = ZoneInfo("America/New_York")

LC_EXPORT_SCHEMA = "lc.lifecycle_export/1"
CLOSE_REFERENCE_SCHEMA = "aureon.close_reference/1"
ACCOUNT_OWNERS_SCHEMA = "aureon.account_owners/1"
#: The row L.C. writes (``lc/lifecycle_export.py``). A row with any other shape is refused.
LC_EXPORT_ROW_FIELDS = frozenset(
    {
        "order_id",
        "parent_order_id",
        "account_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "venue",
        "filled_at",
        "execution_id",
        "event_digest",
        "provenance",
    }
)
_OBSERVED = frozenset({"FACT_EXTERNAL", "FACT_SYNTHETIC"})


@dataclass(frozen=True, slots=True)
class EquityOrderFill:
    order_id: str
    side: str
    beneficial_owner_id: str | None
    filled_at: datetime
    price: Decimal
    close_price: Decimal
    session_volume_percent: Decimal
    symbol: str | None = None
    quantity: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SurveillanceResult:
    disposition: str
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    human_review_required: bool


class _Incomplete(Exception):
    def __init__(self, *missing: str) -> None:
        super().__init__(", ".join(missing))
        self.missing = missing


def _document(path: Path, schema: str, name: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise _Incomplete(name) from error
    if not isinstance(document, dict) or document.get("schema") != schema:
        raise _Incomplete(name)
    return document


def _decimal(value: object, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise _Incomplete(name) from error
    if not number.is_finite():
        raise _Incomplete(name)
    return number


def _close_reference(path: Path) -> dict[tuple[str, date], tuple[Decimal, Decimal]]:
    document = _document(path, CLOSE_REFERENCE_SCHEMA, "close_reference")
    if not document.get("source") or document.get("provenance") not in _OBSERVED:
        raise _Incomplete("close_reference")
    sessions = document.get("sessions")
    if not isinstance(sessions, list):
        raise _Incomplete("close_reference")
    reference: dict[tuple[str, date], tuple[Decimal, Decimal]] = {}
    for row in sessions:
        try:
            key = (str(row["symbol"]), date.fromisoformat(str(row["session_date"])))
        except (KeyError, TypeError, ValueError) as error:
            raise _Incomplete("close_reference") from error
        reference[key] = (
            _decimal(row.get("close_price"), "close_price"),
            _decimal(row.get("session_volume"), "session_volume"),
        )
    return reference


def _account_owners(path: Path) -> dict[str, str]:
    document = _document(path, ACCOUNT_OWNERS_SCHEMA, "account_owners")
    accounts = document.get("accounts")
    if not document.get("source") or not isinstance(accounts, dict):
        raise _Incomplete("account_owners")
    return {str(account): str(owner) for account, owner in accounts.items() if owner}


def _records(
    export: Path, close_reference: Path, account_owners: Path
) -> tuple[EquityOrderFill, ...]:
    document = _document(export, LC_EXPORT_SCHEMA, "lc_export")
    rows = document.get("executions")
    if not isinstance(rows, list):
        raise _Incomplete("lc_export")
    reference = _close_reference(close_reference)
    owners = _account_owners(account_owners)
    records: list[EquityOrderFill] = []
    missing: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != LC_EXPORT_ROW_FIELDS:
            raise _Incomplete("lc_export_row")
        if row["provenance"] not in _OBSERVED:
            raise _Incomplete("provenance")
        try:
            filled_at = datetime.fromisoformat(str(row["filled_at"]))
        except ValueError as error:
            raise _Incomplete("filled_at") from error
        if filled_at.tzinfo is None:
            raise _Incomplete("filled_at")
        symbol = str(row["symbol"]) or None
        quantity = _decimal(row["quantity"], "quantity") if row["quantity"] else None
        owner = owners.get(str(row["account_id"]))
        if owner is None:
            missing.append("beneficial_owner_id")
        session = (
            reference.get((symbol, filled_at.astimezone(NEW_YORK).date())) if symbol else None
        )
        if symbol and session is None:
            missing.append("close_price")
        close_price, session_volume = session or (Decimal(0), Decimal(0))
        if session is not None and session_volume <= 0:
            missing.append("session_volume")
        share = (
            quantity / session_volume * 100
            if quantity is not None and session_volume > 0
            else Decimal(0)
        )
        records.append(
            EquityOrderFill(
                order_id=str(row["order_id"]),
                side=str(row["side"]),
                beneficial_owner_id=owner,
                filled_at=filled_at,
                price=_decimal(row["price"], "price"),
                close_price=close_price,
                session_volume_percent=share,
                symbol=symbol,
                quantity=quantity,
            )
        )
    if missing:
        raise _Incomplete(*dict.fromkeys(missing))
    return tuple(records)


def screen_equities(
    export: Path,
    *,
    close_reference: Path,
    account_owners: Path,
    close_window_seconds: int = 300,
    close_volume_threshold: Decimal = Decimal(20),
) -> SurveillanceResult:
    """Screen one L.C. lifecycle export against the named close and owner sources."""

    try:
        records = _records(export, close_reference, account_owners)
    except _Incomplete as incomplete:
        return SurveillanceResult("SURVEIL_DATA_INCOMPLETE", (), incomplete.missing, True)
    if not records:
        return SurveillanceResult("SURVEIL_DATA_INCOMPLETE", (), ("records",), True)
    missing = []
    if any(not item.symbol for item in records):
        missing.append("symbol")
    if any(item.quantity is None or item.quantity <= 0 for item in records):
        missing.append("quantity")
    calendar = load_us_equities_calendar()
    closes: list[datetime] = []
    for item in records:
        local_day = item.filled_at.astimezone(NEW_YORK).date()
        try:
            closes.append(
                datetime.combine(local_day, calendar.session_close(local_day), tzinfo=NEW_YORK)
            )
        except (CalendarIndeterminateError, ValueError):
            missing.append("session_close")
            break
    if missing:
        return SurveillanceResult("SURVEIL_DATA_INCOMPLETE", (), tuple(missing), True)

    matched = []
    buys = [item for item in records if item.side == "BUY"]
    sells = [item for item in records if item.side == "SELL"]
    if any(
        buy.beneficial_owner_id == sell.beneficial_owner_id
        and buy.symbol == sell.symbol
        and buy.quantity == sell.quantity
        and abs((buy.filled_at - sell.filled_at).total_seconds()) <= 300
        for buy in buys
        for sell in sells
    ):
        matched.append("WASH_TRADE")

    if any(
        0
        <= (close - item.filled_at.astimezone(NEW_YORK)).total_seconds()
        <= close_window_seconds
        and item.session_volume_percent >= close_volume_threshold
        and item.price != item.close_price
        for item, close in zip(records, closes, strict=True)
    ):
        matched.append("MARKING_THE_CLOSE")

    if matched:
        return SurveillanceResult("SURVEIL_PATTERN_ESCALATE", tuple(matched), (), True)
    return SurveillanceResult("SURVEIL_CLEAR", (), (), False)
