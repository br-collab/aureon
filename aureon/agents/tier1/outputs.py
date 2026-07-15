"""Typed I/O contracts for the Settlement Operations Analyst (Tier 1 · Thifur-R).

Per AUR-CANONICAL-001 v1.5.1 Section IV (settlement-operations-analyst v0.3)
and AUR-CUSTODY-001 v1.0 Section VI (R-class roles — zero variance,
no path selection, immediate escalation on any gate failure).

Module layout
-------------
Enumerations: SettlementRail, SettlementKind, CreditFacilityType,
    GCFPoolCustodian, DiscrepancyCode

Input contract: SettlementTaskingRecord — frozen, delivered by Thifur-C2.

Output contracts: SettlementTelemetry (success path), SettlementEscalation
    (any pre-routing gate failure). Discriminated on ``kind``.

SettlementOutput — union alias used by DSORStore type adapter.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from aureon.contracts import DSORLineageStub

CURRENT_DOCTRINE_VERSION: Final = "AUR-CANONICAL-001-v1.5.1"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SettlementRail(StrEnum):
    FICC_GSD_DVP = "ficc_gsd_dvp"
    FICC_GCF_REPO = "ficc_gcf_repo"
    FICC_SPONSORED_DVP = "ficc_sponsored_dvp"
    FEDWIRE_FUNDS = "fedwire_funds"
    FEDWIRE_SECURITIES = "fedwire_securities"
    SWIFT_MT202 = "swift_mt202"


class SettlementKind(StrEnum):
    DVP = "dvp"
    MTM_MARGIN_CALL = "mtm_margin_call"
    EOD_NET_FUNDING = "eod_net_funding"


class CreditFacilityType(StrEnum):
    DIRECT_FED = "direct_fed"
    CORRESPONDENT = "correspondent"


class GCFPoolCustodian(StrEnum):
    BNY_MELLON = "bny_mellon"


class DiscrepancyCode(StrEnum):
    DSOR_MISMATCH = "dsor_mismatch"
    RAIL_UNAVAILABLE = "rail_unavailable"
    COUNTERPARTY_TIMEOUT = "counterparty_timeout"
    INSTRUCTION_REJECTED = "instruction_rejected"
    CLEARING_FUND_DEFICIENCY = "clearing_fund_deficiency"
    INTRADAY_CREDIT_THRESHOLD = "intraday_credit_threshold"
    NET_OBLIGATION_MISMATCH = "net_obligation_mismatch"
    FICC_MTM_DEADLINE_BREACH = "ficc_mtm_deadline_breach"
    RAIL_CONFIRMATION_MISMATCH = "rail_confirmation_mismatch"


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------


class SettlementTaskingRecord(BaseModel):
    """Tasking record delivered by Thifur-C2 to the Settlement Operations Analyst.

    Frozen at delivery. The analyst may read but never mutate this record.
    All optional FICC-specific fields default to None; the analyst gates on
    their presence before applying the corresponding pre-routing checks.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID = Field(default_factory=uuid4)
    operation_id: UUID
    rail: SettlementRail
    settlement_kind: SettlementKind
    counterparty_id: str
    deadline: datetime
    dsor_pre_trade_record_id: UUID
    lineage_stub: DSORLineageStub
    doctrine_version: str = CURRENT_DOCTRINE_VERSION

    # Net settlement obligation (FICC GSD — set for DVP and GCF Repo)
    net_cusip: str | None = None
    net_delivery_quantity: Decimal | None = None
    net_payment_amount: Decimal | None = None

    # FICC-published net position (v0.3: net obligation modeling check)
    ficc_published_net_delivery: Decimal | None = None
    ficc_published_net_payment: Decimal | None = None

    # v0.3 — intraday funding position (Reg F / cap net debit cap)
    intraday_credit_limit: Decimal | None = None
    intraday_credit_current_usage: Decimal | None = None
    credit_facility_type: CreditFacilityType | None = None

    # v0.3 — FICC margin mechanics (clearing fund VaR + FICC intraday MTM call)
    ficc_clearing_fund_compliant: bool = True
    ficc_mtm_call_amount: Decimal | None = None
    ficc_mtm_call_deadline: datetime | None = None

    # v0.3 — FICC netting configuration surfaces
    sponsoring_member_id: str | None = None
    gcf_pool_custodian: GCFPoolCustodian | None = None


# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------


class _SettlementOutputBase(BaseModel):
    """Common fields for all Settlement Operations Analyst outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_id: UUID
    task_id: UUID
    doctrine_version: str
    lineage_stub: DSORLineageStub
    emitted_at: datetime
    rail: SettlementRail | None


class SettlementTelemetry(_SettlementOutputBase):
    """Emitted on successful settlement instruction routing (success path).

    ``kind`` is always ``"settlement_telemetry"`` and serves as the DSOR
    discriminator. The instruction reference is a deterministic routing token
    generated from the task_id and rail; in production it is replaced by the
    rail-assigned acknowledgment reference (FICC CNS sequence number or
    Fedwire sequence).
    """

    kind: Literal["settlement_telemetry"] = "settlement_telemetry"
    settlement_kind: SettlementKind
    instruction_reference: str
    net_cusip: str | None = None
    net_delivery_quantity: Decimal | None = None
    net_payment_amount: Decimal | None = None
    rail_acknowledgment_dtg: datetime
    clearing_fund_compliant: bool
    intraday_credit_usage_at_execution: Decimal | None = None
    intraday_credit_limit: Decimal | None = None
    sponsoring_member_id: str | None = None
    gcf_pool_custodian: GCFPoolCustodian | None = None


class SettlementEscalation(_SettlementOutputBase):
    """Emitted when a pre-routing gate fails (escalation path).

    ``rail`` is ``None`` when the escalation fires before routing (the
    common case for all pre-routing gates). ``clearing_fund_deficiency``
    is only ``True`` when ``discrepancy_code`` is
    ``CLEARING_FUND_DEFICIENCY``; it is ``False`` for all other codes.
    """

    kind: Literal["settlement_escalation"] = "settlement_escalation"
    discrepancy_code: DiscrepancyCode
    failure_detail: str
    intraday_credit_usage: Decimal | None = None
    intraday_credit_limit: Decimal | None = None
    clearing_fund_deficiency: bool = False
    net_obligation_discrepancy: str | None = None


SettlementOutput = SettlementTelemetry | SettlementEscalation

__all__ = [
    "CURRENT_DOCTRINE_VERSION",
    "CreditFacilityType",
    "DiscrepancyCode",
    "GCFPoolCustodian",
    "SettlementEscalation",
    "SettlementKind",
    "SettlementOutput",
    "SettlementRail",
    "SettlementTaskingRecord",
    "SettlementTelemetry",
]
