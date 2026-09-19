"""The surface's not-applicable state says what the kernel says it says.

W2B7-V-01: the settlement dashboard marked the DSOR (Decision System of Record)
phase "recorded" on a quorum hold, when Atreides writes nothing there *because no
instruction was issued*. WP-6 fixed the claim and #36 gave the state a colour.

Neither tied the words to anything. The surface's label was a JavaScript string
literal, and the reason it states — the most useful part, the bit that tells an
operator *why* there is no record — existed only there.

W3 § R2 put that reason in the contract: `cannae_kernel.absence.Absent` carries a
`kind` and a required `reason`, and renders them through `label`. So the surface
and the kernel can now be required to agree, and this is the test that requires
it: it builds the absence the kernel would build for a quorum hold, then reads
the surface's own source and insists the string matches.

There is no JavaScript harness here, so this parses the surface rather than
rendering it — the same shape as `test_settlement_surface_dsor_claim.py`, and the
fallback AMD1 WP-6 item 3 allows.

Run: pytest -q test_settlement_surface_absence_vocabulary.py
"""

from __future__ import annotations

import pathlib
import re

import pytest

from cannae_kernel.absence import Absent, AbsenceKind
from cannae_kernel.disposition import Disposition

DASHBOARD = pathlib.Path(__file__).parent / "atreides-settlement-dashboard.html"

#: What Atreides records on a quorum hold, in the kernel's vocabulary.
QUORUM_HOLD = Absent(
    kind=AbsenceKind.NOTHING_RECORDED,
    reason="no instruction was issued",
)


@pytest.fixture(scope="module")
def source() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def _na_labels(source: str) -> list[str]:
    """Every label the surface shows for the not-applicable DSOR state."""
    return re.findall(r"'—\s*(nothing recorded[^']*)'", source)


def test_the_surface_uses_the_kernel_label_verbatim(source) -> None:
    """One word apart is still two vocabularies.

    The surface said "no instruction issued" and the kernel says "no instruction
    was issued". Nothing broke, and nothing would have — which is exactly why it
    needs a test rather than a convention.
    """
    labels = _na_labels(source)
    assert labels, "the surface no longer shows a not-applicable DSOR label"
    for label in labels:
        assert label == QUORUM_HOLD.label, (
            f"the surface shows {label!r} where the kernel renders "
            f"{QUORUM_HOLD.label!r}"
        )


def test_every_place_the_surface_says_it_says_the_same_thing(source) -> None:
    """Two renderers, one string. They drifted once already (#36)."""
    labels = _na_labels(source)
    assert len(labels) >= 2, "expected the live and replay renderers to both carry it"
    assert len(set(labels)) == 1, f"the renderers disagree: {sorted(set(labels))}"


def test_a_quorum_hold_is_settled_absence_and_not_a_pending_one() -> None:
    """The distinction R2 insists on, applied to this case.

    A quorum hold records nothing and never will for this operation, so it is
    NOTHING_RECORDED. Rendering it as NOT_YET_KNOWN would tell an operator to
    wait for a record that is not coming.
    """
    assert QUORUM_HOLD.kind is AbsenceKind.NOTHING_RECORDED
    assert QUORUM_HOLD.kind is not AbsenceKind.NOT_YET_KNOWN
    assert QUORUM_HOLD.label.startswith("nothing recorded")


def test_the_absence_is_indeterminate_and_never_a_pass() -> None:
    """The rule underneath the whole thing."""
    assert QUORUM_HOLD.disposition is Disposition.INDETERMINATE
    assert QUORUM_HOLD.disposition is not Disposition.PASS


def test_the_surface_does_not_call_the_quorum_hold_recorded(source) -> None:
    """W2B7-V-01 itself, still held."""
    branch = source[source.index("st[PIDX['dsor']]='na'"):]
    branch = branch[: branch.index("\n", branch.index("lb[PIDX['dsor']]"))]
    assert "recorded'" not in branch.replace("nothing recorded", ""), (
        "the quorum-hold branch claims a record again"
    )
