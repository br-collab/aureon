# Cato Demo Package

This folder is a self-contained snapshot of the Cato v0.2.2 tokenized-settlement doctrine gate for independent review. Everything a model validator, research reviewer, or frontier-LLM second opinion needs to evaluate the gate is in this folder.

---

## 🔗 Live application

The Cato doctrine gate is running in production inside Aureon's Atrox tab:

- **Live dashboard (public):** https://aureon-production.up.railway.app
  (Scroll down on the **Atrox** tab until you see the **"Cato — Verana L0 Settlement Gate"** card. The gate decision, recommended rail, recommended chain, live inputs, multi-chain gas row, and live ETH/SOL prices from CoinGecko all refresh every 15 seconds.)
- **Custom domain alternative:** https://grid.mentatrobotics.com (same service)
- **Live API root:** https://aureon-production.up.railway.app/api/cato/gate (returns the current PROCEED / HOLD / ESCALATE decision as JSON — try it in a browser)

Source repos:

- **Cato MCP server (external):** https://github.com/br-collab/Cato---FICC-MCP
- **Aureon (internal integration):** https://github.com/br-collab/aureon

---

## 📁 What's in this folder

| File | Purpose | Source |
|---|---|---|
| [`index.js`](index.js) | **Cato MCP server** (Node.js) — canonical external implementation, 23 MCP tools including `cato_gate`, `get_atomic_settlement_gate`, `compare_settlement_rails`, `get_multichain_gas`, `get_onchain_prices` | `cato-mcp/index.js` |
| [`cato_client.py`](cato_client.py) | **Python in-process twin** — deterministically identical doctrine logic, called directly from Aureon's Flask server for `/api/cato/*` endpoints | `aureon/mcp/cato_client.py` |
| [`cato_backtest.py`](cato_backtest.py) | **Historical backtest** — replays the Cato v0.2.2 doctrine against March 2020 COVID, September 2019 repo spike, and March 2023 SVB using daily FRED SOFR + weekly STLFSI4 | `scripts/cato_backtest.py` |
| [`cato_backtest_results.md`](cato_backtest_results.md) | **Backtest results** — regenerated against v0.2.2 doctrine. Summary + per-event deep dives + documented calibration limitations | `scripts/cato_backtest_results.md` |
| [`DOCTRINE.md`](DOCTRINE.md) | **Full doctrine spec** — thresholds, routing logic, data flow, supported rails, governance invariants, parity principle | Extracted from `CLAUDE.md` lines 99–188 |
| [`REVIEW_PROMPT.md`](REVIEW_PROMPT.md) | **Adversarial review prompt** ready to paste into a frontier LLM for independent critique | Purpose-built for this review |

---

## 🧪 How the pieces fit together

```
                                    Claude Desktop / Agent SDK / any LLM
                                                   │
                                                   │ JSON-RPC stdio
                                                   ▼
                             ┌─────────────────────────────────────────┐
                             │   Cato MCP server (cato-mcp/index.js)   │
                             │   23 tools, v0.2.2                       │
                             │   External callers                       │
                             └──────────────────┬──────────────────────┘
                                                │
                                                │  doctrine parity
                                                │  (bit-for-bit identical
                                                │   decisions for identical
                                                │   inputs)
                                                │
                             ┌──────────────────▼──────────────────────┐
                             │ Aureon Python twin                       │
                             │ (aureon/mcp/cato_client.py)              │
                             │ Pure doctrine, no I/O                    │
                             └──────────────────┬──────────────────────┘
                                                │
                                                │  called by server.py
                                                │  every 60s refresh cycle
                                                ▼
                             ┌─────────────────────────────────────────┐
                             │  /api/cato/gate                          │
                             │  /api/cato/compare-rails                 │
                             │  /api/cato/multichain-gas                │
                             │  /api/cato/settlement-context            │
                             │  /api/cato/prices                        │
                             │  → Aureon dashboard tile                 │
                             └─────────────────────────────────────────┘

Data sources (all free, no auth):
  - FRED        : SOFR, STLFSI4
  - Blockscout  : ETH / Base / Arbitrum gas, block time, network utilization
  - Solana RPC  : priority fees via getRecentPrioritizationFees
  - CoinGecko   : live ETH / SOL USD prices
```

