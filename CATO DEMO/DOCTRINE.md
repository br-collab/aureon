# Cato — Verana L0 Tokenized Settlement Doctrine Gate

**Status:** v0.2.2 — paper trading, approaching institutional-testing readiness.
**Reference:** Duffie (2025) *"The Case for PORTS"* — Brookings Institution.

Cato is the Verana L0 pre-settlement doctrine gate. It takes live SOFR (FRED), OFR financial stress (FRED STLFSI4), multi-chain gas/fee state (Blockscout + Solana RPC), and live ETH/SOL prices (CoinGecko), and emits a deterministic `PROCEED / HOLD / ESCALATE` decision plus a `recommended_chain` for tokenized repo settlement.

## Dual implementation — keep them deterministically identical

Cato exists in **two forms** that must produce bit-for-bit identical decisions:

1. **External MCP server** — https://github.com/br-collab/Cato---FICC-MCP
   Node.js, 23 tools, `@modelcontextprotocol/sdk ^1.0.0`. Exposes Cato to LLM callers (Claude Desktop, Agent SDK apps) over JSON-RPC stdio. GitHub Actions CI asserts exactly 23 tools on every push.

2. **Aureon in-process Python twin** — `aureon/mcp/cato_client.py`
   Pure Python, no I/O. Called directly from `server.py` for the `/api/cato/*` endpoints. Data fetching (FRED, Blockscout, Solana RPC, CoinGecko) happens in `server.py` inside `_cato_refresh_inputs()` and flows into the twin via scalar parameters.

**The parity principle (hard rule):** any doctrine change — new threshold, new input, new decision branch — must land in **both** codebases in the same commit series. The deterministic identity is what lets regulators trust the gate regardless of caller. If you only update one side you break SR 11-7 model governance.

## Doctrine thresholds (v0.2.2)

| Input | Threshold | Effect |
|---|---|---|
| OFR STLFSI4 | `> 1.0` | **ESCALATE** — systemic stress, route to human authority |
| OFR STLFSI4 | `> 0.5` | **HOLD** — non-systemic broad stress, route to FICC traditional |
| ETH gas | `> 50 gwei` | **HOLD** — L1 congestion, route to FICC traditional |
| \|SOFR(t) − SOFR(t−1)\| × 100 | `> 10 bps` | **HOLD** — funding-market shock (v0.2.2, Sept 2019 backtest fix) |
| everything below | — | **PROCEED** — atomic settlement viable |

Chain selection (trade-size-agnostic) picks cheapest live rail:
1. Solana if fee < $0.01
2. Base if gas < 1 gwei
3. Ethereum L1 otherwise

Rail routing (notional-aware, in `compare_settlement_rails`):
1. If OFR > 0.5 → FICC (stress override, absolute)
2. If |SOFR delta| > 10 bps → FICC (funding-market override, v0.2.2)
3. If notional > $10M and ETH gas < 30 → Ethereum L1 (large notional wants L1 depth)
4. If Solana fee < $0.01 → Solana
5. If Base gas < 1 gwei → Base
6. If ETH gas > 50 → FICC (gas spike fallback)
7. Otherwise → Ethereum L1

## Live market data flow (every 60 seconds)

Inside `_cato_refresh_inputs()` in `server.py`:
1. Fetch SOFR from FRED with 2 observations (today + prior day — required for the v0.2.2 delta check)
2. Read OFR STLFSI4 from the existing `_ofr_cache` (warmed by `market_loop`)
3. Fetch live ETH/SOL USD prices from CoinGecko public API
4. Build `chain_state` dict by fetching gas from Blockscout (eth/base/arbitrum) + Solana RPC `getRecentPrioritizationFees`, using the live SOL price for Solana's fee USD conversion
5. Write `sofr_rate`, `sofr_prev`, `ofr_stress`, `chain_state`, `prices` into `_cato_input_cache` atomically

All `/api/cato/*` handlers read from `_cato_input_cache` and never make a network call in the request path.

