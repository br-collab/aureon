"""aureon.agents.hunter_killer — Hunter-Killer agents (Tier 3).

The class here is ``ThifurHAgent``, the agent-framework rendering. It is NOT
the live Thifur-H session engine — that is ``aureon.thifur.thifur_h.ThifurH``,
which ``server.py`` runs and which drives the ``/api/thifur-h/*`` routes. The
two were both named ``ThifurH`` until AUR-CANONICAL-AMD-001 §II separated them.

This package is imported at boot through ``aureon.agents.__init__``. Retiring
it requires repointing ``aureon/cli/main.py`` and ``aureon/mcp/agents_server.py``
first; deleting it outright raises ImportError at ``server.py:97``.
"""

from aureon.agents.base import HunterKillerAgent
from aureon.agents.hunter_killer._base import ThifurHAgent

HUNTER_KILLER_AGENTS: dict[str, type[HunterKillerAgent]] = {
    "THIFUR_H": ThifurHAgent,
}

__all__ = ["HunterKillerAgent", "ThifurHAgent", "HUNTER_KILLER_AGENTS"]
