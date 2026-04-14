# TARGET_OPERATING_MODEL

## 1. Purpose

This document defines the Phase 1 target operating model for Aureon as an Equities-first pre-trade governance and execution-intelligence overlay. A target operating model is required because institutional pre-trade workflows often distribute decision ownership across portfolio management, trading, risk, compliance, controls, and financing functions without maintaining a single governed record of how a trade moved from intent to release. Aureon is designed to close that gap. It sits between portfolio intent and the incumbent OMS/EMS stack as the Decision System of Record (DSOR) before execution. Its role is to structure intent, apply governance, record challenge and approval, and preserve evidence. Its role is not to replace the execution stack or downstream books and records.

## 2. Phase 1 Product Definition

Phase 1 positions Aureon as an Equities-first platform focused on pre-trade governance and execution intelligence. The initial pilot is Electronic Execution, beginning with single-name equities and governed release into existing OMS or EMS workflows. In this model, Aureon acts as the DSOR before execution. It captures investment intent, applies policy and risk framing, routes human approvals, and records decision lineage before an order is handed to the execution stack. Aureon is deployed as an overlay to OMS/EMS, not as a system replacement. OMS, EMS, SOR, and post-trade infrastructure remain in place and continue to own their existing operational responsibilities.

## 2A. What Changes in the Operating Workflow

In the current model, portfolio intent often moves directly into OMS workflows with fragmented pre-trade checks distributed across functions. In the Phase 1 Aureon model, portfolio intent is first structured, governed, and approved within Aureon before entering the execution stack.

Traders receive a governed intent packet that includes policy constraints, risk framing, and approval lineage, rather than reconstructing decision context at the point of execution. This reduces ambiguity at release and improves execution readiness without changing the trader's execution tools.

## 3. Business Scope

### In Scope (Phase 1)

- Electronic Execution workflows
- single-name equities
- governed pre-trade decision capture
- policy, mandate, and control checks before release
- risk framing and constraint visibility
- role-based approval routing and decision recording
- release of approved intent into OMS or EMS
- ingestion of execution feedback for replay and evidence

### Near-Term Expansion

- Program Trading, once the Electronic Execution operating model is proven and the approval, evidence, and integration patterns are stable

### Later Expansion

- Delta One workflows as a controlled extension
- Prime Brokerage and financing-linked workflows where pre-trade financing context materially affects release decisions
- OTC and structured products only as later controlled expansion after Phase 1 operating controls are established

## 4. Role Ownership Model

### Portfolio Manager (PM)

The PM owns investment intent, target exposure, account or mandate alignment, and the rationale for the trade idea. The PM reviews the structured intent record, the constraints attached to the idea, and any decision-support output required to confirm that the expression is still consistent with portfolio objectives. The PM approves the investment intent where the workflow requires PM authority. The PM does not own execution strategy, venue selection, order lifecycle management, or the release of an order outside the approved governance framework.

### Trader

The Trader owns execution readiness, order expression for the desk, execution constraints relevant to market conditions, and the handoff into OMS or EMS once approvals are complete. The Trader reviews the governed intent packet, risk framing, compliance constraints, and any execution restrictions attached to the release. The Trader approves release where the workflow requires trading authority. The Trader does not own policy determination, independent risk sign-off, compliance sign-off, or post-trade books and records.

### Risk

Risk owns independent challenge of exposure, concentration, liquidity, sizing, and any pre-trade constraint that should influence release. Risk reviews the proposed expression of the trade, the affected account or mandate, the risk framing attached to the decision, and the conditions under which the trade may proceed. Risk approves or blocks decisions where risk authority is required. Risk does not own investment intent, trader execution strategy, venue interaction, or OMS lifecycle management.

### Compliance

Compliance owns the interpretation and enforcement of applicable policy, mandate, restricted list, and regulatory constraints that must be satisfied before release. Compliance reviews decision context, account eligibility, control exceptions, and the record of approvals where required. Compliance approves, conditions, or blocks decisions where compliance authority is required. Compliance does not own investment selection, execution strategy, or downstream post-trade processing.

### Cybersecurity / Controls

Cybersecurity and Controls own control design, access boundaries, segregation-of-duties standards, supervisory requirements, and evidence requirements for governed workflows. This function reviews whether approval paths, user entitlements, and control checkpoints align with the institution's operating model. It approves control structures, not trades as a routine desk activity, unless the workflow explicitly requires a control override authority. Cybersecurity and Controls do not own trade intent, execution strategy, or trading decisions on economic merit.

### Prime / Financing

Where financing context is relevant, Prime or Financing owns the assessment of borrow availability, financing feasibility, margin impact, and balance sheet implications relevant to release. This function reviews whether the intended trade can be supported within current financing conditions. It approves or conditions the financing aspect of release only where the workflow requires it. Prime or Financing does not own portfolio intent, policy approval, or execution routing.

### Aureon System

Aureon owns intent structuring, governance workflow, policy-check orchestration, risk framing visibility, approval routing, decision lineage, and evidence capture before execution. It reviews submitted intent against configured rules, control requirements, and approval paths. It records approvals and blocks release when required approvals are absent. Aureon does not autonomously approve trades, does not perform autonomous trade execution, and does not own execution strategy, order lifecycle management, SOR, clearing, settlement, or legal books and records.

### OMS

