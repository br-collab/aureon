"""AMD3-3: a static panel says it is static, and an absent outcome is not a success.

The three secondary items from the WP-6 surface sweep. None is a Decision System
of Record claim and none was introduced by Wave 2, but each asserts something the
system does not know:

- the Audit Report card read `PASS`, "10 checks · All green", with nothing
  computing any of it, and the ten checks below it would read the same if the
  property they name were violated;
- a trade with no `release_outcome` was rendered `RELEASED` with a "ready" badge;
- the regulatory alignment figures are a static summary with no date or source.

Run: pytest -q test_static_claims.py
"""

from __future__ import annotations

import pathlib
import re

import pytest

INDEX = pathlib.Path(__file__).parent / "index.html"


@pytest.fixture(scope="module")
def source() -> str:
    return INDEX.read_text(encoding="utf-8")


def _card(source: str, label: str) -> str:
    start = source.index(f'<div class="card-label">{label}</div>')
    return source[start : source.index("</div>", source.index("card-sub", start))]


def test_the_audit_card_does_not_claim_a_result(source) -> None:
    card = _card(source, "Audit Report")
    assert "PASS" not in card, "the card asserts a result that nothing computes"
    assert "All green" not in card
    assert re.search(r"mock|illustrative", card, re.I), (
        "the card does not say the panel is a design mock"
    )


def test_the_audit_panel_says_the_checks_are_not_computed(source) -> None:
    panel = source[source.index('<div id="report-audit"'):]
    panel = panel[: panel.index('<div id="report-replay"')] if '<div id="report-replay"' in panel \
        else panel[:4000]
    banner = panel[: panel.index("Doctrine Integrity Checks")]
    assert re.search(r"design mock", banner, re.I), "the panel does not declare itself a mock"
    assert re.search(r"not (a )?comput", banner, re.I), (
        "the panel does not say the checks are uncomputed"
    )
    # The checks themselves are still listed: the point is to label them, not hide them.
    assert panel.count("check-row") >= 10


def test_an_absent_release_outcome_is_not_rendered_as_released(source) -> None:
    assert "t.release_outcome || 'RELEASED'" not in source, (
        "a trade with no outcome still defaults to RELEASED"
    )
    row = source[source.index("readiness-badge readiness-ready") - 400:]
    row = row[: row.index("</tr>")]
    assert "t.release_outcome" in row and "?" in row, (
        "the outcome badge is not conditional on there being an outcome"
    )


def test_the_regulatory_figures_carry_provenance_and_a_date(source) -> None:
    block = source[source.index("FULLY SATISFIED") - 600:]
    block = block[: block.index("<!-- TARGET ARCHITECTURE")]
    assert "Provenance:" in block, "the static figures carry no provenance line"
    assert re.search(r"\b20\d\d\b", block), "the static figures carry no date"
    assert re.search(r"not a\s+live measurement|nothing recomputes", block), (
        "the figures do not say they are not measured"
    )
