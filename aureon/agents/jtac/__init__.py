"""aureon.agents.jtac — JTAC agents (Tier 2, bounded autonomy)."""

from aureon.agents.base import JTACAgent
from aureon.agents.jtac.pretrade_structuring import ThifurJ

JTAC_AGENTS: dict[str, type[JTACAgent]] = {
    "AUR-J-TRADE-001": ThifurJ,
}

__all__ = ["JTACAgent", "ThifurJ", "JTAC_AGENTS"]
