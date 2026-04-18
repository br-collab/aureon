"""aureon.agents.ranger — Ranger agents (Tier 1, deterministic execution)."""

from aureon.agents.ranger._base import RangerConcreteBase
from aureon.agents.ranger.settlement_ops import SettlementOps

RANGER_AGENTS: dict[str, type[RangerConcreteBase]] = {
    "AUR-R-SETTLEMENT-001": SettlementOps,
}

__all__ = ["RangerConcreteBase", "SettlementOps", "RANGER_AGENTS"]
