"""aureon.agents.ranger — Ranger agents (Tier 1, deterministic execution)."""

from aureon.agents.base import RangerAgent
from aureon.agents.ranger._base import ThifurR

RANGER_AGENTS: dict[str, type[RangerAgent]] = {
    "THIFUR_R": ThifurR,
}

__all__ = ["RangerAgent", "ThifurR", "RANGER_AGENTS"]
