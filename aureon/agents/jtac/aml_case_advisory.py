"""Advisory-only anti-money laundering case narrative drafting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AMLCaseNarrative:
    case_id: str
    label: str
    narrative: str
    decision: None = None


def draft_case_narrative(*, case_id: str, alert_facts: tuple[str, ...]) -> AMLCaseNarrative:
    return AMLCaseNarrative(
        case_id,
        "ADVISORY_DRAFT_NOT_A_DECISION",
        "Observed facts: " + "; ".join(alert_facts),
    )
