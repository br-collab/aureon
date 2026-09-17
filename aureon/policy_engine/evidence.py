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
from enum import StrEnum
from typing import Any

from cannae_kernel.disposition import Disposition

__all__ = [
    "EvidenceProvenance",
    "fabricated_reason",
    "is_fabricated",
    "provenance_of",
    "stress_disposition",
]


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
    if provenance is EvidenceProvenance.FABRICATED_DEFAULT:
        return Disposition.INDETERMINATE, fabricated_reason(snapshot)
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