The OMS owns order staging, blotter state, allocations, parent-order lifecycle management, and order-state persistence after release from Aureon. The OMS reviews the governed intent packet only to the extent required for downstream order creation and workflow handling. The OMS does not own the pre-trade approval lineage created within Aureon. The OMS also does not replace Aureon's role as DSOR before execution.

### EMS

The EMS owns trader execution workflow, order handling at the point of execution, algo or strategy selection, trader controls, and venue interaction as delegated by the desk operating model. The EMS reviews the released order instructions and execution constraints received from upstream systems. The EMS does not own pre-trade governance, approval lineage, or the authoritative record of why the order was approved for release.

### Post-Trade Systems

Post-trade systems own confirmations, allocations finalization where applicable, settlement processing, breaks management, custody, accounting, and legal books and records. These systems review execution outcomes and perform downstream processing based on their own operating controls. They do not own the pre-trade decision record created in Aureon, and Aureon does not replace their role as downstream systems of record.

## 5. Decision Lifecycle (End-to-End)

1. Intent is created by a PM, model, signal source, or research input and is expressed as a proposed trade or exposure change.
2. Aureon structures that intent into a governed decision record with instrument, direction, sizing, account or mandate context, rationale, and required control metadata.
3. Aureon applies policy, mandate, and control checks to determine whether the intent is permissible, restricted, or requires exception handling before release.
4. Aureon presents risk framing and constraint visibility, including the conditions and limits under which the trade may proceed.
5. Where applicable, financing context is attached so the decision reflects borrow, margin, or balance-sheet feasibility before release.
6. Aureon routes the decision through the required human review chain based on product, account, materiality, and control rules.
7. The relevant roles approve, condition, escalate, or reject the decision through configurable role-based authority. Risk and Compliance operate as independent challenge functions within the approval chain, ensuring that economic intent, policy constraints, and regulatory requirements are validated before release.
8. Only after required approvals are complete does Aureon release the governed intent packet to OMS or EMS for downstream order handling. In Phase 1, Aureon typically releases approved intent into the OMS as a governed parent-order construct, which then flows into EMS for execution. Direct release to EMS may be supported for specific desk configurations.
9. Execution occurs outside Aureon in the incumbent OMS, EMS, broker, and venue stack.
10. Execution feedback, including status, fills, breaks, and confirms as available, is returned to Aureon from downstream systems.
11. Aureon captures that downstream feedback against the original decision record so the institution can replay what was intended, what was approved, what constraints applied, and what occurred in execution.

## 6. Human Approval Model

Aureon uses role-based approval, not named-person approval, as the foundation of the control model. Approval chains are configurable by business line, account type, product scope, trade materiality, and exception conditions. The operating model supports segregation of duties by separating intent creation, independent challenge, and release authority across distinct roles where required. It also supports escalation logic so a decision can be routed to supervisory or delegated authority when thresholds, exceptions, or unavailable approvers require it. Delegation is based on role and control policy, not on informal substitution. Aureon does not release trades without human approval. No order is released into OMS or EMS until the required role-based approvals are complete.

## 7. System Boundaries

### Aureon Owns

- intent formation as a governed decision record before execution
- governance workflow and control enforcement
- policy, mandate, and rule checks
- risk framing and constraint visibility
- approval routing and approval lineage
- decision evidence, replay context, and audit packaging

### Aureon Informs

- OMS by providing approved, governed intent for downstream order staging
- EMS by providing approved release context and execution constraints
- downstream systems by attaching decision lineage and evidence context to execution outcomes where needed

### Aureon Does NOT Own

- order lifecycle management after release
- execution strategy or algo selection
- venue routing or SOR responsibilities
- broker or exchange session ownership
- clearing, settlement, custody, or treasury processing
- legal books and records
- post-trade system-of-record functions

## 8. Doctrine to Institutional Mapping

### Verana

Institutional translation: control and governance boundary layer.  
Phase 1 responsibility: enforce session, control, and governance boundaries around what may enter the governed decision process and under what supervisory conditions a decision may proceed.

### Mentat

Institutional translation: decision intelligence layer.  
Phase 1 responsibility: support intent synthesis, scenario framing, and structured decision support so the trade idea is expressed clearly before approval.

### Kaladan

Institutional translation: lifecycle and evidence orchestration layer.  
Phase 1 responsibility: maintain approval lineage, attach downstream execution feedback to the governed decision record, and preserve replay and audit context.

### Thifur

Institutional translation: trader and execution-support layer.  
Phase 1 responsibility: support pre-trade execution preparation, including how approved intent is framed for trader review and governed release into OMS or EMS.

## 9. Phase 1 Out-of-Scope

- autonomous execution
- release of orders without human approval
- full OMS replacement
- full EMS replacement
- SOR ownership
- broker or venue session ownership
- settlement ownership
- treasury ownership
- legal books and records
- full cross-asset expansion beyond the controlled Equities-first scope

## 10. Operating Model Summary

In Phase 1, Aureon operates as the DSOR before execution for Equities-first workflows, beginning with Electronic Execution. It is an overlay to OMS and EMS, not a replacement for them. It applies governed intent capture, policy checks, risk framing, approval lineage, and evidence preservation before release, while execution remains outside Aureon. AI is controlled, role-bound, and subject to human-in-the-loop approval. The result is a pilot-ready operating model with clear institutional ownership, explicit control points, and clean boundaries across Aureon, OMS, EMS, and downstream post-trade systems. This model is designed to reduce pre-trade exceptions, shorten approval cycles, and improve auditability by ensuring that decision context is fully defined before execution.
