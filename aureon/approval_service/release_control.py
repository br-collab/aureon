"""Governed release control boundary for Phase 1 OMS/EMS handoff."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from aureon.approval_service.routing import apply_routing
from aureon.core.models import GovernedDecision


def normalize_decision(decision: Any) -> GovernedDecision:
    """Accept either a mapping or a GovernedDecision and return the normalized model."""
    if isinstance(decision, GovernedDecision):
        return apply_routing(decision)
    if isinstance(decision, dict):
        return apply_routing(GovernedDecision.from_mapping(decision))
    return apply_routing(GovernedDecision.from_mapping(vars(decision)))


def approve_role(decision: Any, role: str) -> GovernedDecision:
    """Record a role approval on the governed decision."""
    governed = normalize_decision(decision)
    role = role.upper()
    if role not in governed.current_approvals:
        governed = replace(governed, current_approvals=[*governed.current_approvals, role])
    return governed


def missing_roles(decision: Any) -> list[str]:
    """Return the set of required roles that have not yet approved."""
    governed = normalize_decision(decision)
    approvals = set(governed.current_approvals)
    return [role for role in governed.required_approvals if role not in approvals]


def can_release(decision: Any) -> bool:
    """A governed decision may be released only when every required role has approved."""
    return not missing_roles(decision)


def release_to_oms(
    decision: Any,
    *,
    authority_hash: str,
    oms_send: Callable[[dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    """
    Enforce the DSOR release gate and hand off only fully approved decisions
    to the OMS adapter boundary.
    """
    governed = normalize_decision(decision)
    outstanding = missing_roles(governed)
    if outstanding:
        raise RuntimeError(f"Release blocked: approvals incomplete ({', '.join(outstanding)})")
    return oms_send(governed.to_mapping(), authority_hash)