---

## 📌 Key claims to evaluate

A reviewer should evaluate Cato v0.2.2 on the following claims:

1. **Deterministic parity.** The Node.js MCP server and the Python in-process twin must produce identical decisions for identical inputs. If a reviewer can find a case where they diverge, that's a real finding and a governance violation.

2. **Backtest results are honest.** On v0.2.2, the doctrine correctly flags 100% of the March 2020 COVID repo freeze, 80% of the September 2019 overnight repo spike (4 of 5 expected-window days), and 45% of March 2023 SVB. The SVB result is *documented as a calibration limitation*, not claimed as a catch.

3. **The doctrine is narrow by design.** Cato covers funding-market stress (SOFR delta), broad financial stress (OFR STLFSI4), and on-chain congestion (ETH gas). It explicitly does NOT cover slow-moving credit events (HY OAS widening, bank equity performance, VIX regime shifts). The trade-off: fewer false positives at the cost of missing slow credit events. A reviewer should challenge whether this trade-off is the right one for institutional repo.

4. **Live market data flows through both sides.** The `price_sources` block in every tool output shows whether CoinGecko served the live price or the fallback was used. The `cache_age_seconds` field on every endpoint shows how fresh the data is. There is no hidden statefulness.

5. **Thresholds are static.** v0.2.2 uses hardcoded thresholds (1.0 OFR escalate, 0.5 OFR hold, 50 gwei gas, 10 bps SOFR delta). Each is calibrated against a published reference or a visible regime boundary. A v0.3.0 revision may move to dynamic rolling-σ thresholds after institutional input. Reviewers should say whether the static calibration is defensible or whether a dynamic approach is mandatory for pilot deployment.

6. **Reference implementation of Duffie 2025 PORTS.** The architecture is intended as a working reference implementation of the governance layer Duffie proposes in *"The Case for PORTS"* (Brookings 2025). Reviewers familiar with the paper should flag any way in which Cato's design deviates from or contradicts the paper's thesis.

---

## 🔍 How to run the backtest yourself

```bash
# From this demo folder (adjust import path in cato_backtest.py if needed,
# or run from the full aureon repo as documented in cato_backtest.py's docstring)

FRED_API_KEY=your_free_fred_key python3 cato_backtest.py
```

Free FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html

The backtest will fetch SOFR daily + STLFSI4 weekly for three event windows, replay the Cato `atomic_settlement_gate` function day-by-day, and regenerate `cato_backtest_results.md` with the current results. Deterministic and reproducible.

---

## 🎯 Use this folder for

1. **Adversarial LLM review** — paste [`REVIEW_PROMPT.md`](REVIEW_PROMPT.md) into a frontier model (GPT-5, Gemini 2.5 Pro, Claude Opus 4.6, etc.) along with the 5 code/data files. See `REVIEW_PROMPT.md` for the full prompt and signal-vs-noise guidance.
2. **Institutional model-validation review** — the backtest methodology + results + doctrine spec constitute an SR 11-7 Tier 1 validation artifact.
3. **Academic / policy review** — a reviewer familiar with Duffie 2025 or related BIS / OFR / Fed policy work can evaluate whether Cato is a faithful implementation of the PORTS thesis.
4. **Pilot deployment preparation** — everything a tier-1 bank's innovation team needs to understand what Cato does, what it doesn't do, and what the next version would add.

---

## 📜 License and provenance

- Cato MCP server: MIT license (see `index.js` header and `package.json` in the source repo)
- Aureon / Cato Python twin: project-internal (see CLAUDE.md in the source repo)
- Reference: Duffie (2025), *"The Case for PORTS: Perpetual Overnight Rate Treasury Securities"*, Brookings Institution
- Built by: Ravelo Strategic Solutions LLC · Columbia University MS Technology Management
- Doctrine version at snapshot: **v0.2.2**
