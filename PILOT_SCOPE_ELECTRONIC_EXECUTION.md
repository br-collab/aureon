# PILOT_SCOPE_ELECTRONIC_EXECUTION

## 1. Pilot Objective

This pilot is designed to validate Aureon as a pre-trade governance and decision-lineage layer for Electronic Execution in single-name equities. The pilot tests whether trade intent can be structured, challenged, approved, and recorded in a single governed workflow before release into the existing execution stack. Success requires clear ownership of decision context, reliable approval lineage, and clean downstream handoff into OMS and EMS without disrupting trader workflows. This pilot validates that a governed decision layer improves control, reduces ambiguity, and integrates without disrupting execution workflows.

## 2. Why Electronic Execution (Justification)

Electronic Execution is the appropriate Phase 1 pilot because it combines high order volume, repeatable workflow patterns, and established OMS/EMS operating models. That makes it the most practical environment for testing whether pre-trade governance can be strengthened without changing how the desk executes orders. Today, pre-trade decision context is often fragmented across PM intent, trader judgment, risk interpretation, compliance review, and local workflow practices, with reconstruction required after the fact when questions arise. Electronic Execution provides the most controlled and repeatable environment to validate pre-trade governance improvements without disrupting core execution systems. It also offers a measurable improvement opportunity through lower exception rates, clearer release conditions, and more consistent supervisory evidence.

## 2A. What Changes from Current State

In the current model, pre-trade decisions are distributed across systems, communications, and individual judgment, with no single authoritative record prior to execution.

In the pilot model:

- trade intent is structured before execution
- constraints are made explicit rather than implicit
- approvals are recorded as part of the workflow, not reconstructed after the fact
- release into OMS or EMS occurs only after governed approval is complete

The execution process itself does not change. The decision process before execution becomes structured, governed, and auditable.

## 3. In-Scope Workflow

1. A PM, model, or signal source generates trade intent for a single-name equity.
2. That intent enters Aureon before order creation in the execution stack.
3. Aureon structures the intent into a governed decision record with instrument, direction, sizing, account or mandate context, rationale, and required control metadata.
4. Aureon applies policy and mandate checks to determine whether the proposed trade is permissible, restricted, or requires exception handling.
5. Aureon presents risk framing and constraint visibility so the release decision is made with explicit limits and conditions.
6. Aureon routes the decision through the required approval chain based on product, account, materiality, and control rules.
7. Role-based approvers review, challenge, approve, condition, escalate, or reject the decision before release.
8. Aureon acts as the control gate for release. No order is transmitted to OMS or EMS until required role-based approvals are complete within Aureon.
9. Execution occurs outside Aureon in the existing OMS, EMS, broker, and venue stack.
10. Execution feedback is returned to Aureon from downstream systems.
11. Aureon attaches that feedback to the original decision record for replay, supervisory evidence, and audit support.

## 4. Out-of-Scope Workflow

The following items are outside the scope of this pilot:

- Program Trading, which remains a later phase after Electronic Execution validation
- Delta One and structured products
- Prime Brokerage integration beyond basic awareness of financing context
- clearing, settlement, custody, and treasury ownership
- OMS replacement or EMS replacement
- smart order routing ownership
- autonomous execution
- release of trades without human approval

## 5. Actors and Responsibilities

### Portfolio Manager (PM)

In the pilot, the PM provides investment intent, account or mandate context, and the rationale for the trade idea. The PM does not own execution strategy, venue interaction, or downstream order lifecycle management.

### Trader

In the pilot, the Trader reviews the governed intent packet, confirms execution readiness, and executes through existing OMS or EMS tools once approvals are complete. The Trader retains full control over execution strategy and timing within the constraints defined at approval. The Trader does not own policy determination, independent risk approval, or compliance approval.

### Risk

In the pilot, Risk reviews exposure, sizing, concentration, and any release constraints that should influence whether the trade proceeds. Risk does not own investment intent, execution strategy, or OMS lifecycle management.

### Compliance

In the pilot, Compliance reviews policy, mandate, restricted-list, and regulatory considerations relevant to release. Compliance does not own trade selection, execution strategy, or post-trade processing.

