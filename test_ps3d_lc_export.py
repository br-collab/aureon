"""PS-3D Part 7: equities surveillance reads the L.C. lifecycle export and named sources.

L.C. is Legiones Cannenses. Gate G3 finding H3 (21 Nov 2026): the first Part 7 read an
export L.C. never wrote, carrying close price, session volume and beneficial owner, none of
which L.C. records. The export now has exactly the row L.C. writes
(``lc/lifecycle_export.py``); close price and session volume come from a close reference and
the owner from an account record. A missing or malformed source is DATA_INCOMPLETE, by name.
Phase A: no run writes these files yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from aureon.agents.jtac.equities_surveillance import (
    LC_EXPORT_ROW_FIELDS,
    SurveillanceResult,
    screen_equities,
)

CONTROL_WASH = "wash trade beneficial owner control"
CONTROL_OWNER = "beneficial owner data incomplete control"
CONTROL_SOURCE = "surveillance named source control"


@dataclass(frozen=True)
class Fill:
    """One fill as the scenario needs it; the helper splits it across the three sources."""

    order_id: str
    side: str
    owner: str | None
    filled_at: datetime
    price: Decimal = Decimal(100)
    close: Decimal = Decimal(100)
    volume_percent: Decimal = Decimal(1)
    symbol: str | None = "SYNTHETIC-ABC"
    quantity: Decimal | None = Decimal(10)


@dataclass(frozen=True)
class Sources:
    export: Path
    close_reference: Path
    account_owners: Path


def lc_row(fill: Fill) -> dict[str, str]:
    """The row ``lc.lifecycle_export.export_executions`` writes, and nothing else."""

    return {
        "order_id": fill.order_id,
        "parent_order_id": "",
        "account_id": f"ACCT-{fill.order_id}",
        "symbol": fill.symbol or "",
        "side": fill.side,
        "quantity": "" if fill.quantity is None else str(fill.quantity),
        "price": str(fill.price),
        "venue": "SYNTHETIC-VENUE",
        "filled_at": fill.filled_at.isoformat(),
        "execution_id": f"EXE-{fill.order_id}",
        "event_digest": "sha256:" + "0" * 64,
        "provenance": "FACT_SYNTHETIC",
    }


def write_sources(directory: Path, name: str, fills: tuple[Fill, ...]) -> Sources:
    directory.mkdir(parents=True, exist_ok=True)
    rows = [lc_row(fill) for fill in fills]
    assert all(set(row) == LC_EXPORT_ROW_FIELDS for row in rows)
    sessions: dict[tuple[str, str], dict[str, str]] = {}
    for fill in fills:
        if fill.symbol is None:
            continue
        day = fill.filled_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        quantity = fill.quantity or Decimal(1)
        sessions.setdefault(
            (fill.symbol, day),
            {
                "symbol": fill.symbol,
                "session_date": day,
                "close_price": str(fill.close),
                "session_volume": str(quantity * 100 / fill.volume_percent),
            },
        )
    export = directory / f"{name}-export.json"
    export.write_text(
        json.dumps({"schema": "lc.lifecycle_export/1", "executions": rows}), encoding="utf-8"
    )
    close_reference = directory / f"{name}-close.json"
    close_reference.write_text(
        json.dumps(
            {
                "schema": "aureon.close_reference/1",
                "source": "synthetic official close file",
                "provenance": "FACT_SYNTHETIC",
                "sessions": list(sessions.values()),
            }
        ),
        encoding="utf-8",
    )
    account_owners = directory / f"{name}-owners.json"
    account_owners.write_text(
        json.dumps(
            {
                "schema": "aureon.account_owners/1",
                "source": "synthetic account master",
                "accounts": {
                    f"ACCT-{fill.order_id}": fill.owner for fill in fills if fill.owner
                },
            }
        ),
        encoding="utf-8",
    )
    return Sources(export, close_reference, account_owners)


def screen(sources: Sources) -> SurveillanceResult:
    return screen_equities(
        sources.export,
        close_reference=sources.close_reference,
        account_owners=sources.account_owners,
    )


NOON = datetime(2026, 11, 18, 17, 0, tzinfo=UTC)


def test_a_planted_wash_pair_in_the_lc_export_is_flagged(tmp_path: Path) -> None:
    sources = write_sources(
        tmp_path, "wash", (Fill("B", "BUY", "OWNER-1", NOON), Fill("S", "SELL", "OWNER-1", NOON))
    )
    result = screen(sources)
    assert result.disposition == "SURVEIL_PATTERN_ESCALATE", CONTROL_WASH
    assert result.matched == ("WASH_TRADE",), CONTROL_WASH


def test_an_account_missing_from_the_owner_record_is_data_incomplete(tmp_path: Path) -> None:
    sources = write_sources(tmp_path, "owner", (Fill("B", "BUY", None, NOON),))
    result = screen(sources)
    assert result.disposition == "SURVEIL_DATA_INCOMPLETE", CONTROL_OWNER
    assert result.missing == ("beneficial_owner_id",), CONTROL_OWNER


def test_a_caller_built_row_with_fields_lc_does_not_write_is_refused(tmp_path: Path) -> None:
    sources = write_sources(tmp_path, "forged", (Fill("B", "BUY", "OWNER-1", NOON),))
    document = json.loads(sources.export.read_text(encoding="utf-8"))
    document["executions"][0]["close_price"] = "100"
    sources.export.write_text(json.dumps(document), encoding="utf-8")
    result = screen(sources)
    assert result.disposition == "SURVEIL_DATA_INCOMPLETE", CONTROL_SOURCE
    assert result.missing == ("lc_export_row",), CONTROL_SOURCE


def test_a_fill_without_a_close_reference_session_is_data_incomplete(tmp_path: Path) -> None:
    sources = write_sources(tmp_path, "close", (Fill("B", "BUY", "OWNER-1", NOON),))
    document = json.loads(sources.close_reference.read_text(encoding="utf-8"))
    document["sessions"] = []
    sources.close_reference.write_text(json.dumps(document), encoding="utf-8")
    result = screen(sources)
    assert result.disposition == "SURVEIL_DATA_INCOMPLETE", CONTROL_SOURCE
    assert result.missing == ("close_price",), CONTROL_SOURCE


def test_a_forecast_is_not_an_execution(tmp_path: Path) -> None:
    sources = write_sources(tmp_path, "forecast", (Fill("B", "BUY", "OWNER-1", NOON),))
    document = json.loads(sources.export.read_text(encoding="utf-8"))
    document["executions"][0]["provenance"] = "FORECAST"
    sources.export.write_text(json.dumps(document), encoding="utf-8")
    result = screen(sources)
    assert result.missing == ("provenance",), CONTROL_SOURCE


def test_an_unreadable_export_is_data_incomplete_not_a_crash(tmp_path: Path) -> None:
    sources = write_sources(tmp_path, "broken", (Fill("B", "BUY", "OWNER-1", NOON),))
    sources.export.write_text("not json", encoding="utf-8")
    result = screen(sources)
    assert result.disposition == "SURVEIL_DATA_INCOMPLETE", CONTROL_SOURCE
    assert result.missing == ("lc_export",), CONTROL_SOURCE
