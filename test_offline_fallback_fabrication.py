"""WP-7 (AMD3-2): a failed approval changes nothing and fabricates nothing.

`confirmExecute()` and the rejection path in `resolveDecision()` both POST to
`/api/decisions/<id>`. Any exception — a network failure, a 500, an auth
failure, a non-JSON body, or a redeploy dropping the connection — used to reach
a `catch` that called `resolveDecisionLocal`, which:

- wrote a Tier 1 authority-log entry attributed to `br@ravelobizdev.com` with
  `Math.random()` in the hash field;
- pushed a position and added a trade carrying `human_approved: true` and
  `release_outcome: 'RELEASED'`;
- told the operator the trade had **executed**.

In the circumstance where the surface knows least, it asserted the most. Since
W2B-4 the real path books nothing at approval, so the fallback also simulated
behaviour the system deliberately stopped producing. The trigger — "the backend
call throws" — is exactly what a redeploy causes.

**Why this shape of test.** aureon has no JavaScript rendering harness (no node
test runner, no jsdom), so these are assertions over the surface's own source:
the failure paths must not call anything that mutates operator-visible state,
and no evidence field may be filled with a generated number. The same fallback
form AMD1 WP-6 item 3 allowed, and AMD3-1 asked to be used again.

The same property is asserted below for the other controls the WP-7 sweep found:
halt, resume, the doctrine proposal, and the price ticker. A halt that did not
reach the server has not frozen anything, and a resume that did not reach it has
not restarted anything — reporting either is worse than a wrong label, because
those two are how an operator stops and starts execution.

Run: pytest -q test_offline_fallback_fabrication.py
"""

from __future__ import annotations

import pathlib
import re

import pytest

INDEX = pathlib.Path(__file__).parent / "index.html"

#: Client-side mutations that would make the screen disagree with the record.
FABRICATION_MARKERS = (
    "state.positions.push",
    "state.trades.unshift",
    "state.authorityLog.unshift",
)


@pytest.fixture(scope="module")
def source() -> str:
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def code(source: str) -> str:
    """The source with line comments stripped, so a comment naming what was
    removed is not mistaken for the thing itself."""
    return "\n".join(re.sub(r"//.*$", "", line) for line in source.splitlines())


