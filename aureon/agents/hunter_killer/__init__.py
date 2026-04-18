"""
aureon.agents.hunter_killer — Hunter-Killer agents (500 ft, adaptive)

DECLARED, NOT ACTIVATED.  execute() raises NotActivatedError.
Activation requires SR 11-7 Tier 1 independent validation,
EU AI Act conformity assessment, and Tier 2 human authority sign-off.
"""

from aureon.agents.hunter_killer._base import ThifurH

HUNTER_KILLER_AGENTS: dict[str, type] = {
    "THIFUR_H": ThifurH,
}

__all__ = ["ThifurH", "HUNTER_KILLER_AGENTS"]
