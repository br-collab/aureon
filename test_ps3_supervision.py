from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from aureon.agents.jtac.aml_case_advisory import draft_case_narrative
from aureon.agents.jtac.equities_surveillance import EquityOrderFill, screen_equities
from aureon.agents.ranger.reg_reporting import RegReporting


def record(
    order_id: str,
    side: str,
    owner: str | None,
    *,
    minute: int = 30,
    volume: str = "1",
    price: str = "100",
    close: str = "100",
) -> EquityOrderFill:
    return EquityOrderFill(
        order_id, side, owner, datetime(2026, 11, 18, 20, minute, tzinfo=UTC),
        Decimal(price), Decimal(close), Decimal(volume), "SYNTHETIC-ABC", Decimal(10),
    )


def test_equities_wash_pair_is_flagged_for_human() -> None:
    result = screen_equities((record("B", "BUY", "OWNER-1"), record("S", "SELL", "OWNER-1")))
    assert result.disposition == "SURVEIL_PATTERN_ESCALATE"
    assert result.matched == ("WASH_TRADE",)
    assert result.human_review_required


def test_equities_marking_close_is_flagged() -> None:
    result = screen_equities(
        (record("B", "BUY", "OWNER-1", minute=59, volume="25", price="101", close="100"),)
    )
    assert result.matched == ("MARKING_THE_CLOSE",)
    assert result.human_review_required


def test_surveillance_missing_beneficial_owner_is_data_incomplete() -> None:
    result = screen_equities((record("B", "BUY", None),))
    assert result.disposition == "SURVEIL_DATA_INCOMPLETE"
    assert result.missing == ("beneficial_owner_id",)


def test_empty_surveillance_is_data_incomplete() -> None:
    assert screen_equities(()).disposition == "SURVEIL_DATA_INCOMPLETE"


def test_wash_match_requires_symbol_time_and_quantity() -> None:
    buy = record("B", "BUY", "OWNER-1")
    wrong_symbol = replace(record("S", "SELL", "OWNER-1"), symbol="SYNTHETIC-OTHER")
    assert "WASH_TRADE" not in screen_equities((buy, wrong_symbol)).matched


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
