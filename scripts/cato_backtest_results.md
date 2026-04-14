# Cato Historical Backtest — v0.2.1

_Generated: 2026-04-14T22:27:32.291862+00:00_

## Methodology

Replays the Cato `atomic_settlement_gate` doctrine against three historical market stress events. For each trading day in each event window, we pull daily SOFR and the weekly OFR-style financial stress index (STLFSI4) from FRED and call the gate with those scalars + an empty chain_state. Historical Ethereum gas data is not available from the free Blockscout API, so the gas threshold check never fires during this backtest. The OFR and SOFR surfaces are the tested doctrine logic.

### Data sources

- **SOFR** — FRED series `SOFR`, daily observations
- **OFR Financial Stress Index** — FRED series `STLFSI4`, weekly (forward-filled to daily)
- **ETH gas** — not available historically; gas threshold excluded from backtest

### Cato doctrine under test (v0.2.1)

- **ESCALATE** if OFR stress index > 1.0
- **HOLD** if OFR stress index > 0.5
- **HOLD** if ETH gas > 50.0 gwei _(not tested; historical gas unavailable)_
- **PROCEED** otherwise

## Summary

| Event | Days in window | PROCEED | HOLD | ESCALATE | In-window accuracy |
|---|---|---|---|---|---|
| March 2020 — COVID repo freeze | 62 | 18 | 5 | 39 | 20/20 (100.0%) |
| September 2019 — overnight repo spike | 64 | 64 | 0 | 0 | 0/5 (0.0%) |
| March 2023 — SVB collapse | 61 | 56 | 0 | 5 | 5/11 (45.5%) |

- **March 2020 — COVID repo freeze** — ✅ doctrine correctly flagged stress (100% of window)
- **September 2019 — overnight repo spike** — ❌ doctrine MISSED the event (0% of window)
- **March 2023 — SVB collapse** — ❌ doctrine MISSED the event (45% of window)

## March 2020 — COVID repo freeze

- **Window:** 2020-02-03 → 2020-04-30
- **Expected stress window:** 2020-03-13 → 2020-04-10

**Historical context.** COVID market panic. Treasury repo markets froze mid-March as dealers hoarded cash. Fed launched a $1.5T repo facility on March 12 and expanded QE on March 15. OFR STLFSI4 spiked from ~-0.8 in late February to a peak of ~+5.5 on March 27, 2020. Every institutional model validator tests against this event.

**Decisions:** PROCEED=18, HOLD=5, ESCALATE=39

**Peak in-window metrics:**
- OFR STLFSI4 peak: `5.657`
- SOFR range: `0.01%` → `1.1%`
- Peak SOFR 1-day move: `84.0 bps`

**In-window accuracy:** 20/20 = 100.0%

**Notable days:**

| Date | SOFR % | SOFR Δ bps | OFR FSI | Decision |
|---|---|---|---|---|
| 2020-03-13 | 1.10 | 10.0 | 3.497 | **ESCALATE** |
| 2020-03-20 | 0.04 | 2.0 | 5.657 | **ESCALATE** |
| 2020-03-16 | 0.26 | 84.0 | 3.497 | **ESCALATE** |
| 2020-04-09 | 0.01 | 0.0 | 3.158 | **ESCALATE** |

## September 2019 — overnight repo spike

- **Window:** 2019-08-01 → 2019-10-31
- **Expected stress window:** 2019-09-16 → 2019-09-20

**Historical context.** Overnight SOFR spiked from ~2.2% to 5.25% on September 17, 2019 after tax-day cash outflows collided with Treasury coupon settlements. The Fed launched its first post-crisis standing repo operations on September 17. CRITICAL: the OFR STLFSI4 did NOT spike during this event — it was a pure funding-market liquidity crunch, not a broad financial stress event. This is the test case that exposes whether Cato's doctrine catches funding-market-only stress (SOFR 1-day delta) or only broad stress (OFR).

**Decisions:** PROCEED=64, HOLD=0, ESCALATE=0

**Peak in-window metrics:**
- OFR STLFSI4 peak: `-0.1555`
- SOFR range: `1.86%` → `5.25%`
- Peak SOFR 1-day move: `282.0 bps`

**In-window accuracy:** 0/5 = 0.0%

**Notable days:**

| Date | SOFR % | SOFR Δ bps | OFR FSI | Decision |
|---|---|---|---|---|
| 2019-09-16 | 2.43 | 23.0 | -0.350 | **PROCEED** |
| 2019-09-20 | 1.86 | 9.0 | -0.155 | **PROCEED** |
| 2019-09-17 | 5.25 | 282.0 | -0.350 | **PROCEED** |

## March 2023 — SVB collapse

- **Window:** 2023-02-01 → 2023-04-30
- **Expected stress window:** 2023-03-10 → 2023-03-24

**Historical context.** Silicon Valley Bank failed March 10, 2023. Signature Bank followed March 12. FDIC announced systemic-risk exception March 12. First Republic received $30B deposit from 11 banks on March 16. STLFSI4 rose but less dramatically than March 2020 — this is a regional-banking-stress event that tests threshold calibration at the HOLD / PROCEED boundary.

**Decisions:** PROCEED=56, HOLD=0, ESCALATE=5

**Peak in-window metrics:**
- OFR STLFSI4 peak: `1.0965`
- SOFR range: `4.55%` → `4.8%`
- Peak SOFR 1-day move: `25.0 bps`

**In-window accuracy:** 5/11 = 45.5%

**Notable days:**

| Date | SOFR % | SOFR Δ bps | OFR FSI | Decision |
|---|---|---|---|---|
| 2023-03-10 | 4.55 | 0.0 | -0.091 | **PROCEED** |
| 2023-03-17 | 4.55 | 2.0 | 1.097 | **ESCALATE** |
| 2023-03-23 | 4.80 | 25.0 | 1.097 | **ESCALATE** |
| 2023-03-24 | 4.80 | 0.0 | 0.266 | **PROCEED** |

## Doctrine gaps found

### GAP: SOFR 1-day delta is not a HOLD trigger

During the September 2019 repo spike, peak SOFR 1-day move was **282.0 bps** (a crisis-level shock) but peak OFR STLFSI4 only reached **-0.155** — well below the 0.5 HOLD threshold. Result: Cato classified the entire Sept 2019 event as PROCEED, which is **wrong**. Pure funding-market liquidity crunches don't show up in broad financial stress indices.

**Recommended fix:** restore the v0.1.0-era SOFR delta check. Add `CATO_SOFR_DELTA_HOLD_BPS = 10.0` to the doctrine and promote any day with `|SOFR_today - SOFR_prev| × 100 > 10` to HOLD. This requires the caller to supply `sofr_prev` to `atomic_settlement_gate` (a two-field expansion of the cache and the Python twin signature).


### GAP: September 2019 — overnight repo spike — in-window accuracy 0.0%
Cato failed to flag this event as HOLD or ESCALATE on 5 of 5 days in the expected stress window.


### GAP: March 2023 — SVB collapse — in-window accuracy 45.5%
Cato failed to flag this event as HOLD or ESCALATE on 6 of 11 days in the expected stress window.


---

This backtest is a model validation exercise, not a strategy simulation. It answers the narrow question: *does the current Cato doctrine correctly flag known historical stress events?* That is the exact question institutional model validators (SR 11-7 Tier 1) will ask during review. Any gap identified above should be closed before institutional pilot deployment.

_Reference: Duffie (2025), "The Case for PORTS", Brookings Institution._
