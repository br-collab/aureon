from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from aureon.agents.jtac.aml_case_advisory import draft_case_narrative
from aureon.agents.jtac.equities_surveillance import SurveillanceResult
from aureon.agents.ranger.reg_reporting import RegReporting
from test_ps3d_lc_export import Fill, Sources, screen, write_sources


def record(
    order_id: str,
    side: str,
    owner: str | None,
    *,
    minute: int = 30,
    volume: str = "1",
    price: str = "100",
    close: str = "100",
) -> Fill:
    return Fill(
        order_id,
        side,
        owner,
        datetime(2026, 11, 18, 20, minute, tzinfo=UTC),
        price=Decimal(price),
        close=Decimal(close),
        volume_percent=Decimal(volume),
    )


def _export(directory: Path, name: str, records: tuple[Fill, ...]) -> Sources:
    return write_sources(directory, name.removesuffix(".json"), records)


def screen_equities(sources: Sources) -> SurveillanceResult:
    return screen(sources)


def test_equities_wash_pair_is_flagged_for_human(tmp_path: Path) -> None:
    export = _export(
        tmp_path, "wash.json", (record("B", "BUY", "OWNER-1"), record("S", "SELL", "OWNER-1"))
    )
    result = screen_equities(export)
    assert result.disposition == "SURVEIL_PATTERN_ESCALATE"
    assert result.matched == ("WASH_TRADE",)
    assert result.human_review_required


def test_equities_marking_close_is_flagged(tmp_path: Path) -> None:
    export = _export(
        tmp_path,
        "close.json",
        (record("B", "BUY", "OWNER-1", minute=59, volume="25", price="101", close="100"),),
    )
    result = screen_equities(export)
    assert result.matched == ("MARKING_THE_CLOSE",)
    assert result.human_review_required


def test_surveillance_missing_beneficial_owner_is_data_incomplete(tmp_path: Path) -> None:
    result = screen_equities(_export(tmp_path, "owner.json", (record("B", "BUY", None),)))
    assert result.disposition == "SURVEIL_DATA_INCOMPLETE"
    assert result.missing == ("beneficial_owner_id",)


def test_empty_surveillance_is_data_incomplete(tmp_path: Path) -> None:
    assert screen_equities(_export(tmp_path, "empty.json", ())).disposition == (
        "SURVEIL_DATA_INCOMPLETE"
    )


def test_wash_match_requires_symbol_time_and_quantity(tmp_path: Path) -> None:
    buy = record("B", "BUY", "OWNER-1")
    wrong_symbol = replace(record("S", "SELL", "OWNER-1"), symbol="SYNTHETIC-OTHER")
    export = _export(tmp_path, "symbol.json", (buy, wrong_symbol))
    assert "WASH_TRADE" not in screen_equities(export).matched


def _at(when: datetime, **changes: object) -> Fill:
    base = record("B", "BUY", "OWNER-1", volume="25", price="101", close="100")
    return replace(base, filled_at=when, **changes)


def test_marking_the_close_uses_the_early_close_on_27_november_2026(tmp_path: Path) -> None:
    # 12:58 New York time: two minutes before the 1:00 p.m. early close (NYSE calendar).
    early = screen_equities(
        _export(tmp_path, "early.json", (_at(datetime(2026, 11, 27, 17, 58, tzinfo=UTC)),))
    )
    assert early.matched == ("MARKING_THE_CLOSE",)
    # The same clock time on a regular day is three hours before the close.
    regular = screen_equities(
        _export(tmp_path, "regular.json", (_at(datetime(2026, 11, 25, 17, 58, tzinfo=UTC)),))
    )
    assert "MARKING_THE_CLOSE" not in regular.matched


def test_missing_symbol_or_quantity_is_data_incomplete_not_a_wash(tmp_path: Path) -> None:
    blank = screen_equities(
        _export(
            tmp_path,
            "blank.json",
            (
                replace(record("B", "BUY", "OWNER-1"), symbol=None, quantity=None),
                replace(record("S", "SELL", "OWNER-1"), symbol=None, quantity=None),
            ),
        )
    )
    assert blank.disposition == "SURVEIL_DATA_INCOMPLETE"
    assert blank.missing == ("symbol", "quantity")


def test_a_day_outside_the_calendar_is_data_incomplete(tmp_path: Path) -> None:
    result = screen_equities(
        _export(tmp_path, "year.json", (_at(datetime(2031, 3, 3, 20, 58, tzinfo=UTC)),))
    )
    assert result.disposition == "SURVEIL_DATA_INCOMPLETE"
    assert result.missing == ("session_close",)


def test_aml_agent_output_is_advisory_without_decision() -> None:
    draft = draft_case_narrative(case_id="CASE-1", alert_facts=("fact one", "fact two"))
    assert draft.label == "ADVISORY_DRAFT_NOT_A_DECISION"
    assert draft.decision is None


def test_aureon_cat_stub_never_returns_ready() -> None:
    agent = RegReporting({}, __import__("threading").Lock())
    result = agent.process_cat_event({"event_type": "NEW_ORDER", "order_id": "O1"})
    assert result["submission_status"] == "NOT_VALIDATED"
    assert result["deprecated"] is True
    assert result["validator_owner"] == "L.C."


def test_cftc_part45_is_not_validated() -> None:
    agent = RegReporting({}, __import__("threading").Lock())
    result = agent.generate_cftc_part45_report({"id": "SYNTHETIC-SWAP-1"})
    assert result["submission_status"] == "NOT_VALIDATED"
