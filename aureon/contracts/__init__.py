"""Vendored cockpit substrate (WS-1, AUR-COCKPIT-001).

Production previously carried no ``aureon.contracts`` package. This vendored
package exposes only the DSOR lineage stub that the Clearing Operator Cockpit
dependency chain (``aureon.agents.tier1`` + ``aureon.cockpit``) imports.

Source of truth is the public Atreides package
(``Project Atreides - Custody/Project-Atreides-public/aureon/contracts``).
If the full custody-contract graph (asset_class, custody_object, operations,
settlement, quorum, inherent_safety, failure_mode) is later vendored, extend
these exports to match the public ``__init__``.
"""

from aureon.contracts.dsor_stub import (
    CAOM_MODE_DEFAULT,
    CURRENT_DOCTRINE_VERSION,
    CAOMTier,
    DSORLineageStub,
)

__all__ = [
    "CAOM_MODE_DEFAULT",
    "CURRENT_DOCTRINE_VERSION",
    "CAOMTier",
    "DSORLineageStub",
]
