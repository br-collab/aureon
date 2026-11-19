"""Equities surveillance using Aureon's existing disposition ladder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class EquityOrderFill:
    order_id: str
    side: str
    beneficial_owner_id: str | None
    filled_at: datetime
    price: Decimal
    close_price: Decimal
    session_volume_percent: Decimal
    symbol: str = "SYNTHETIC-UNKNOWN"
    quantity: Decimal = Decimal(0)


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
        0 <= (
            datetime.combine(
                item.filled_at.astimezone(ZoneInfo("America/New_York")).date(),
                time(16, 0),
                tzinfo=ZoneInfo("America/New_York"),
            )
            - item.filled_at.astimezone(ZoneInfo("America/New_York"))
        ).total_seconds()
        <= close_window_seconds
        and item.session_volume_percent >= close_volume_threshold
        and item.price != item.close_price
        for item in records
    ):
        matched.append("MARKING_THE_CLOSE")

    if matched:
        return SurveillanceResult("SURVEIL_PATTERN_ESCALATE", tuple(matched), (), True)
    return SurveillanceResult("SURVEIL_CLEAR", (), (), False)
