"""aureon.agents.jtac — JTAC agents (Tier 2, bounded autonomy)."""

from aureon.agents.base import JTACAgent
from aureon.agents.jtac._base import ThifurJ

JTAC_AGENTS: dict[str, type[JTACAgent]] = {
    "THIFUR_J": ThifurJ,
}

__all__ = ["JTACAgent", "ThifurJ", "JTAC_AGENTS"]
