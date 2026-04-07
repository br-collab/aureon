"""Core decision models for Phase 1 governed release control."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_REQUIRED_APPROVALS = ["TRADER"]


@dataclass
class GovernedDecision:
    """Simplified DSOR decision model for role-based release control."""

    id: str
    action: str
    symbol: str
    asset_class: str
    shares: float
    price: float
    notional: float
    product_type: str = "SINGLE_NAME_EQUITY"
    rationale: str = ""
    status: str = "PENDING"
    required_approvals: list[str] = field(default_factory=lambda: list(DEFAULT_REQUIRED_APPROVALS))
    current_approvals: list[str] = field(default_factory=list)
    release_target: str = "OMS"
    mandate_sensitive: bool = False
    policy_exception: bool = False
    risk_exception: bool = False
    pm_signoff_required: bool = False
    control_exception: bool = False
    financing_relevant: bool = False
    created: str | None = None
    signal_type: str | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "GovernedDecision":
        """Normalize a dict-shaped decision into a governed decision model."""
        return cls(
            id=raw["id"],
            action=raw["action"],
            symbol=raw["symbol"],
            asset_class=raw["asset_class"],
            shares=raw["shares"],
            price=raw["price"],
            notional=raw["notional"],
            product_type=raw.get("product_type", "SINGLE_NAME_EQUITY"),
            rationale=raw.get("rationale", ""),
            status=raw.get("status", "PENDING"),
            required_approvals=list(raw.get("required_approvals", DEFAULT_REQUIRED_APPROVALS)),
            current_approvals=list(raw.get("current_approvals", [])),
            release_target=raw.get("release_target", "OMS"),
            mandate_sensitive=bool(raw.get("mandate_sensitive", False)),
            policy_exception=bool(raw.get("policy_exception", False)),
            risk_exception=bool(raw.get("risk_exception", False)),
            pm_signoff_required=bool(raw.get("pm_signoff_required", False)),
            control_exception=bool(raw.get("control_exception", False)),
            financing_relevant=bool(raw.get("financing_relevant", False)),
            created=raw.get("created"),
            signal_type=raw.get("signal_type"),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return a dict form compatible with the current prototype state."""
        return {
            "id": self.id,
            "action": self.action,
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "shares": self.shares,
            "price": self.price,
            "notional": self.notional,
            "product_type": self.product_type,
            "rationale": self.rationale,
            "status": self.status,
            "required_approvals": list(self.required_approvals),
            "current_approvals": list(self.current_approvals),
            "release_target": self.release_target,
            "mandate_sensitive": self.mandate_sensitive,
            "policy_exception": self.policy_exception,
            "risk_exception": self.risk_exception,
            "pm_signoff_required": self.pm_signoff_required,
            "control_exception": self.control_exception,
            "financing_relevant": self.financing_relevant,
            "created": self.created,
            "signal_type": self.signal_type,
        }
