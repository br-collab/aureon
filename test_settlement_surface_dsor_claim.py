"""WP-6 (finding W2B7-V-01): the settlement surface may claim a DSOR record only where one exists.

DSOR = Decision System of Record.

Atreides v0.4.0 writes a DSOR record at emission and only at emission
(`emit_instruction_package`: "A quorum hold persists nothing, because no
instruction was issued"). Observed against the installed package:

    sub-material : emit_for_human_entry  dsor_record_id set
    material     : quorum_required_hold  dsor_record_id None
    gate held    : gate_held             dsor_record_id set

`atreides-settlement-dashboard.html` marked the DSOR phase "pass" and labelled it
"recorded" on **every** branch, and printed `DSOR ` with an empty identifier
beside that claim. Under Atreides v0.3.3 the identifier came from
`GateResult.dsor_pre_trade_record_id`, which existed for every validated
operation, so the label was true; PR #26 is what made it false.

**Why this shape of test.** aureon has no JavaScript rendering harness — no node
test runner, no jsdom — so a rendering assertion is not available. This is the
fallback AMD1 WP-6 item 3 allows, strengthened: rather than hardcoding what the
three dispositions do, it *executes* the cockpit to observe which of them write a
record, then reads the surface's own branches and requires the two to agree. If
Atreides changes which dispositions persist, this test follows.

Run: pytest -q test_settlement_surface_dsor_claim.py
"""

from __future__ import annotations

import pathlib
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from atreides.agents.tier1.outputs import SettlementKind, SettlementRail
from atreides.cockpit.clearing_cockpit import ClearingCockpit, PortalRegime
from atreides.contracts.dsor_stub import CAOMTier

DASHBOARD = pathlib.Path(__file__).parent / "atreides-settlement-dashboard.html"
MATERIAL_THRESHOLD = Decimal("50000000")

#: Words the surface uses to assert a record exists. "na" and a label that says
#: nothing was recorded are the honest forms when there is none.
CLAIM_STATUSES = {"pass"}


def _observe(amount: Decimal, *, clearing_fund_compliant: bool = True):
    """Run one real cockpit cycle and return (disposition, dsor_record_id)."""
    cockpit = ClearingCockpit()
    tasking = cockpit.capture_tasking(
        regime=PortalRegime.CCP,
        rail=SettlementRail.FICC_GSD_DVP,
        settlement_kind=SettlementKind.DVP,
        counterparty_id="CP-A",
        settlement_date=(datetime.now(timezone.utc) + timedelta(days=1)).date(),
        authority_id="operator-bill",
        authority_tier=CAOMTier.T1,
        cusip="912828XX",
        net_delivery_quantity=amount,
        net_payment_amount=amount,
        ficc_published_net_delivery=amount,
        intraday_credit_limit=Decimal("100000000000"),
        intraday_credit_current_usage=Decimal("1000000"),
        ficc_clearing_fund_compliant=clearing_fund_compliant,
    )
    gate = cockpit.run_validation_gates(tasking)
    package = cockpit.emit_instruction_package(tasking, gate)
    return package.disposition.value, package.dsor_record_id


@pytest.fixture(scope="module")
def observed() -> dict[str, object]:
    """What each disposition actually persists, measured, not assumed."""
    cases = {
        "sub_material": _observe(MATERIAL_THRESHOLD / 50),
        "material": _observe(MATERIAL_THRESHOLD * 2),
        "gate_held": _observe(MATERIAL_THRESHOLD / 50, clearing_fund_compliant=False),
    }
    return {name: {"disposition": d, "record": r} for name, (d, r) in cases.items()}


@pytest.fixture(scope="module")
def branches() -> dict[str, str]:
    """The three disposition branches of runLiveCycle, as source text."""
    source = DASHBOARD.read_text(encoding="utf-8")
    body = source[source.index("async function runLiveCycle("):]
    body = body[: body.index("\n}")]
    gate_held, rest = body.split("} else if(disp==='quorum_required_hold'){", 1)
    quorum, emitted = rest.split("} else {", 1)
    return {
        "gate_held": gate_held[gate_held.index("if(!passed){"):],
        "material": quorum,
        "sub_material": emitted[: emitted.index("liveRender(")],
    }


def _dsor_phase(branch: str) -> tuple[str, str]:
    """The DSOR phase status and label the surface sets in this branch."""
    status = re.search(r"st\[PIDX\['dsor'\]\]\s*=\s*'([^']*)'", branch)
    label = re.search(r"lb\[PIDX\['dsor'\]\]\s*=\s*'([^']*)'", branch)
    assert status and label, "the branch no longer sets the DSOR phase; update this test"
    return status.group(1), label.group(1)