def _function(source: str, name: str) -> str:
    """The source of one top-level function, by brace balance."""
    start = source.index(f"function {name}(")
    depth, i = 0, source.index("{", start)
    for j in range(i, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start : j + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def _catch_bodies(block: str) -> list[str]:
    """Every catch body in a block of source."""
    bodies = []
    for match in re.finditer(r"catch\s*\([^)]*\)\s*\{", block):
        depth, start = 0, match.end() - 1
        for j in range(start, len(block)):
            if block[j] == "{":
                depth += 1
            elif block[j] == "}":
                depth -= 1
                if depth == 0:
                    bodies.append(block[start + 1 : j])
                    break
    return bodies


def test_the_optimistic_fallback_is_gone(source, code) -> None:
    assert "function resolveDecisionLocal" not in code, (
        "the fallback that simulated an approval client-side is still defined"
    )
    assert "resolveDecisionLocal(" not in code, (
        "the fallback that simulated an approval client-side is still called"
    )


@pytest.mark.parametrize("func", ["confirmExecute", "resolveDecision"])
def test_a_failed_resolve_changes_nothing(source, func) -> None:
    """The failure path must not write an authority entry, a position or a trade."""
    for body in _catch_bodies(_function(source, func)):
        for marker in FABRICATION_MARKERS:
            assert marker not in body, (
                f"{func}: a catch block calls {marker}, so a failed call still "
                f"changes operator-visible state"
            )
        assert "resolveDecisionLocal" not in body, (
            f"{func}: a catch block still simulates the outcome locally"
        )


@pytest.mark.parametrize("func", ["confirmExecute", "resolveDecision"])
def test_a_failed_resolve_says_so_and_does_not_claim_execution(source, func) -> None:
    bodies = _catch_bodies(_function(source, func))
    assert bodies, f"{func}: expected at least one catch block"
    reported = [b for b in bodies if "reportResolveFailure" in b]
    assert reported, f"{func}: the failure is not surfaced to the operator"
    for body in reported:
        assert "executed" not in body.lower(), (
            f"{func}: the failure path claims the trade executed"
        )


def test_the_failure_report_surfaces_the_exception_and_keeps_the_decision_pending(source) -> None:
    report = _function(source, "reportResolveFailure")
    assert "console.error" in report, "the exception is still swallowed"
    assert "err" in report, "the caught exception is not passed to the report"
    assert "pending" in report, "the operator is not told the decision is unchanged"
    for marker in FABRICATION_MARKERS:
        assert marker not in report, f"the failure report itself calls {marker}"


def test_no_generated_number_fills_an_evidence_field(source) -> None:
    """A hash, an authority reference or a record id is the server's to issue."""
    offenders = []
    for line_no, line in enumerate(source.splitlines(), 1):
        if "Math.random" not in line or line.strip().startswith("//"):
            continue
        if re.search(r"\b(hash|authority|record_id|report_id|signature)\b", line, re.I):
            offenders.append(f"{line_no}: {line.strip()}")
    assert offenders == [], "a generated number is filling an evidence field:\n" + "\n".join(offenders)


def test_the_post_trade_modal_does_not_invent_an_authority_hash(source) -> None:
    modal = _function(source, "showPosttradeModal")
    assign = next(line for line in modal.splitlines() if "const hash" in line)
    assert "Math.random" not in assign, (
        f"the post-trade modal generates an authority hash when the server returns none: {assign.strip()}"
    )
    assert re.search(r"hash\s*\|\|\s*'[^']*not returned", modal), (
        "the modal does not say when the server returned no hash"
    )


# ── The other controls the WP-7 sweep found ─────────────────────────────────────

#: Halt state the browser must not set on its own: the server decides whether
#: execution is frozen, and the banner is what tells the operator it is.
HALT_MARKERS = ("state.haltActive", "banner.classList", "haltBtn.textContent")


@pytest.mark.parametrize("func", ["confirmHalt", "resumeFromHalt"])
def test_a_failed_halt_control_changes_nothing(source, func) -> None:
    for body in _catch_bodies(_function(source, func)):
        for marker in HALT_MARKERS:
            assert marker not in body, (
                f"{func}: a catch block sets {marker}, so a control that never reached "
                f"the server still changes what the operator is shown"
            )
        assert "offline mode" not in body, (
            f"{func}: the failure path still reports the control as having taken effect"
        )
        assert "reportControlFailure" in body, f"{func}: the failure is not surfaced"


def test_the_control_failure_report_changes_no_state(source) -> None:
    report = _function(source, "reportControlFailure")
    assert "console.error" in report, "the exception is swallowed"
    assert "nothing changed" in report, "the operator is not told nothing changed"
    for marker in HALT_MARKERS + FABRICATION_MARKERS:
        assert marker not in report, f"the failure report itself sets {marker}"


def test_the_doctrine_proposal_failure_does_not_claim_a_submission(source) -> None:
    submit = _function(source, "doctrinePropose") if "function doctrinePropose(" in source else None
    block = submit or source
    assert "Proposal submitted (backend offline" not in block, (
        "the failure path still claims the proposal was submitted"
    )
    assert "will sync on reconnect" not in block, (
        "the failure path promises a reconnect sync that does not exist"
    )
    assert "NOT submitted" in block


def test_simulated_prices_are_visible_as_simulated(source) -> None:
    portfolio = _function(source, "fetchPortfolio")
    catches = _catch_bodies(portfolio)
    assert catches, "fetchPortfolio has no catch block"
    body = catches[0]
    assert "markPricesSimulated" in body, (
        "the browser falls back to simulated prices without saying so"
    )
    assert "state.liveMode = false" in body, "liveMode is not cleared when the backend is gone"
    marker = _function(source, "markPricesSimulated")
    assert "SIMULATED" in marker, "the header does not name the prices as simulated"
