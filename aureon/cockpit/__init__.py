"""Clearing Operator Cockpit — AUR-COCKPIT-001 v0.1.

The human-facing operator surface governing the clearing-and-settlement
decision cycle around external CCP/CSD portals. Prepares, governs, and
reconciles; never submits. See :mod:`aureon.cockpit.clearing_cockpit`.
"""

from aureon.cockpit.clearing_cockpit import (
    BreakLeg,
    BreakTicket,
    ClearingCockpit,
    CockpitBoundaryError,
    CockpitHalted,
    CockpitTasking,
    CycleBeat,
    GateResult,
    InstructionPackage,
    PackageDisposition,
    PortalReadback,
    PortalRegime,
    Reconciliation,
)

__all__ = [
    "BreakLeg",
    "BreakTicket",
    "ClearingCockpit",
    "CockpitBoundaryError",
    "CockpitHalted",
    "CockpitTasking",
    "CycleBeat",
    "GateResult",
    "InstructionPackage",
    "PackageDisposition",
    "PortalReadback",
    "PortalRegime",
    "Reconciliation",
]
