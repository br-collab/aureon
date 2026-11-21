# Changelog

## Unreleased

Phase A: equities surveillance reads order and fill rows from an L.C. (Legiones Cannenses) lifecycle export. `screen_equities` no longer accepts a caller-built tuple. A wash pair in that export is flagged. A row with the beneficial-owner field removed is `SURVEIL_DATA_INCOMPLETE`. No run writes the export yet.

## 1.2.0 - 18 Nov 2026

Correct equities surveillance to require symbol, side, time and quantity agreement for wash
matches, use the America/New_York close, and treat empty input as data incomplete. Mark the CFTC
Part 45 compatibility output not validated. Migrate pre-upgrade DSOR tombstones without sorting
UUIDs as age, and record the temporary development-audit expiry in SECURITY.md.

## 1.1.0 - 18 Nov 2026

Retire the CAT label that returned `READY` without validation. The compatibility method now
returns `NOT_VALIDATED`, is marked deprecated and names L.C. as validator owner. Add equities
wash-trade and marking-the-close screening over order and fill facts using the existing
surveillance disposition ladder; missing beneficial-owner data is `SURVEIL_DATA_INCOMPLETE`.
Add an advisory-only AML case narrative draft that cannot carry a decision.

## 1.0.1 - 18 Nov 2026

Keep legacy Decision System of Record identifiers in a cap-bounded tombstone list when their
records are trimmed. Legacy identifiers no longer inflate the sequence watermark, so an unrelated
identifier still reports that it was never stored.

## 1.0.0 - 17 Nov 2026

Close the declared-synthetic retail minimum viable product from MVP-0 through MVP-5B. Decision
System of Record replay metadata now uses a bounded sequence watermark while preserving exact
trimmed-record and never-stored errors at the replay cap.

On 18 November 2026, Bill decided that the required npm vulnerability gate covers production
dependencies (`npm audit --omit=dev --audit-level=high`). The full audit remains visible as a
separate non-blocking job and reports GHSA-fc5q-39xc-vjpf in picomatch, reached as a development
dependency through Vite; the advisory had no patched version on the decision date.

## 0.8.5 - 9 Nov 2026

Preserve original DSOR operation identifiers outside the capped display log so duplicate
operations remain refused after eviction and restart.

## 0.8.4 - 7 Nov 2026

Persist Decision System of Record replay metadata and reconcile merge authority.

## 0.8.3 - 7 Nov 2026

Apply Ruff safe fixes and add per-file Ruff and strict mypy quality ratchets.

## 0.8.2 - 7 Nov 2026

Allow builders to enable check-gated auto-merge while preserving Bill's sole release authority.

## 0.8.1 - 7 Nov 2026

Clarify merge authority and use the established Decision System of Record expansion in the
settlement dashboard.

## 0.8.0 - 7 Nov 2026

Port ONB-1 regulatory alignment and add shared DSOR decision metadata with append-only migration
provenance. Pin the ONB-1 Atreides and kernel branches pending Bill's release tags.