def test_the_three_dispositions_are_what_we_think(observed) -> None:
    """Pins the premise. If Atreides changes this, the test below is reasoning from a stale map."""
    assert observed["sub_material"]["disposition"] == "emit_for_human_entry"
    assert observed["material"]["disposition"] == "quorum_required_hold"
    assert observed["gate_held"]["disposition"] == "gate_held"
    assert observed["sub_material"]["record"] is not None
    assert observed["material"]["record"] is None, (
        "a quorum hold issues no instruction, so nothing is persisted"
    )
    assert observed["gate_held"]["record"] is not None, (
        "a held gate persists its escalation, so 'escalation recorded' is true"
    )


@pytest.mark.parametrize("case", ["sub_material", "material", "gate_held"])
def test_the_surface_claims_a_record_only_where_one_is_written(observed, branches, case) -> None:
    status, label = _dsor_phase(branches[case])
    record_written = observed[case]["record"] is not None
    claims_record = status in CLAIM_STATUSES

    assert claims_record == record_written, (
        f"{case}: the dashboard sets the DSOR phase to {status!r} labelled {label!r}, "
        f"but Atreides wrote {'a record' if record_written else 'nothing'} "
        f"for disposition {observed[case]['disposition']!r}"
    )
    if not record_written:
        assert "recorded" not in label or "nothing recorded" in label, (
            f"{case}: the label {label!r} reads as a record that does not exist"
        )


def test_the_ledger_line_omits_the_identifier_when_there_is_no_record() -> None:
    """Never print `DSOR ` with nothing after it: an empty identifier beside a claim."""
    source = DASHBOARD.read_text(encoding="utf-8")
    ledger = source[source.index("const rid=(pkg.dsor_record_id"):]
    ledger = ledger[: ledger.index("ledger.insertBefore")]

    template = next(line for line in ledger.splitlines() if "li.innerHTML" in line)
    assert "DSOR ${rid}" not in template, (
        "the ledger line interpolates the identifier unconditionally, so a quorum hold "
        "prints 'DSOR ' with nothing after it"
    )
    segment = next(line for line in ledger.splitlines() if "dsorSeg" in line and "=" in line)
    assert re.search(r"\brid\s*\?", segment), (
        f"the DSOR segment is not conditional on a record: {segment.strip()}"
    )


# --- The `na` state, once introduced, has to be a state everywhere -------------
#
# WP-6 gave the DSOR phase a fourth status, `na`, for the quorum hold that records
# nothing. Both renderers suppressed it — `'stat '+(k==='na'?'':k)` — so it fell
# through to the base `.stat` colour, which is *brighter* than `.stat.idle`: a
# phase that recorded nothing read louder than one not yet reached. AMD3-1 noted
# the missing rule. These tests make the vocabulary and the styling agree, so the
# next status added is caught rather than silently unstyled.


def _status_vocabulary(source: str) -> set[str]:
    """The statuses `applyPhase` distinguishes — the surface's own definition."""
    body = source[source.index("function applyPhase("):]
    body = body[: body.index("\nfunction ", 1)]
    return set(re.findall(r"k===\s*'([a-z]+)'", body))


def test_every_status_the_surface_can_set_is_styled() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    vocabulary = _status_vocabulary(source) | {"idle"}
    assert "na" in vocabulary, "the not-applicable status is gone; update this test"
    missing = [k for k in sorted(vocabulary) if f".stat.{k}{{" not in source]
    assert missing == [], f"statuses with no .stat rule, so they render at base contrast: {missing}"


def test_the_status_reaches_the_element_as_a_class() -> None:
    """A rule is no use if the renderer drops the class before it is applied."""
    source = DASHBOARD.read_text(encoding="utf-8")
    assignments = re.findall(r"className\s*=\s*'stat '\s*\+\s*(.+?);", source)
    assert assignments, "no status class is assigned; update this test"
    for expression in assignments:
        assert "?" not in expression, (
            f"the status is filtered before it becomes a class: 'stat '+{expression}"
        )


def test_a_cleared_stage_drops_every_status_class() -> None:
    """Otherwise a status survives into the next run and mislabels it."""
    source = DASHBOARD.read_text(encoding="utf-8")
    cleared = set(re.search(r"classList\.remove\(([^)]*)\)", source).group(1).replace("'", "").split(","))
    for status in _status_vocabulary(source):
        assert status in cleared, f"clearStage leaves {status!r} on the phase element"
