"""
aureon.thifur — Legacy import path.

Agents have moved to aureon.agents. This module re-exports for
backward compatibility with existing TYPE_CHECKING references.
"""

from aureon.agents.c2.coordinator import ThifurC2
from aureon.agents.jtac._base import ThifurJ
from aureon.agents.ranger._base import ThifurR
from aureon.agents.hunter_killer._base import ThifurH

__all__ = ["ThifurC2", "ThifurJ", "ThifurR", "ThifurH"]
