"""Clearing Operator Cockpit — the human-facing settlement decision surface.

Per **AUR-COCKPIT-001 v0.1** (Clearing Operator Cockpit Doctrine),
AUR-CANONICAL-001 v1.6, and AUR-CUSTODY-001 v1.0 (Settlement Operations).

The cockpit governs the operator's decision cycle as it moves *around* —
never *through* — the external clearing (CCP) and settlement (CSD)
portals. It implements the six capability primitives named in
AUR-COCKPIT-001 Section VIII and the five-beat operating cycle in
Section IV:

    1. gather    -> capture_tasking
    2. validate  -> run_validation_gates   (reuses the Settlement
                    Operations Analyst gate set — no divergent gate logic)
    3. prepare   -> emit_instruction_package
    4. submit    -> PERFORMED BY THE ENTITLED MEMBER, OUTSIDE THIS SURFACE
    5. reconcile -> ingest_portal_readback + reconcile_expected_actual
                    + raise_break

THE CARDINAL BOUNDARY (AUR-COCKPIT-001 Section II), enforced structurally
below:

    Atreides prepares - governs - reconciles. The entitled member submits.

- The cockpit NEVER holds CCP/CSD credentials, NEVER auto-submits, and
  NEVER scrapes a portal. There is deliberately no ``submit`` method and
  no credential field anywhere in this module.
- Inbound data enters ONLY as operator-entered readback
  (``ingest_portal_readback``).
- Outbound is a validated instruction package for human entry — a
  structured artifact, never a submission. ``InstructionPackage`` pins
  ``is_submission`` to ``Literal[False]`` so a submission object is
  unconstructible at the type layer.
- CCP and CSD are separate regimes (Section VI): the cockpit keeps
  separate contexts per regime and never flattens them into one
  "depository" abstraction.
- Material-magnitude operations route to quorum before release; under
  CAOM-001 quorum is unavailable, so they HOLD and surface a
  CAOM-transition trigger (AUR-CUSTODY-001 Section VII; canonical
  Section V). No package is emitted.
- Tier 0 Halt propagates across the surface: when the halt predicate is
  set, every primitive refuses (Axiom 9).

Build status per AUR-COCKPIT-001 Section XI: the operating cycle runs on
operator-entered / synthetic inputs. Beat 4 (submission) is permanent
doctrine — no submission capability is ever to be built.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aureon.agents.tier1.outputs import (
    CreditFacilityType,
    GCFPoolCustodian,
    SettlementKind,
    SettlementRail,
    SettlementTaskingRecord,
    SettlementTelemetry,
)
from aureon.agents.tier1.settlement_operations_analyst import (
    SettlementOperationsAnalyst,
)
from aureon.contracts import DSORLineageStub
from aureon.contracts.dsor_stub import CAOMTier
from aureon.dsor import DSORStore

# Default material-magnitude threshold above which an operation is
# quorum-required. The doctrine fixes no number (per-magnitude threshold
# selection is a Federate/Sovereign operational-specification concern —
# AUR-CUSTODY-001 Section VII / quorum.py). This default is operator-set.
DEFAULT_MATERIAL_MAGNITUDE = Decimal("50000000")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PortalRegime(StrEnum):
    """The two distinct external regimes the cockpit governs around.

    Per AUR-COCKPIT-001 Section VI: the clearing leg (CCP — novation,
    netting, clearing fund) and the settlement/custody leg (CSD —
    securities custody, DvP) are distinct subsidiaries under distinct
    rulebooks. The cockpit maintains SEPARATE contexts and never
    flattens them.
    """

    CCP = "ccp"
    CSD = "csd"


class CycleBeat(StrEnum):
    """The cockpit-owned beats of the five-beat cycle (Section IV).

    Beat 4 (SUBMIT) is deliberately absent — it is the entitled member's
    regulated act, outside the cockpit's authority, and is never recorded
    here as a cockpit action.
    """

    GATHER = "gather"
    VALIDATE = "validate"
    PREPARE = "prepare"
    RECONCILE = "reconcile"


class PackageDisposition(StrEnum):
    """Outcome of ``emit_instruction_package``."""

    EMIT_FOR_HUMAN_ENTRY = "emit_for_human_entry"
    """Gates passed, magnitude sub-material: a governed package is emitted
    as a structured artifact for the entitled member to key."""

    GATE_HELD = "gate_held"
    """A validation gate held. No package is emitted (Section IV Beat 2)."""

    QUORUM_REQUIRED_HOLD = "quorum_required_hold"
    """Material magnitude routes to quorum; quorum is unavailable under
    CAOM-001, so the operation HOLDS and surfaces a CAOM-transition
    trigger. No package is emitted (AUR-CUSTODY-001 Section VII)."""


class BreakLeg(StrEnum):
    """Reconciliation break classification by leg (Section VII)."""

    POSITION = "position_break"
    FUNDING = "funding_break"
    CLEARING_FUND = "clearing_fund_break"
    NET_OBLIGATION = "net_obligation_break"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CockpitHalted(RuntimeError):
    """Raised when a primitive is invoked while Tier 0 Halt is active."""


class CockpitBoundaryError(RuntimeError):
    """Raised on an attempt that would cross the cardinal boundary."""


# ---------------------------------------------------------------------------
# Models (frozen, extra-forbid — no hidden credential/submission fields)
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CockpitTasking(_Frozen):
    """Structured transaction picture captured at Beat 1 (Section V inbound).

    Operator-entered readback only. Carries the transaction picture the
    gates read; carries no credential or entitlement.
    """

    operation_id: UUID
    regime: PortalRegime
    rail: SettlementRail
    settlement_kind: SettlementKind
    counterparty_id: str
    cusip: str | None = None
    settlement_date: datetime
    authority_tier: CAOMTier
    authority_id: str
    captured_at: datetime

    # Net settlement obligation (operator readback)
    net_delivery_quantity: Decimal | None = None
    net_payment_amount: Decimal | None = None
    ficc_published_net_delivery: Decimal | None = None

    # Intraday funding / credit position (operator readback)
    intraday_credit_limit: Decimal | None = None
    intraday_credit_current_usage: Decimal | None = None
    credit_facility_type: CreditFacilityType | None = None

    # Clearing-fund status (operator readback)
    ficc_clearing_fund_compliant: bool = True

    # FICC netting configuration
    sponsoring_member_id: str | None = None
    gcf_pool_custodian: GCFPoolCustodian | None = None

    def pre_operation_state_hash(self) -> str:
        """Deterministic SHA-256 of the captured picture — the pre-operation
        DSOR state hash the lineage stub binds (Axiom 4)."""
        payload = self.model_dump(mode="json", exclude={"captured_at"})
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class GateResult(_Frozen):
    """Outcome of Beat 2 validation against the Settlement Operations
    Analyst gate set. On a hold, ``passed`` is False and no package may be
    emitted."""

    operation_id: UUID
    regime: PortalRegime
    passed: bool
    output_kind: str
    dsor_pre_trade_record_id: UUID
    discrepancy_code: str | None = None
    detail: str | None = None


class InstructionPackage(_Frozen):
    """Beat 3 output — a governed, exportable instruction package.

    A structured artifact for human entry, carrying a DSOR pre-trade
    record reference and an authority stamp. It is NEVER a submission:
    ``is_submission`` is pinned to ``Literal[False]`` so a submission
    package cannot be constructed. There is no credential field.
    """

    operation_id: UUID
    regime: PortalRegime
    disposition: PackageDisposition
    rail: SettlementRail
    settlement_kind: SettlementKind
    cusip: str | None
    net_delivery_quantity: Decimal | None
    net_payment_amount: Decimal | None
    dsor_pre_trade_record_id: UUID
    authority_stamp: dict[str, str]
    quorum_required: bool
    for_human_entry: bool
    is_submission: Literal[False] = False
    notes: str | None = None


class PortalReadback(_Frozen):
    """Beat 5 inbound — operator-entered post-submission portal state.

    ``source`` is pinned to operator readback. The cockpit never obtains
    this by scraping or via credentials.
    """

    operation_id: UUID
    regime: PortalRegime
    source: Literal["operator_readback"] = "operator_readback"
    ingested_at: datetime
    position_balance: Decimal | None = None
    clearing_fund_deficit: Decimal | None = None
    ccp_net_obligation: Decimal | None = None
    intraday_credit_usage: Decimal | None = None
    risk_control_status: str | None = None


class Reconciliation(_Frozen):
    """Beat 5 output — expected-vs-actual diff with per-leg breaks."""

    operation_id: UUID
    regime: PortalRegime
    matched: bool
    breaks: tuple[BreakLeg, ...] = ()
    detail: dict[str, dict[str, str]] = Field(default_factory=dict)


class BreakTicket(_Frozen):
    """A break routed to the workbench with full lineage (Section VII)."""

    break_id: str
    operation_id: UUID
    regime: PortalRegime
    leg: BreakLeg
    detail: str
    dsor_pre_trade_record_id: UUID
    raised_at: datetime
    status: Literal["OPEN_ON_WORKBENCH"] = "OPEN_ON_WORKBENCH"


# ---------------------------------------------------------------------------
# The cockpit
# ---------------------------------------------------------------------------


class ClearingCockpit:
    """The Clearing Operator Cockpit surface.

    One instance per operator session. Holds separate CCP and CSD
    contexts and a per-operation cycle ledger — the replayable lineage
    of the gather -> validate -> prepare -> reconcile cycle (Section IV
    "Audit" is cross-cutting).

    The cockpit reuses :class:`SettlementOperationsAnalyst` for Beat 2:
    the gate logic is not reimplemented here, so there is exactly one
    settlement gate set in the estate (Parity Principle).
    """

    def __init__(
        self,
        dsor_store: DSORStore | None = None,
        *,
        material_magnitude_threshold: Decimal = DEFAULT_MATERIAL_MAGNITUDE,
        halt_check: Callable[[], bool] | None = None,
        doctrine_version: str = "1.6",
        caom_mode: str = "CAOM-001",
    ) -> None:
        self._store = dsor_store if dsor_store is not None else DSORStore(":memory:")
        self._analyst = SettlementOperationsAnalyst()
        self._threshold = material_magnitude_threshold
        self._halt_check = halt_check
        self._doctrine_version = doctrine_version
        self._caom_mode = caom_mode

        # Separate regime contexts — NEVER flattened (Section VI).
        self._ccp_context: dict[UUID, CockpitTasking] = {}
        self._csd_context: dict[UUID, CockpitTasking] = {}

        # Per-operation replayable cycle ledger (Section IV Audit).
        self._ledger: dict[UUID, list[dict]] = {}

        # The break workbench (Section VII).
        self._workbench: list[BreakTicket] = []

    # -- boundary guards ---------------------------------------------------

    def _guard_halt(self, primitive: str) -> None:
        if self._halt_check is not None and self._halt_check():
            raise CockpitHalted(
                f"Tier 0 Halt active — cockpit primitive {primitive!r} refused. "
                "AUR-CANONICAL-001 v1.6 Axiom 9."
            )

    def _context_for(self, regime: PortalRegime) -> dict[UUID, CockpitTasking]:
        return self._ccp_context if regime is PortalRegime.CCP else self._csd_context

    def _ledger_append(self, operation_id: UUID, beat: CycleBeat, obj) -> None:
        self._ledger.setdefault(operation_id, []).append(
            {"beat": beat.value, "at": datetime.now(tz=timezone.utc).isoformat(), "record": obj}
        )

    # -- Beat 1: gather ----------------------------------------------------

    def capture_tasking(
        self,
        *,
        regime: PortalRegime,
        rail: SettlementRail,
        settlement_kind: SettlementKind,
        counterparty_id: str,
        settlement_date: datetime,
        authority_id: str,
        authority_tier: CAOMTier = CAOMTier.T1,
        operation_id: UUID | None = None,
        cusip: str | None = None,
        net_delivery_quantity: Decimal | None = None,
        net_payment_amount: Decimal | None = None,
        ficc_published_net_delivery: Decimal | None = None,
        intraday_credit_limit: Decimal | None = None,
        intraday_credit_current_usage: Decimal | None = None,
        credit_facility_type: CreditFacilityType | None = None,
        ficc_clearing_fund_compliant: bool = True,
        sponsoring_member_id: str | None = None,
        gcf_pool_custodian: GCFPoolCustodian | None = None,
    ) -> CockpitTasking:
        """Beat 1 — structured intake of the transaction picture.

        Stores the tasking in the regime-appropriate context and opens the
        cycle ledger. Purely a capture step: nothing here reaches a portal.
        """
        self._guard_halt("capture_tasking")
        tasking = CockpitTasking(
            operation_id=operation_id or uuid.uuid4(),
            regime=regime,
            rail=rail,
            settlement_kind=settlement_kind,
            counterparty_id=counterparty_id,
            cusip=cusip,
            settlement_date=settlement_date,
            authority_tier=authority_tier,
            authority_id=authority_id,
            captured_at=datetime.now(tz=timezone.utc),
            net_delivery_quantity=net_delivery_quantity,
            net_payment_amount=net_payment_amount,
            ficc_published_net_delivery=ficc_published_net_delivery,
            intraday_credit_limit=intraday_credit_limit,
            intraday_credit_current_usage=intraday_credit_current_usage,
            credit_facility_type=credit_facility_type,
            ficc_clearing_fund_compliant=ficc_clearing_fund_compliant,
            sponsoring_member_id=sponsoring_member_id,
            gcf_pool_custodian=gcf_pool_custodian,
        )
        self._context_for(regime)[tasking.operation_id] = tasking
        self._ledger_append(tasking.operation_id, CycleBeat.GATHER, tasking)
        return tasking

    # -- Beat 2: validate --------------------------------------------------

    def run_validation_gates(self, tasking: CockpitTasking) -> GateResult:
        """Beat 2 — run the tasking through the Settlement Operations Analyst
        gate set (intraday funding -> clearing fund -> net obligation ->
        DSOR lineage). A hold here is caught before anything reaches a
        portal; no package is emitted on a held gate.
        """
        self._guard_halt("run_validation_gates")

        pre_hash = tasking.pre_operation_state_hash()
        lineage_stub = DSORLineageStub(
            operation_id=tasking.operation_id,
            doctrine_version=self._doctrine_version,
            caom_mode=self._caom_mode,
            authority_tier=tasking.authority_tier,
            authority_id=tasking.authority_id,
            initiated_at=tasking.captured_at,
            c2_handoff_id=None,  # operator-direct under CAOM-001
            pre_operation_state_hash=pre_hash,
        )
        dsor_pre_trade_record_id = uuid.uuid4()
        record = SettlementTaskingRecord(
            operation_id=tasking.operation_id,
            rail=tasking.rail,
            settlement_kind=tasking.settlement_kind,
            counterparty_id=tasking.counterparty_id,
            deadline=tasking.settlement_date,
            dsor_pre_trade_record_id=dsor_pre_trade_record_id,
            lineage_stub=lineage_stub,
            net_cusip=tasking.cusip,
            net_delivery_quantity=tasking.net_delivery_quantity,
            net_payment_amount=tasking.net_payment_amount,
            ficc_published_net_delivery=tasking.ficc_published_net_delivery,
            intraday_credit_limit=tasking.intraday_credit_limit,
            intraday_credit_current_usage=tasking.intraday_credit_current_usage,
            credit_facility_type=tasking.credit_facility_type,
            ficc_clearing_fund_compliant=tasking.ficc_clearing_fund_compliant,
            sponsoring_member_id=tasking.sponsoring_member_id,
            gcf_pool_custodian=tasking.gcf_pool_custodian,
        )

        output, dsor_record = self._analyst.run(record, self._store)
        passed = isinstance(output, SettlementTelemetry)
        result = GateResult(
            operation_id=tasking.operation_id,
            regime=tasking.regime,
            passed=passed,
            output_kind=output.kind,
            dsor_pre_trade_record_id=dsor_record.record_id,
            discrepancy_code=None if passed else output.discrepancy_code.value,
            detail=None if passed else output.failure_detail,
        )
        self._ledger_append(tasking.operation_id, CycleBeat.VALIDATE, result)
        return result

    # -- Beat 3: prepare ---------------------------------------------------

    def emit_instruction_package(
        self, tasking: CockpitTasking, gate_result: GateResult
    ) -> InstructionPackage:
        """Beat 3 — emit a governed instruction package, or HOLD.

        Emits only on a clean gate pass AND sub-material magnitude.
        Material magnitude routes to quorum, which is unavailable under
        CAOM-001, so the operation HOLDS (no package). The output is
        always an artifact for human entry — never a submission.
        """
        self._guard_halt("emit_instruction_package")
        if gate_result.operation_id != tasking.operation_id:
            raise CockpitBoundaryError("gate_result/operation_id mismatch")

        authority_stamp = {
            "authority_tier": tasking.authority_tier.value,
            "authority_id": tasking.authority_id,
            "doctrine_version": self._doctrine_version,
            "caom_mode": self._caom_mode,
        }
        base = dict(
            operation_id=tasking.operation_id,
            regime=tasking.regime,
            rail=tasking.rail,
            settlement_kind=tasking.settlement_kind,
            cusip=tasking.cusip,
            net_delivery_quantity=tasking.net_delivery_quantity,
            net_payment_amount=tasking.net_payment_amount,
            dsor_pre_trade_record_id=gate_result.dsor_pre_trade_record_id,
            authority_stamp=authority_stamp,
        )

        if not gate_result.passed:
            pkg = InstructionPackage(
                disposition=PackageDisposition.GATE_HELD,
                quorum_required=False,
                for_human_entry=False,
                notes=(
                    f"Gate held ({gate_result.discrepancy_code}); no package emitted. "
                    "AUR-COCKPIT-001 Section IV Beat 2."
                ),
                **base,
            )
            self._ledger_append(tasking.operation_id, CycleBeat.PREPARE, pkg)
            return pkg

        if self._is_material(tasking):
            pkg = InstructionPackage(
                disposition=PackageDisposition.QUORUM_REQUIRED_HOLD,
                quorum_required=True,
                for_human_entry=False,
                notes=(
                    "Material magnitude — quorum required (default 3-of-5). "
                    "Quorum is unavailable under CAOM-001: operation HOLDS and "
                    "surfaces a CAOM-transition trigger. No package emitted. "
                    "AUR-CUSTODY-001 Section VII; canonical Section V."
                ),
                **base,
            )
            self._ledger_append(tasking.operation_id, CycleBeat.PREPARE, pkg)
            return pkg

        pkg = InstructionPackage(
            disposition=PackageDisposition.EMIT_FOR_HUMAN_ENTRY,
            quorum_required=False,
            for_human_entry=True,
            notes="Validated instruction package for entitled-member entry. Not a submission.",
            **base,
        )
        self._ledger_append(tasking.operation_id, CycleBeat.PREPARE, pkg)
        return pkg

    def _is_material(self, tasking: CockpitTasking) -> bool:
        magnitude = tasking.net_payment_amount
        if magnitude is None:
            magnitude = tasking.net_delivery_quantity
        return magnitude is not None and abs(magnitude) >= self._threshold

    # -- Beat 5: reconcile -------------------------------------------------

    def ingest_portal_readback(
        self,
        *,
        operation_id: UUID,
        regime: PortalRegime,
        position_balance: Decimal | None = None,
        clearing_fund_deficit: Decimal | None = None,
        ccp_net_obligation: Decimal | None = None,
        intraday_credit_usage: Decimal | None = None,
        risk_control_status: str | None = None,
    ) -> PortalReadback:
        """Beat 5 inbound — accept operator-entered post-submission state.

        Readback only. The cockpit never obtains this via credentials or
        scraping (Section V "Prohibited, without exception").
        """
        self._guard_halt("ingest_portal_readback")
        if operation_id not in self._context_for(regime):
            raise CockpitBoundaryError(
                f"readback for unknown {regime.value} operation {operation_id}"
            )
        readback = PortalReadback(
            operation_id=operation_id,
            regime=regime,
            ingested_at=datetime.now(tz=timezone.utc),
            position_balance=position_balance,
            clearing_fund_deficit=clearing_fund_deficit,
            ccp_net_obligation=ccp_net_obligation,
            intraday_credit_usage=intraday_credit_usage,
            risk_control_status=risk_control_status,
        )
        self._ledger_append(operation_id, CycleBeat.RECONCILE, readback)
        return readback

    def reconcile_expected_actual(
        self,
        expected: InstructionPackage,
        readback: PortalReadback,
        *,
        expected_position: Decimal | None = None,
    ) -> Reconciliation:
        """Beat 5 — diff expected vs actual; classify discrepancies by leg.

        Compares the emitted package (expected) against operator readback
        (actual) and classifies any divergence into POSITION / FUNDING /
        CLEARING_FUND / NET_OBLIGATION breaks (Section VII).
        """
        self._guard_halt("reconcile_expected_actual")
        if expected.operation_id != readback.operation_id:
            raise CockpitBoundaryError("expected/readback operation mismatch")

        tasking = self._context_for(readback.regime).get(readback.operation_id)
        breaks: list[BreakLeg] = []
        detail: dict = {}

        # NET_OBLIGATION leg: CCP net obligation vs expected net payment.
        if (
            readback.ccp_net_obligation is not None
            and expected.net_payment_amount is not None
            and readback.ccp_net_obligation != expected.net_payment_amount
        ):
            breaks.append(BreakLeg.NET_OBLIGATION)
            detail["net_obligation"] = {
                "expected": str(expected.net_payment_amount),
                "actual": str(readback.ccp_net_obligation),
            }

        # CLEARING_FUND leg: any positive deficit is a break.
        if readback.clearing_fund_deficit is not None and readback.clearing_fund_deficit > 0:
            breaks.append(BreakLeg.CLEARING_FUND)
            detail["clearing_fund"] = {"deficit": str(readback.clearing_fund_deficit)}

        # FUNDING leg: intraday usage at/above the captured facility limit.
        if (
            readback.intraday_credit_usage is not None
            and tasking is not None
            and tasking.intraday_credit_limit is not None
            and readback.intraday_credit_usage >= tasking.intraday_credit_limit
        ):
            breaks.append(BreakLeg.FUNDING)
            detail["funding"] = {
                "usage": str(readback.intraday_credit_usage),
                "limit": str(tasking.intraday_credit_limit),
            }

        # POSITION leg: readback position vs expected position (delivery qty).
        exp_pos = expected_position
        if exp_pos is None and expected.net_delivery_quantity is not None:
            exp_pos = expected.net_delivery_quantity
        if (
            readback.position_balance is not None
            and exp_pos is not None
            and readback.position_balance != exp_pos
        ):
            breaks.append(BreakLeg.POSITION)
            detail["position"] = {
                "expected": str(exp_pos),
                "actual": str(readback.position_balance),
            }

        recon = Reconciliation(
            operation_id=readback.operation_id,
            regime=readback.regime,
            matched=not breaks,
            breaks=tuple(breaks),
            detail=detail,
        )
        self._ledger_append(readback.operation_id, CycleBeat.RECONCILE, recon)
        return recon

    def raise_break(
        self, reconciliation: Reconciliation, dsor_pre_trade_record_id: UUID
    ) -> list[BreakTicket]:
        """Route each reconciliation break to the workbench with lineage.

        One ticket per broken leg, each carrying the DSOR pre-trade record
        reference so the workbench can replay the full cycle (Section VII).
        """
        self._guard_halt("raise_break")
        tickets: list[BreakTicket] = []
        for leg in reconciliation.breaks:
            ticket = BreakTicket(
                break_id=f"BRK-{str(reconciliation.operation_id)[:8]}-{leg.value}",
                operation_id=reconciliation.operation_id,
                regime=reconciliation.regime,
                leg=leg,
                detail=json.dumps(reconciliation.detail.get(leg.value.split("_")[0], {})),
                dsor_pre_trade_record_id=dsor_pre_trade_record_id,
                raised_at=datetime.now(tz=timezone.utc),
            )
            tickets.append(ticket)
            self._workbench.append(ticket)
        return tickets

    # -- Audit (cross-cutting) --------------------------------------------

    def get_cycle_ledger(self, operation_id: UUID) -> list[dict]:
        """Return the replayable gather->validate->prepare->reconcile
        lineage for one operation (Section IV Audit)."""
        return list(self._ledger.get(operation_id, []))

    @property
    def workbench(self) -> list[BreakTicket]:
        """Open break tickets routed to the workbench."""
        return list(self._workbench)


__all__ = [
    "BreakLeg",
    "BreakTicket",
    "ClearingCockpit",
    "CockpitBoundaryError",
    "CockpitHalted",
    "CockpitTasking",
    "CycleBeat",
    "GateResult",
    "InstructionPackage",
    "PackageDisposition",
    "PortalReadback",
    "PortalRegime",
    "Reconciliation",
]
