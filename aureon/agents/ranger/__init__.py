"""aureon.agents.ranger — Ranger agents (Tier 1, deterministic execution)."""

from aureon.agents.ranger._base import RangerConcreteBase
from aureon.agents.ranger.settlement_ops import SettlementOps
from aureon.agents.ranger.trade_support import TradeSupport
from aureon.agents.ranger.reconciliation import Reconciliation
from aureon.agents.ranger.reg_reporting import RegReporting

RANGER_AGENTS: dict[str, type[RangerConcreteBase]] = {
    "AUR-R-SETTLEMENT-001":   SettlementOps,
    "AUR-R-TRADESUPPORT-001": TradeSupport,
    "AUR-R-RECON-001":        Reconciliation,
    "AUR-R-REGREP-001":       RegReporting,
}

__all__ = [
    "RangerConcreteBase",
    "SettlementOps",
    "TradeSupport",
    "Reconciliation",
    "RegReporting",
    "RANGER_AGENTS",
]
