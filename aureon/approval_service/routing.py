"""Dynamic approval routing for Phase 1 governed release control."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from aureon.core.models import GovernedDecision


PHASE1_MATERIALITY_THRESHOLD = 400_000


def normalize_decision(decision: Any) -> GovernedDecision:
    """Accept either a mapping or a GovernedDecision and return the normalized model."""
    if isinstance(decision, GovernedDecision):
        return decision
    if isinstance(decision, dict):
        return GovernedDecision.from_mapping(decision)
    return GovernedDecision.from_mapping(vars(decision))


def determine_required_approvals(decision: Any) -> list[str]:
    """
    Phase 1 routing model for Electronic Execution in single-name equities.

    Base:
    - TRADER for all in-scope decisions

    Add:
    - RISK for material trades or risk-relevant exceptions
    - COMPLIANCE for mandate/policy sensitivity
    - PM when explicit PM sign-off is required
    - CONTROL for exceptional override paths
    """
    governed = normalize_decision(decision)
    roles: list[str] = ["TRADER"]

    if governed.notional >= PHASE1_MATERIALITY_THRESHOLD or governed.risk_exception or governed.financing_relevant:
        roles.append("RISK")

    if governed.mandate_sensitive or governed.policy_exception:
        roles.append("COMPLIANCE")

    if governed.pm_signoff_required:
        roles.append("PM")

    if governed.control_exception:
        roles.append("CONTROL")

    return roles


def apply_routing(decision: Any) -> GovernedDecision:
    """Return a decision with its required approvals populated from Phase 1 routing."""
    governed = normalize_decision(decision)
    return replace(governed, required_approvals=determine_required_approvals(governed))
