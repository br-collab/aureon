"""aureon.agents.ranger — Ranger agents (Tier 1, deterministic execution)."""

from aureon.agents.ranger._base import RangerConcreteBase
from aureon.agents.ranger.settlement_ops import SettlementOps
from aureon.agents.ranger.trade_support import TradeSupport

RANGER_AGENTS: dict[str, type[RangerConcreteBase]] = {
    "AUR-R-SETTLEMENT-001":   SettlementOps,
    "AUR-R-TRADESUPPORT-001": TradeSupport,
}

__all__ = ["RangerConcreteBase", "SettlementOps", "TradeSupport", "RANGER_AGENTS"]
