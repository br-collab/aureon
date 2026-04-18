"""
aureon.thifur — Legacy import path.

Agents have moved to aureon.agents. This module re-exports for
backward compatibility with existing TYPE_CHECKING references.
"""

from aureon.agents.c2 import ThifurC2
from aureon.agents.triplet.agent_j import ThifurJ
from aureon.agents.triplet.agent_r import ThifurR
from aureon.agents.triplet.agent_h import ThifurH

__all__ = ["ThifurC2", "ThifurJ", "ThifurR", "ThifurH"]