### Aureon

In the pilot, Aureon structures trade intent, applies governance checks, coordinates approval routing, records approval lineage, and captures replay and evidence context. Aureon does not perform autonomous execution, does not release orders without required human approval, and does not own OMS, EMS, SOR, clearing, settlement, or legal books and records.

### OMS

In the pilot, the OMS receives approved intent for order staging and parent-order handling where that is the desk standard. The OMS does not own the governed pre-trade decision record created in Aureon.

### EMS

In the pilot, the EMS supports trader execution workflow, execution strategy selection, and venue interaction where applicable. The EMS does not own pre-trade governance or approval lineage.

## 6. Integration Points

The pilot should assume staged, practical integration rather than deep platform replacement. PM and signal inputs may enter Aureon through lightweight intake workflows, structured uploads, or application interfaces appropriate to the desk. Policy and risk inputs should be connected at a logical level, so Aureon can consume applicable rules, constraints, and control outputs without requiring a full re-platform of existing control systems. OMS integration should support handoff of approved intent into standard order-staging workflows, with parent-order creation remaining in the OMS where that is the desk norm. EMS integration should support receipt of release context and execution constraints where the desk executes through the EMS. Execution feedback should be returned from available downstream sources using the lightest reliable integration path sufficient to attach status, fills, breaks, or confirms to the decision record. The pilot must accommodate variation in desk workflows rather than assume full standardization, ensuring Aureon can operate across differing OMS/EMS configurations without requiring uniform behavior across all trading teams.

## 7. Core Decisions Governed by Aureon

For each in-scope order, Aureon must capture:

- trade intent
- instrument and direction
- sizing
- account or mandate context
- applicable policy, mandate, and risk constraints
- approval lineage
- execution constraints where applicable to release

The pilot is successful only if those elements are recorded before execution and remain attached to the downstream execution outcome.

## 8. KPIs and Success Metrics

The pilot should measure the following outcomes:

- reduction in pre-trade exceptions
- reduction in manual reconstruction effort
- reduction in time required to reconstruct pre-trade decision context for supervisory, audit, or risk review
- approval cycle time
- percentage of orders with complete decision lineage
- percentage of clean handoffs into OMS or EMS
- qualitative improvement in control confidence across Trading, Risk, Compliance, and supervisory stakeholders

Success metrics should be defined against a baseline process so the pilot demonstrates operational improvement rather than anecdotal benefit.

## 9. Risks and Dependencies

The principal risks and dependencies are practical rather than theoretical. OMS and EMS integration may be more complex than expected if desk workflows vary materially across teams. User adoption may be uneven if PMs or Traders view Aureon as additional process rather than clearer release discipline. Risk and Compliance alignment is essential because the pilot depends on agreement about which checks are authoritative before release. Data availability may also limit the quality of decision context if account, mandate, or control inputs are incomplete at the point of intent formation. These are manageable risks, but they must be addressed directly in pilot planning.

## 10. Pilot Exit Criteria

Expansion beyond the pilot should require proof that Aureon can operate as a reliable DSOR before execution without slowing or destabilizing desk workflows. Success means the pilot demonstrates complete decision lineage for the defined workflow, clean OMS or EMS handoff, measurable reduction in exceptions or reconstruction effort, and credible support from Trading, Risk, Compliance, and Technology stakeholders. Success also requires evidence that the workflow can scale across multiple desks without requiring material redesign of approval logic or system integration patterns. Failure means the pilot cannot establish clear ownership, cannot produce reliable decision records, or cannot integrate with acceptable workflow impact. Readiness to expand to Program Trading should depend on whether the Electronic Execution pilot proves that governed pre-trade decision handling can scale with control integrity and low operational disruption.

## 11. Pilot Summary

This pilot positions Aureon as the DSOR before execution for Electronic Execution in single-name equities. It uses Electronic Execution as the validation layer because the workflow is repeatable, measurable, and compatible with low-disruption integration into existing OMS and EMS environments. Aureon augments those systems rather than replacing them, applies role-based human governance before release, and preserves decision lineage for replay and supervision. The pilot should be judged on measurable improvement in control quality, release clarity, and operational readiness.