## Supported rails

| Rail | Speed | Cost at normal state | Status |
|---|---|---|---|
| FICC traditional | T+1 | ~0.5 bps + SOFR cost-of-capital (SOFR 3.6% × notional × 1/360) | Live |
| Ethereum L1 | ~12s | ~$0.08 / settlement at 0.5 gwei, $2,300 ETH | Live |
| Base (Ethereum L2) | ~2s | ~$0.001 / settlement at 0.01 gwei | Live |
| Arbitrum (Ethereum L2) | ~2s | ~$0.1 / settlement at 0.6 gwei | Live |
| Solana | ~400ms | ~$0.0004 / settlement at 5000 lamports, $84 SOL | Live |
| Fed L1 / PORTS | Instant | TBD | **Pending — GENIUS Act** |

## Historical backtest — SR 11-7 Tier 1 validation artifact

`cato_backtest.py` replays Cato against March 2020 COVID, September 2019 repo spike, and March 2023 SVB. Results in `cato_backtest_results.md`:

| Event | v0.2.1 (before fix) | v0.2.2 (current) | Peak OFR | Peak SOFR Δ | Verdict |
|---|---|---|---|---|---|
| March 2020 COVID | 100% (20/20) | **100% (20/20)** | 5.657 | 84 bps | ✅ caught |
| September 2019 repo spike | 0% (0/5) | **80% (4/5)** | -0.155 | 282 bps | ✅ caught after v0.2.2 fix |
| March 2023 SVB | 45.5% (5/11) | 45.5% (5/11) | 1.097 | 25 bps | ⚠️ calibration limit |

**v0.2.2 closed the September 2019 gap** by restoring the SOFR 1-day delta trigger that was silently dropped in the v0.2.0 refactor. Peak SOFR 1-day move was 282 bps (crisis-level) while OFR FSI was *negative* during the event — a pure funding-market liquidity crunch that broad financial-stress indices don't capture. Cato now flags these in real time.

**March 2023 SVB is a documented calibration limitation**, not a bug. Peak OFR STLFSI4 was 1.097 (only barely above the 1.0 ESCALATE threshold, and only for one day). Peak SOFR delta was 25 bps (only exceeded the 10 bps threshold on one day, which was already tripping ESCALATE on OFR). SVB was a slow-moving regional-banking credit event that didn't produce the signal shapes Cato v0.2.2 watches for. To catch events of this class would require additional doctrine inputs (HY OAS delta, VIX percentile, or bank equity performance) — explicitly deferred to avoid over-calibrating to slow-moving credit moves. Documented in `cato_backtest_results.md`.

Run the backtest with:

```bash
FRED_API_KEY=<key> python3 cato_backtest.py
```

(In the production repo the script lives at `scripts/cato_backtest.py` and imports `aureon.mcp.cato_client`. The copy in this demo folder is the same file; to run it standalone, either copy `cato_client.py` into the same directory or adjust the import path.)

## Invariants

- External MCP server and in-process Python twin must stay at the same doctrine version and produce identical decisions for identical inputs.
- The gate is **advisory only** — it emits a decision, it does not execute. Operator authority (CAOM-001) still gates every trade.
- `fed_l1` slot is always present in `chain_state` as a documented placeholder. Never remove it. When PORTS ships, the chain_state shape stays the same; only the `status` field flips from `not_yet_issued` to `live`.
- Live prices are fetched on a 60s background cadence. Request path never hits CoinGecko, FRED, Blockscout, or Solana RPC directly. Any endpoint that makes a network call in the request handler is a bug.
- All four thresholds (OFR escalate, OFR hold, gas hold, SOFR delta hold) are static constants in v0.2.2. A v0.3.0 revision may introduce rolling-σ or percentile-based dynamic thresholds; the current static numbers are calibrated against published reference points (1σ OFR, 3σ SOFR normal-day volatility, Ethereum gas regime boundary).
