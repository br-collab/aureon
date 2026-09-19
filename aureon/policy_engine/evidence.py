"""
aureon.policy_engine.evidence
=============================
Where a market-evidence reading came from (AUR-I-10, W2B-3 fix F1).

A stress reading can be three different things, and only the label tells them
apart once the number is in hand:

- ``FACT_EXTERNAL`` — read from the publisher: the OFR (Office of Financial
  Research) Financial Stress Index, or a FRED (Federal Reserve Economic Data)
  series.
- ``POLICY_RESULT`` — computed here from **live** external inputs, such as the
  OFR proxy derived from live FRED series. A real computation over real data,
  but not the official reading.
- ``FABRICATED_DEFAULT`` — a fixed constant stood in for an input that could
  not be read. The number looks measured and means nothing.

This distinction is the whole finding. With FRED and the OFR page both
unreachable, `_fallback_macro_snapshot`'s constants (VIX 24.0, high-yield
option-adjusted spread 4.25, curve −20) flowed into the proxy and produced a
plausible stress index of about 0.38, which gate 6 read as PASS. A missing
reading was converted into permission.

A snapshot that carries a fabricated default is evidence of nothing:
:func:`gate_disposition_for` makes it ``INDETERMINATE``, and audit fields
record ``None`` with a reason instead of the number.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from cannae_kernel.disposition import Disposition
from cannae_kernel.measurement import (
    ADMISSIBLE_WITH_DERIVATION,
    Constant,
    Measurement,
    NotAnObservationError,
    require_observation,
)
from cannae_kernel.provenance import Provenance

__all__ = [
    "KERNEL_PROVENANCE",
    "EvidenceProvenance",
    "fabricated_reason",
    "is_fabricated",
    "provenance_of",
    "reading_of",
    "stress_disposition",
]

#: This module's wire labels, which snapshots carry as strings, mapped onto the
#: kernel's vocabulary. Only two map: `FABRICATED_DEFAULT` has no kernel
#: `Provenance` and deliberately never will, because provenance answers *where an
#: observation came from* and a fabricated default is not an observation. In the
#: kernel it is a different type — `Constant` — which has no `observed_at` field
#: at all and carries the reason there is none.
KERNEL_PROVENANCE = {
    "FACT_EXTERNAL": Provenance.FACT_EXTERNAL,
    "POLICY_RESULT": Provenance.POLICY_RESULT,
}


class EvidenceProvenance(StrEnum):
    FACT_EXTERNAL = "FACT_EXTERNAL"
    POLICY_RESULT = "POLICY_RESULT"
    FABRICATED_DEFAULT = "FABRICATED_DEFAULT"


def provenance_of(snapshot: Mapping[str, Any] | None) -> EvidenceProvenance:
    """The snapshot's label. Anything unlabelled or unrecognised is fabricated.

    Fail closed: a reading that cannot say where it came from is not evidence.
    """
    if not isinstance(snapshot, Mapping):
        return EvidenceProvenance.FABRICATED_DEFAULT
    try:
        return EvidenceProvenance(snapshot.get("provenance"))
    except ValueError:
        return EvidenceProvenance.FABRICATED_DEFAULT


def is_fabricated(snapshot: Mapping[str, Any] | None) -> bool:
    return provenance_of(snapshot) is EvidenceProvenance.FABRICATED_DEFAULT


def fabricated_reason(snapshot: Mapping[str, Any] | None) -> str:
    """Why a value is not recorded, for the audit field that would have held it."""
    if isinstance(snapshot, Mapping) and snapshot.get("fabricated_reason"):
        return str(snapshot["fabricated_reason"])
    return ("no live reading: a fixed constant stood in for the feed, so there is no "
            "measured value to record")


def reading_of(
    snapshot: Mapping[str, Any] | None, value: float | None
) -> Measurement | Constant:
    """This module's snapshot as a kernel reading.

    The point of converting is that the refusal then lives in the type rather
    than in this function: a gate written against `ObservedFact` cannot be handed
    a fabricated default by a caller who did not know to filter, which is the
    failure R1 describes and the one that produced F1.

    **On the observation time.** These feeds report an `as_of` *date*, not an
    instant, so the observation time is that date at 00:00 UTC and is no more
    precise than the feed. A snapshot with no usable date is not a measurement:
    a value that cannot say when it was seen is a constant, and is returned as
    one with that as its reason.
    """
    provenance = provenance_of(snapshot)
    source = str((snapshot or {}).get("source") or "unknown")

    if provenance is EvidenceProvenance.FABRICATED_DEFAULT or value is None:
        return Constant(
            value=_decimal(value),
            source=source,
            reason=fabricated_reason(snapshot) if value is not None
            else "the feed returned no usable number",
        )

    observed_at = _observed_at(snapshot)
    if observed_at is None:
        return Constant(
            value=_decimal(value),
            source=source,
            reason="the reading carries no as-of date, so there is no time it was seen",
        )
    return Measurement(
        value=_decimal(value),
        provenance=KERNEL_PROVENANCE[provenance.value],
        source=source,
        observed_at=observed_at,
    )


def _decimal(value: float | None) -> Decimal:
    """A Decimal the kernel will accept, from a float the feed gave us."""
    try:
        return Decimal(str(value if value is not None else 0))
    except InvalidOperation:
        return Decimal("0")


def _observed_at(snapshot: Mapping[str, Any] | None) -> datetime | None:
    """The `as_of` date at 00:00 UTC, or None when there is no usable date."""
    raw = (snapshot or {}).get("as_of")
    if not raw:
        return None
    try:
        return datetime.combine(date.fromisoformat(str(raw)[:10]), datetime.min.time(), UTC)
    except ValueError:
        return None


def stress_disposition(
    snapshot: Mapping[str, Any] | None, *, usable: bool, warn_threshold: float, value: float | None
) -> tuple[Disposition, str]:
    """Disposition and a one-line basis for a systemic-stress reading.

    - fabricated, or unusable → INDETERMINATE;
    - proxy (POLICY_RESULT) → PASS below the warning threshold, HOLD at or
      above it: a derived reading may not clear an elevated market on its own;
    - official (FACT_EXTERNAL) → PASS, or WARN-level PASS above the threshold,
      as before.
    """
    provenance = provenance_of(snapshot)

    # The fabricated case is refused by the kernel rather than by an `if` here,
    # so a gate that asks for an `ObservedFact` cannot be handed one by a caller
    # who did not know to filter. ADMISSIBLE_WITH_DERIVATION is stated at the
    # call site on purpose: this gate acts on the OFR proxy, a real computation
    # over live FRED series that is not the official index, and saying so here
    # is what keeps the choice visible in review.
    if provenance is EvidenceProvenance.FABRICATED_DEFAULT:
        try:
            require_observation(
                reading_of(snapshot, value), admitting=ADMISSIBLE_WITH_DERIVATION
            )
        except NotAnObservationError:
            return Disposition.INDETERMINATE, fabricated_reason(snapshot)
        raise AssertionError(  # pragma: no cover - the kernel must refuse a Constant
            "a fabricated snapshot satisfied a gate requiring an observation"
        )

    # A labelled reading with no `as_of` is, by R1, a constant rather than a
    # measurement — `reading_of` says so. This function deliberately does **not**
    # act on that yet: flipping an undated official reading to INDETERMINATE
    # would change what the live gate does, and that is a decision to take on
    # purpose rather than inside a type-adoption change. Reported in
    # `_reports/W3-report.md`; both production snapshots do carry `as_of`.
    if not usable or value is None:
        return Disposition.INDETERMINATE, "the reading is not a usable number"
    if provenance is EvidenceProvenance.POLICY_RESULT:
        if value >= warn_threshold:
            return (Disposition.HOLD,
                    f"proxy reading {value:.2f} at or above the {warn_threshold:.2f} warning "
                    "threshold (source=ofr_proxy): held for the official index")
        return (Disposition.PASS,
                f"proxy reading {value:.2f} below the {warn_threshold:.2f} warning threshold "
                "(source=ofr_proxy, derived from live FRED series)")
    if value >= warn_threshold:
        return Disposition.PASS, f"official reading {value:.2f} — elevated systemic risk"
    return Disposition.PASS, f"official reading {value:.2f} — normal"
