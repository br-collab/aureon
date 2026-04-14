# REFACTOR_NOTES

## What Was Moved

The refactor introduced an explicit `aureon/` package to make the Phase 1 architecture visible in code:

- `aureon/config/settings.py`
  Stores repository-level settings such as the persisted state file and error log paths.

- `aureon/persistence/store.py`
  Owns save and load behavior for the local JSON state snapshot, including salvage logic for corrupted state files.

- `aureon/policy_engine/service.py`
  Owns pre-trade policy, mandate, and risk-framing checks for pending decisions. This is now the explicit boundary for DSOR pre-trade evaluation.

- `aureon/approval_service/service.py`
  Owns role-based decision resolution and release control. This is now the explicit boundary that enforces no governed release without completed approval.

- `aureon/evidence_service/service.py`
  Owns trade-report construction and compliance PDF generation. This is now the explicit boundary for decision lineage, replay context, and audit packaging.

- `aureon/integration_adapters/fix_adapter.py`
  Holds the FIX translation stub under an explicit integration boundary.

- `aureon/integration_adapters/oms_adapter.py`
  Defines the governed OMS parent-order handoff packet for Phase 1 release.

- `aureon/integration_adapters/ems_adapter.py`
  Defines the governed EMS release packet for desks that release directly into EMS.

The root `fix_adapter.py` file now acts as a compatibility wrapper so existing references still work while the real adapter lives under `aureon/integration_adapters/`.

## Why It Was Moved

The goal was to align the implementation with the documented Phase 1 product model:

- Aureon is the DSOR before execution.
- Approval and governed release are not generic route behavior; they are control services.
- OMS/EMS handoff belongs behind integration adapters, not mixed with governance logic.
- Evidence and replay belong in a dedicated service, not inside route handlers.
- Persistence belongs behind an explicit storage boundary rather than being embedded in server flow.

This is a structural refactor, not a net-new product expansion. The extracted modules were chosen because they correspond directly to the operating model described in `README.md`, `MD_BRIEF.md`, `TARGET_OPERATING_MODEL.md`, and `PILOT_SCOPE_ELECTRONIC_EXECUTION.md`.

## Architectural Boundaries That Now Exist

The following boundaries are now explicit in code:

- DSOR pre-trade evaluation boundary
  `aureon/policy_engine/service.py`
  This module evaluates pending decisions before release and caches pre-trade results for downstream evidence.

- Approval and release-control boundary
  `aureon/approval_service/service.py`
  This module enforces role-based resolution and prevents governed release when approval is missing or the system is halted.

- OMS / EMS integration boundary
  `aureon/integration_adapters/`
  OMS and EMS handoff payloads are now built outside the governance route logic, and FIX remains explicitly under integration adapters.

- Evidence / replay / audit boundary
  `aureon/evidence_service/service.py`
  Decision-lineage artifacts and compliance reports are now built in a dedicated service.

- Persistence boundary
  `aureon/persistence/store.py`
  The JSON state snapshot is now handled by a dedicated persistence module.

- Configuration boundary
  `aureon/config/settings.py`
  Filesystem-level settings are now separated from route and governance logic.

## What Remains Structurally Compressed

`server.py` remains the main runtime file and still contains substantial compressed logic, including:

- initial state and reference data definitions
- market data and simulation logic
- macro and OFR data logic
- thesis-analysis logic
- email composition and scheduling
- treasury and settlement views
- governance halt and doctrine update routes
- most Flask route registration

The refactor deliberately targeted the highest-value Phase 1 boundaries first, rather than attempting a risky full rewrite in one pass.

## What Should Be Refactored Next

The next highest-value decomposition steps are:

1. Extract API route registration into `aureon/api/`
   This would move Flask route wiring out of `server.py` and make the service boundaries even clearer.

2. Extract state models and reference data into `aureon/core/`
   The current global state dictionary, initial positions, allocation targets, and instrument metadata are still embedded in `server.py`.

3. Remove or isolate non-Phase-1-adjacent prototype logic
   Treasury, settlement, cash sweep, and thesis-analysis logic should either be clearly marked as downstream/contextual prototype surfaces or moved into separate modules outside the Phase 1 governance core.

## Known Tradeoffs And Temporary Compromises

- `server.py` still contains the legacy helper implementations alongside the new wrappers. The runtime now uses the explicit service boundaries for persistence, approval, pre-trade checks, and evidence, but the file is not yet fully reduced.

- The UI remains a single `index.html` file. This is intentional for now to avoid overengineering the presentation layer during a backend boundary refactor.

- The prototype still contains broader legacy concepts such as treasury and settlement views. They were not expanded, but they also were not fully removed in this pass because the goal was structural alignment without unnecessary regression.

- OMS and EMS adapters currently build governed handoff payloads rather than opening live sessions. That is consistent with the Phase 1 overlay model and keeps execution ownership outside Aureon.

## Behavior Notes

- The prototype remains importable and the main backend entrypoint remains `server.py`.

- Decision resolution now flows through `aureon/approval_service/service.py`.

- Pre-trade decision checks now flow through `aureon/policy_engine/service.py`.

- Trade evidence and compliance-report generation now flow through `aureon/evidence_service/service.py`.

- State save/load now flow through `aureon/persistence/store.py`.

- Approved releases now generate explicit OMS or EMS handoff payloads and store them under `integration_handoffs` in runtime state.
