"""PS-3D Phase A: equities surveillance reads an L.C. lifecycle export.

L.C. is Legiones Cannenses. The run does not write this export yet.
That wiring is Phase B.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from aureon.agents.jtac.equities_surveillance import screen_equities

CONTROL_WASH = "wash trade beneficial owner control"
CONTROL_OWNER = "beneficial owner data incomplete control"


def _row(order_id: str, side: str, *, owner: str | None = "OWNER-1") -> dict[str, str]:
    row = {
        "order_id": order_id,
        "side": side,
        "filled_at": datetime(2026, 11, 18, 20, 30, tzinfo=UTC).isoformat(),
        "price": "100",
        "close_price": "100",
        "session_volume_percent": "1",
        "symbol": "SYNTHETIC-ABC",
        "quantity": "10",
    }
    if owner is not None:
        row["beneficial_owner_id"] = owner
    return row


def _export(path: Path, rows: list[dict[str, str]]) -> Path:
    path.write_text(
        json.dumps({"schema": "lc.lifecycle_export/1", "executions": rows}),
        encoding="utf-8",
    )
    return path


def test_lc_run_wash_pair_is_flagged_through_adapter(tmp_path: Path) -> None:
    export = _export(tmp_path / "wash.json", [_row("B", "BUY"), _row("S", "SELL")])
    result = screen_equities(export)
    assert result.disposition == "SURVEIL_PATTERN_ESCALATE", CONTROL_WASH
    assert result.matched == ("WASH_TRADE",), CONTROL_WASH


def test_lc_run_missing_beneficial_owner_is_data_incomplete(tmp_path: Path) -> None:
    export = _export(tmp_path / "missing.json", [_row("B", "BUY", owner=None)])
    result = screen_equities(export)
    assert result.disposition == "SURVEIL_DATA_INCOMPLETE", CONTROL_OWNER
    assert result.missing == ("beneficial_owner_id",), CONTROL_OWNER
