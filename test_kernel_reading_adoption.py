"""The fabricated-reading refusal lives in the kernel type, not in an `if` here.

F1: with FRED and the OFR page both unreachable, `_fallback_macro_snapshot`'s
constants flowed into the stress proxy and produced a plausible 0.38, which gate
6 read as PASS. W2B-3 fixed it with a provenance label and a branch in
`stress_disposition`.

A branch is a filter one layer up, and W3 § R1 is the generalisation of why that
is not enough: it survives only while every caller remembers it. Now that
`cannae-kernel` is reachable by tag, the refusal moves into
`cannae_kernel.measurement`, where a gate written against `ObservedFact` cannot
be handed a fabricated default at all.

This is an adoption, not a behaviour change: the dispositions are identical
before and after, and `test_stress_evidence_provenance.py` still holds them.

Run: pytest -q test_kernel_reading_adoption.py
"""

from __future__ import annotations

import pytest

from aureon.policy_engine.evidence import (
    KERNEL_PROVENANCE,
    EvidenceProvenance,
    reading_of,
    stress_disposition,
)
from cannae_kernel.disposition import Disposition
from cannae_kernel.measurement import (
    ADMISSIBLE_WITH_DERIVATION,
    Constant,
    Measurement,
    NotAnObservationError,
    require_observation,
)
from cannae_kernel.provenance import Provenance

FABRICATED = {
    "source": "fallback",
    "provenance": "FABRICATED_DEFAULT",
    "fabricated_reason": "FRED is unreachable; these are fixed constants, not a reading",
    "as_of": "2026-09-19",
}
OFFICIAL = {"source": "ofr", "provenance": "FACT_EXTERNAL", "as_of": "2026-09-19"}
PROXY = {"source": "ofr_proxy", "provenance": "POLICY_RESULT", "as_of": "2026-09-19"}


# --- the conversion --------------------------------------------------------------


def test_a_fabricated_default_becomes_a_constant_not_a_measurement() -> None:
    """The kernel has no `Provenance` for it, deliberately: it is a different type."""
    reading = reading_of(FABRICATED, 0.38)
    assert isinstance(reading, Constant)
    assert "FRED is unreachable" in reading.reason
    assert not hasattr(reading, "observed_at")


@pytest.mark.parametrize("snapshot", [OFFICIAL, PROXY], ids=["official", "proxy"])
def test_a_labelled_reading_becomes_a_measurement(snapshot: dict) -> None:
    reading = reading_of(snapshot, 0.38)
    assert isinstance(reading, Measurement)
    assert reading.provenance is KERNEL_PROVENANCE[snapshot["provenance"]]
    assert reading.observed_at.isoformat() == "2026-09-19T00:00:00+00:00"


def test_an_undated_reading_is_a_constant_because_it_cannot_say_when_it_was_seen() -> None:
    """R1: a value with no observation time is not a measurement.

    `stress_disposition` does not act on this yet — see its comment — because
    flipping an undated official reading to INDETERMINATE changes what the live
    gate does. The conversion is still honest about it.
    """
    reading = reading_of({"source": "ofr", "provenance": "FACT_EXTERNAL"}, 0.38)
    assert isinstance(reading, Constant)
    assert "no as-of date" in reading.reason


def test_a_reading_with_no_number_is_a_constant() -> None:
    reading = reading_of(OFFICIAL, None)
    assert isinstance(reading, Constant)
    assert "no usable number" in reading.reason


# --- the refusal is the kernel's ---------------------------------------------------


def test_the_kernel_refuses_the_fabricated_reading() -> None:
    """The load-bearing one: a gate cannot be handed F1's 0.38."""
    with pytest.raises(NotAnObservationError) as refusal:
        require_observation(reading_of(FABRICATED, 0.38), admitting=ADMISSIBLE_WITH_DERIVATION)
    assert "no observation was made" in str(refusal.value)


@pytest.mark.parametrize("snapshot", [OFFICIAL, PROXY], ids=["official", "proxy"])
def test_the_kernel_admits_an_official_or_derived_reading(snapshot: dict) -> None:
    """The gate states what it admits at its own call site, and this is what that means."""
    observed = require_observation(
        reading_of(snapshot, 0.38), admitting=ADMISSIBLE_WITH_DERIVATION
    )
    assert observed.provenance in (Provenance.FACT_EXTERNAL, Provenance.POLICY_RESULT)


def test_a_derived_reading_is_refused_by_the_default_admitted_set() -> None:
    """Which is why the gate has to name ADMISSIBLE_WITH_DERIVATION explicitly."""
    with pytest.raises(NotAnObservationError):
        require_observation(reading_of(PROXY, 0.38))


def test_the_refusal_is_not_a_local_branch_any_more() -> None:
    """If the kernel call is removed, this says so before the gate goes quiet."""
    source = open("aureon/policy_engine/evidence.py", encoding="utf-8").read()
    body = source[source.index("def stress_disposition("):]
    assert "require_observation(" in body, (
        "stress_disposition no longer routes the fabricated case through the kernel; "
        "the refusal is back in a branch that a new caller can bypass"
    )


# --- and none of it changed what the gate decides -----------------------------------


@pytest.mark.parametrize(
    ("snapshot", "value", "expected"),
    [
        (FABRICATED, 0.38, Disposition.INDETERMINATE),
        (OFFICIAL, 0.38, Disposition.PASS),
        (OFFICIAL, 0.90, Disposition.PASS),
        (PROXY, 0.38, Disposition.PASS),
        (PROXY, 0.90, Disposition.HOLD),
    ],
    ids=["fabricated", "official-normal", "official-elevated", "proxy-normal", "proxy-elevated"],
)
def test_the_dispositions_are_what_they_were(snapshot: dict, value: float, expected) -> None:
    """An adoption that changes a gate's answer is not an adoption."""
    disposition, basis = stress_disposition(
        snapshot, usable=True, warn_threshold=0.7, value=value
    )
    assert disposition is expected
    assert basis.strip()


def test_the_fabricated_basis_still_carries_the_reason() -> None:
    _, basis = stress_disposition(FABRICATED, usable=True, warn_threshold=0.7, value=0.38)
    assert "FRED is unreachable" in basis


def test_the_local_label_still_maps_onto_the_kernel_vocabulary() -> None:
    """Two labels map; the third deliberately has no kernel `Provenance`."""
    assert set(KERNEL_PROVENANCE) == {"FACT_EXTERNAL", "POLICY_RESULT"}
    assert EvidenceProvenance.FABRICATED_DEFAULT.value not in KERNEL_PROVENANCE
