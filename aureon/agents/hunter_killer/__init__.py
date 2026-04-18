"""aureon.agents.hunter_killer — Hunter-Killer agents (Tier 3, DECLARED)."""

from aureon.agents.base import HunterKillerAgent
from aureon.agents.hunter_killer._base import ThifurH

HUNTER_KILLER_AGENTS: dict[str, type[HunterKillerAgent]] = {
    "THIFUR_H": ThifurH,
}

__all__ = ["HunterKillerAgent", "ThifurH", "HUNTER_KILLER_AGENTS"]
