"""Settlement Operations Analyst — Tier 1 · Thifur-R.

Deterministic settlement instruction routing and execution monitoring.
Per AUR-CANONICAL-001 v1.5.1 Section IV (settlement-operations-analyst v0.3)
and AUR-CUSTODY-001 v1.0 Section VI (R-class roles).

Six primitives execute in sequence (pre-routing gates 4→5→6→1, then
routing and confirmation). Any gate failure emits a
:class:`~aureon.agents.tier1.outputs.SettlementEscalation` to the DSOR
and returns immediately — no instruction is ever issued after a gate
failure. R-class guardrails preserved unchanged from v0.2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from aureon.agents.tier1.outputs import (
    DiscrepancyCode,
    SettlementEscalation,
    SettlementOutput,
    SettlementTaskingRecord,
    SettlementTelemetry,
)
from aureon.dsor import DSORRecord, DSORStore


class SettlementOperationsAnalyst:
    """Tier 1 · Thifur-R — Settlement Operations Analyst.

    Executes the six-primitive settlement workflow and persists the result
    to the DSOR. Fully deterministic: zero variance, no path selection.

    Usage::

        analyst = SettlementOperationsAnalyst()
        output, record = analyst.run(tasking, store)
        # output: SettlementTelemetry | SettlementEscalation
        # record: DSORRecord (persisted; record.record_id for replay)
    """

    def run(
        self,
        tasking: SettlementTaskingRecord,
        store: DSORStore,
        *,
        now: datetime | None = None,
    ) -> tuple[SettlementOutput, DSORRecord]:
        """Execute the settlement operations workflow.

        Pre-routing gates fire in order (funding → clearing fund →
        net obligation → DSOR lineage). The first failure emits a
        :class:`SettlementEscalation`, persists it to the DSOR, and
        returns early — no instruction is issued.

        On a clean gate pass, routes the instruction and emits
        :class:`SettlementTelemetry` to the DSOR.

        Args:
            tasking: C2-delivered tasking record (frozen).
            store: DSOR store for output persistence.
            now: Override execution timestamp (testing only).

        Returns:
            ``(output, record)`` where ``output`` is the emitted
            :data:`SettlementOutput` and ``record`` is the persisted
            :class:`DSORRecord` (``record.record_id`` may be used to
            replay from the DSOR).
        """
        emitted_at = now if now is not None else datetime.now(tz=UTC)

        # Gate 4 (v0.3): intraday funding position
        esc = self._monitor_intraday_funding_position(tasking, emitted_at)
        if esc is not None:
            return esc, store.append(esc, dtg=emitted_at)

        # Gate 5 (v0.3): FICC clearing fund compliance
        esc = self._verify_ficc_clearing_fund_compliance(tasking, emitted_at)
        if esc is not None:
            return esc, store.append(esc, dtg=emitted_at)

        # Gate 6 (v0.3): FICC net settlement obligation consistency
        esc = self._model_ficc_net_settlement_obligation(tasking, emitted_at)
        if esc is not None:
            return esc, store.append(esc, dtg=emitted_at)

        # Gate 1: DSOR lineage consistency
        esc = self._verify_dsor_pre_trade_record(tasking, emitted_at)
        if esc is not None:
            return esc, store.append(esc, dtg=emitted_at)

        # Primitive 2: route settlement instruction
        instruction_ref = self._route_settlement_instruction(tasking)

        # STUB — Primitive 3: match_rail_confirmation.
        # NOT YET REAL. Production path: await the rail-assigned acknowledgment
        # reference (FICC CNS sequence number or Fedwire end-to-end reference),
        # validate it against the instruction parameters and DSOR intent, and
        # apply the five-second internal alert threshold (operational SLA;
        # no US statutory equivalent governs settlement-confirmation timing). Current
        # stub sets rail_acknowledgment_dtg = emitted_at and skips validation.
        telemetry = SettlementTelemetry(
            operation_id=tasking.operation_id,
            task_id=tasking.task_id,
            doctrine_version=tasking.doctrine_version,
            lineage_stub=tasking.lineage_stub,
            emitted_at=emitted_at,
            rail=tasking.rail,
            settlement_kind=tasking.settlement_kind,
            instruction_reference=instruction_ref,
            net_cusip=tasking.net_cusip,
            net_delivery_quantity=tasking.net_delivery_quantity,
            net_payment_amount=tasking.net_payment_amount,
            rail_acknowledgment_dtg=emitted_at,
            clearing_fund_compliant=tasking.ficc_clearing_fund_compliant,
            intraday_credit_usage_at_execution=tasking.intraday_credit_current_usage,
            intraday_credit_limit=tasking.intraday_credit_limit,
            sponsoring_member_id=tasking.sponsoring_member_id,
            gcf_pool_custodian=tasking.gcf_pool_custodian,
        )
        return telemetry, store.append(telemetry, dtg=emitted_at)

    # ------------------------------------------------------------------
    # Primitive 4 (v0.3): monitor_intraday_funding_position
    # ------------------------------------------------------------------

    def _monitor_intraday_funding_position(
        self,
        tasking: SettlementTaskingRecord,
        now: datetime,
    ) -> SettlementEscalation | None:
        """Hold if intraday credit usage is at or above the facility limit."""
        if (
            tasking.intraday_credit_limit is not None
            and tasking.intraday_credit_current_usage is not None
            and tasking.intraday_credit_current_usage >= tasking.intraday_credit_limit
        ):
            return self._make_escalation(
                tasking,
                now,
                DiscrepancyCode.INTRADAY_CREDIT_THRESHOLD,
                (
                    "Intraday credit usage at or above facility limit. "
                    "Pre-routing hold. Instruction not issued. "
                    "Primitive: monitor_intraday_funding_position. "
                    "AUR-CANONICAL-001 v1.5.1 Section IV."
                ),
                intraday_credit_usage=tasking.intraday_credit_current_usage,
                intraday_credit_limit=tasking.intraday_credit_limit,
            )
        return None

    # ------------------------------------------------------------------
    # Primitive 5 (v0.3): verify_ficc_clearing_fund_compliance
    # ------------------------------------------------------------------

    def _verify_ficc_clearing_fund_compliance(
        self,
        tasking: SettlementTaskingRecord,
        now: datetime,
    ) -> SettlementEscalation | None:
        """Hold if FICC clearing fund contribution (VaR-based) is deficient."""
        if not tasking.ficc_clearing_fund_compliant:
            return self._make_escalation(
                tasking,
                now,
                DiscrepancyCode.CLEARING_FUND_DEFICIENCY,
                (
                    "FICC clearing fund contribution (VaR-based) deficient. "
                    "Pre-routing hold. Instruction not issued. "
                    "Primitive: verify_ficc_clearing_fund_compliance. "
                    "AUR-CANONICAL-001 v1.5.1 Section IV."
                ),
                intraday_credit_usage=tasking.intraday_credit_current_usage,
                intraday_credit_limit=tasking.intraday_credit_limit,
                clearing_fund_deficiency=True,
            )
        return None

    # ------------------------------------------------------------------
    # Primitive 6 (v0.3): model_ficc_net_settlement_obligation
    # ------------------------------------------------------------------

    def _model_ficc_net_settlement_obligation(
        self,
        tasking: SettlementTaskingRecord,
        now: datetime,
    ) -> SettlementEscalation | None:
        """Hold if tasking net delivery diverges from FICC's published figure."""
        if (
            tasking.ficc_published_net_delivery is not None
            and tasking.net_delivery_quantity is not None
            and tasking.ficc_published_net_delivery != tasking.net_delivery_quantity
        ):
            return self._make_escalation(
                tasking,
                now,
                DiscrepancyCode.NET_OBLIGATION_MISMATCH,
                (
                    "FICC net settlement obligation does not match "
                    "FICC-published net delivery position. Pre-routing hold. "
                    "Primitive: model_ficc_net_settlement_obligation. "
                    "AUR-CANONICAL-001 v1.5.1 Section IV."
                ),
                intraday_credit_usage=tasking.intraday_credit_current_usage,
                intraday_credit_limit=tasking.intraday_credit_limit,
                net_obligation_discrepancy=(
                    f"tasking={tasking.net_delivery_quantity!s}; "
                    f"ficc_published={tasking.ficc_published_net_delivery!s}"
                ),
            )
        return None

    # ------------------------------------------------------------------
    # Primitive 1: verify_dsor_pre_trade_record
    # ------------------------------------------------------------------

    def _verify_dsor_pre_trade_record(
        self,
        tasking: SettlementTaskingRecord,
        now: datetime,
    ) -> SettlementEscalation | None:
        """Verify lineage stub operation_id matches the tasking operation_id."""
        if tasking.lineage_stub.operation_id != tasking.operation_id:
            return self._make_escalation(
                tasking,
                now,
                DiscrepancyCode.DSOR_MISMATCH,
                (
                    "Lineage stub operation_id does not match tasking operation_id. "
                    "DSOR pre-trade record verification failed. "
                    "Primitive: verify_dsor_pre_trade_record. "
                    "AUR-CANONICAL-001 v1.5.1 Section IV."
                ),
                intraday_credit_usage=tasking.intraday_credit_current_usage,
                intraday_credit_limit=tasking.intraday_credit_limit,
            )
        return None

    # ------------------------------------------------------------------
    # Primitive 2: route_settlement_instruction
    # ------------------------------------------------------------------

    def _route_settlement_instruction(self, tasking: SettlementTaskingRecord) -> str:
        """Generate a deterministic routing reference from rail + task_id.

        Production replaces this with the rail-assigned acknowledgment
        reference (FICC CNS sequence number or Fedwire end-to-end reference).
        """
        task_hex = str(tasking.task_id).replace("-", "")[:12].upper()
        return f"{tasking.rail.value.upper()}-{task_hex}"

    # ------------------------------------------------------------------
    # Internal factory
    # ------------------------------------------------------------------

    def _make_escalation(
        self,
        tasking: SettlementTaskingRecord,
        now: datetime,
        code: DiscrepancyCode,
        detail: str,
        *,
        intraday_credit_usage: Decimal | None = None,
        intraday_credit_limit: Decimal | None = None,
        clearing_fund_deficiency: bool = False,
        net_obligation_discrepancy: str | None = None,
    ) -> SettlementEscalation:
        return SettlementEscalation(
            operation_id=tasking.operation_id,
            task_id=tasking.task_id,
            doctrine_version=tasking.doctrine_version,
            lineage_stub=tasking.lineage_stub,
            emitted_at=now,
            rail=None,
            discrepancy_code=code,
            failure_detail=detail,
            intraday_credit_usage=intraday_credit_usage,
            intraday_credit_limit=intraday_credit_limit,
            clearing_fund_deficiency=clearing_fund_deficiency,
            net_obligation_discrepancy=net_obligation_discrepancy,
        )
