"""Equities surveillance using Aureon's existing disposition ladder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from aureon.agents.jtac.market_calendar import (
    CalendarIndeterminateError,
    load_us_equities_calendar,
)

NEW_YORK = ZoneInfo("America/New_York")


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


def screen_equities(
    records: tuple[EquityOrderFill, ...],
    *,
    close_window_seconds: int = 300,
    close_volume_threshold: Decimal = Decimal(20),
) -> SurveillanceResult:
    if not records:
        return SurveillanceResult("SURVEIL_DATA_INCOMPLETE", (), ("records",), True)
    missing = []
    if any(item.beneficial_owner_id is None for item in records):
        missing.append("beneficial_owner_id")
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
