"""aureon.agents.jtac — JTAC agents (Tier 2, bounded autonomy)."""

from aureon.agents.base import JTACAgent
from aureon.agents.jtac._base import JTACConcreteBase, UnapprovedPathError
from aureon.agents.jtac.pretrade_structuring import ThifurJ
from aureon.agents.jtac.compliance import Compliance
from aureon.agents.jtac.aml_kyc import AmlKyc

# Registry keyed by role_id (matches the Ranger convention).
# ThifurJ still inherits JTACAgent directly; Phase 4.1 retrofits it onto
# JTACConcreteBase — see TRACKERS.md "JTAC base unification".
JTAC_AGENTS: dict[str, type[JTACAgent]] = {
    "AUR-J-TRADE-001": ThifurJ,
    "AUR-J-COMP-001":  Compliance,
    "AUR-J-AML-001":   AmlKyc,       # WS-2.2 — second Tier 2 role
}

__all__ = [
    "JTACAgent",
    "JTACConcreteBase",
    "UnapprovedPathError",
    "ThifurJ",
    "Compliance",
    "AmlKyc",
    "JTAC_AGENTS",
]
