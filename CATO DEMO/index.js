#!/usr/bin/env node
/**
 * Cato MCP Server — v0.2.2
 * Absolute doctrine for tokenized settlement governance.
 * Multi-chain settlement router with live CoinGecko price feeds.
 * v0.2.2 restores the SOFR 1-day delta check (funding-market shock
 * detector) that was dropped in the v0.2.0 refactor — closes the
 * September 2019 repo spike gap identified by cato_backtest.py.
 *
 * Named after Marcus Porcius Cato — Roman senator and institutional
 * conscience of the Republic. Cato is the Verana L0 data layer for
 * Project Aureon's tokenized settlement doctrine.
 *
 * Data sources (all free, no auth required):
 *   - NY Fed:        SOFR, BGCR, TGCR, EFFR, repo reference rates
 *   - FRED:          Treasury yields, fed funds, repo rates, macro regime
 *   - TreasuryDirect: Auction results, yield curves
 *   - OFR:           Financial stress index, systemic risk indicators
 *   - SEC EDGAR:     13F filings, institutional positioning
 *   - Blockscout:    On-chain network state (ETH, Base, Arbitrum)
 *   - Solana RPC:    Priority fees, settlement speed
 *   - CoinGecko:     Live ETH and SOL USD prices (v0.2.1)
 *
 * Reference: Duffie (2025) "The Case for PORTS" — Brookings Institution.
 */

const { Server } = require("@modelcontextprotocol/sdk/server/index.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { CallToolRequestSchema, ListToolsRequestSchema } = require("@modelcontextprotocol/sdk/types.js");
const axios = require("axios");

const FRED_BASE = "https://api.stlouisfed.org/fred";
const NYFED_BASE = "https://markets.newyorkfed.org/api";
const TREASURY_BASE = "https://api.fiscaldata.treasury.gov/services/api/v1";
const EDGAR_BASE = "https://data.sec.gov";

// ── Multi-chain settlement rails (Blockscout + Solana RPC) ───────────────────
// Each entry is a free public endpoint. Solana is different protocol so it
// has its own JSON-RPC helper below. "fed_l1" is a documented placeholder —
// not live. The architecture accommodates tokenized Fed reserves when they
// arrive (see GENIUS Act, Duffie 2025 PORTS proposal).
const BLOCKSCOUT_CHAINS = {
  ethereum: "https://eth.blockscout.com/api/v2/stats",
  base:     "https://base.blockscout.com/api/v2/stats",
  arbitrum: "https://arbitrum.blockscout.com/api/v2/stats",
};
const SOLANA_RPC = "https://api.mainnet-beta.solana.com";

// Price fallback values — used only when the CoinGecko public API is
// unreachable. v0.2.1 replaces the v0.2.0 static proxies with live
// CoinGecko prices via getLivePrices() below. The fallback constants
// are retained so Cato still produces a meaningful cost estimate when
// CoinGecko is rate-limited or offline, and so the fallback path is
// observable in the output (price_sources.fallback_used = true).
const ETH_PRICE_FALLBACK = 3500;   // USD per ETH — CoinGecko fallback
const SOL_PRICE_FALLBACK = 150;    // USD per SOL — CoinGecko fallback

// Doctrine thresholds — mirror aureon/mcp/cato_client.py exactly. The
// parity principle (hard rule) says these must be identical across the
// MCP server and the Python twin so the gate produces the same decision
// regardless of caller. v0.2.2 restores the SOFR delta trigger that was
// in the v0.1.0 spec but silently dropped during the v0.2.0 refactor.
const CATO_OFR_ESCALATE_THRESHOLD = 1.0;
const CATO_OFR_HOLD_THRESHOLD = 0.5;
const CATO_GAS_GWEI_HOLD_THRESHOLD = 50.0;
const CATO_SOFR_DELTA_HOLD_BPS = 10.0;   // funding-market shock detector

// Speed properties (informational, used by get_multichain_gas and
// compare_settlement_rails output). Block times are rough medians.
const CHAIN_SPEED = {
  ethereum: "12s",
  base:     "2s",
  arbitrum: "2s",
  solana:   "400ms",
};

const FRED_KEY = process.env.FRED_API_KEY || ""; // Free key from fred.stlouisfed.org

async function get(url, params = {}) {
  try {
    const res = await axios.get(url, { params, timeout: 10000,
      headers: { "User-Agent": "Cato-MCP-Server/0.2.2 (open-source; Project Aureon; contact: github)" }
    });
    return res.data;
  } catch (e) {
    return { error: e.message, url };
  }
}

// ── CoinGecko live prices (v0.2.1) ───────────────────────────────────────────
// Fetches live ETH and SOL USD prices from the free CoinGecko public API.
// No auth required. Returns {eth, sol, source, timestamp, fallback_used}.
// If CoinGecko is unreachable or rate-limited, returns the static fallback
// constants with fallback_used=true so the caller can surface the degraded
// state. Doctrine note: for institutional deployment, replace with a
// licensed price feed (Bloomberg BVAL, Refinitiv, Chainlink Price Feeds).
async function getLivePrices() {
  try {
    const res = await get(
      "https://api.coingecko.com/api/v3/simple/price",
      { ids: "ethereum,solana", vs_currencies: "usd" }
    );
    const ethUsd = res?.ethereum?.usd;
    const solUsd = res?.solana?.usd;
    const fallbackUsed = !ethUsd || !solUsd;
    return {
      eth: ethUsd || ETH_PRICE_FALLBACK,
      sol: solUsd || SOL_PRICE_FALLBACK,
      source: fallbackUsed ? "coingecko_partial_fallback" : "coingecko_public",
      timestamp: new Date().toISOString(),
      fallback_used: fallbackUsed,
      note: "Live prices via CoinGecko public API. For institutional deployment use a licensed price feed (Bloomberg BVAL, Refinitiv, Chainlink Price Feeds).",
    };
  } catch (e) {
    return {
      eth: ETH_PRICE_FALLBACK,
      sol: SOL_PRICE_FALLBACK,
      source: "static_fallback",
      timestamp: new Date().toISOString(),
      fallback_used: true,
      error: e.message,
      note: "CoinGecko unreachable. Using Cato static fallback prices.",
    };
  }
}

// ── FRED helper ──────────────────────────────────────────────────────────────
async function fredSeries(seriesId, limit = 10) {
  const params = { series_id: seriesId, sort_order: "desc", limit, file_type: "json" };
  if (FRED_KEY) params.api_key = FRED_KEY;
  const data = await get(`${FRED_BASE}/series/observations`, params);
  if (data.error) return data;
  return {
    series: seriesId,
    observations: (data.observations || []).map(o => ({ date: o.date, value: o.value }))
  };
}

// ── Blockscout helpers (per-chain) ───────────────────────────────────────────
// blockscoutStatsFor(chainKey) fetches the /api/v2/stats endpoint for any
// chain registered in BLOCKSCOUT_CHAINS and returns a uniform shape.
// Returns nulls on failure so the caller can surface "unavailable" cleanly.
async function blockscoutStatsFor(chainKey) {
  const url = BLOCKSCOUT_CHAINS[chainKey];
  if (!url) {
    return { gas_gwei: null, coin_price_usd: null, error: `no Blockscout endpoint for chain ${chainKey}` };
  }
  const data = await get(url);
  if (data.error) {
    return { gas_gwei: null, coin_price_usd: null, error: data.error };
  }
  const gasAvg = data?.gas_prices?.average;
  const coinPrice = parseFloat(data?.coin_price || "0");
  return {
    gas_gwei: gasAvg !== undefined ? parseFloat(gasAvg) : null,
    block_time_seconds: data?.average_block_time !== undefined
      ? parseFloat(data.average_block_time) / 1000
      : null,
    network_utilization_pct: data?.network_utilization_percentage !== undefined
      ? parseFloat(data.network_utilization_percentage)
      : null,
    coin_price_usd: coinPrice || null
  };
}

// v0.1.0 backwards-compatible alias — existing tools call blockscoutStats()
// and expect Ethereum mainnet data.
async function blockscoutStats() {
  return blockscoutStatsFor("ethereum");
}

// ── Solana helper ────────────────────────────────────────────────────────────
// Uses getRecentPrioritizationFees JSON-RPC to estimate the median priority
// fee. Solana base fee is a fixed 5000 lamports per signature. Total fee
// ≈ base (5000) + median prioritization (variable). Takes a solPrice USD
// so it can compute a live fee_usd on top of the raw lamports.
async function solanaStats(solPrice) {
  const priceUsd = solPrice || SOL_PRICE_FALLBACK;
  try {
    const res = await axios.post(
      SOLANA_RPC,
      { jsonrpc: "2.0", id: 1, method: "getRecentPrioritizationFees", params: [] },
      { timeout: 5000, headers: { "Content-Type": "application/json",
          "User-Agent": "Cato-MCP-Server/0.2.1 (open-source; Project Aureon)" } }
    );
    const fees = res.data?.result || [];
    const priorityMedian = fees.length > 0
      ? fees.map(f => f.prioritizationFee || 0).sort((a, b) => a - b)[Math.floor(fees.length / 2)]
      : 0;
    const base = 5000;
    const totalLamports = base + priorityMedian;
    return {
      base_fee_lamports: base,
      priority_fee_lamports: priorityMedian,
      total_fee_lamports: totalLamports,
      total_fee_sol: totalLamports * 1e-9,
      total_fee_usd: totalLamports * 1e-9 * priceUsd,
    };
  } catch (e) {
    // Fail safe — assume base fee only so Solana still shows a cost estimate.
    return {
      base_fee_lamports: 5000,
      priority_fee_lamports: 0,
      total_fee_lamports: 5000,
      total_fee_sol: 5000 * 1e-9,
      total_fee_usd: 5000 * 1e-9 * priceUsd,
      error: e.message,
    };
  }
}

// ── Multi-chain orchestrator ─────────────────────────────────────────────────
// Fetches gas/fee state across every supported rail in parallel. Each fetch
// is isolated so one slow/broken chain can never block the others. Takes a
// prices object ({eth, sol}) so Solana's fee_usd_estimate uses the live
// CoinGecko value. Returns a uniform shape per chain plus the documented
// fed_l1 placeholder.
async function multichainGas(prices) {
  const resolvedPrices = prices || { eth: ETH_PRICE_FALLBACK, sol: SOL_PRICE_FALLBACK };
  const [eth, base, arb, sol] = await Promise.all([
    blockscoutStatsFor("ethereum"),
    blockscoutStatsFor("base"),
    blockscoutStatsFor("arbitrum"),
    solanaStats(resolvedPrices.sol),
  ]);

  const chainBlock = (key, stats) => {
    if (!stats || stats.gas_gwei === null || stats.gas_gwei === undefined) {
      return {
        gas_gwei: null,
        settlement_speed: CHAIN_SPEED[key],
        status: "unavailable",
        error: stats?.error || "no data",
      };
    }
    return {
      gas_gwei: stats.gas_gwei,
      settlement_speed: CHAIN_SPEED[key],
      status: "live",
      coin_price_usd: stats.coin_price_usd,
    };
  };

  return {
    ethereum: chainBlock("ethereum", eth),
    base:     chainBlock("base", base),
    arbitrum: chainBlock("arbitrum", arb),
    solana: {
      fee_lamports:     sol.total_fee_lamports,
      fee_usd_estimate: +sol.total_fee_usd.toFixed(6),
      base_fee_lamports: sol.base_fee_lamports,
      priority_fee_lamports: sol.priority_fee_lamports,
      settlement_speed: CHAIN_SPEED.solana,
      status: sol.error ? "placeholder" : "live",
      note: `Solana 400ms finality. Base fee 5000 lamports + median prioritization. Live SOL price: $${resolvedPrices.sol.toFixed(2)}.`,
    },
    fed_l1: {
      status: "not_yet_issued",
      note: "PORTS — Duffie 2025. Tokenized Fed reserves pending. Monitor GENIUS Act progress.",
    },
  };
}

// ── Rail cost helpers ────────────────────────────────────────────────────────
// Compute the all-in USD cost of a settlement on each rail. Returns null
// for rails without live data so the caller can exclude them from ranking.
// evmL1Cost and solanaCost take their respective live prices as params.
function ficcCost(notionalUsd, sofrPct, termDays) {
  // 0.5 bps clearing fee net of 40% netting benefit, annualized to term,
  // plus cost of capital at SOFR for the term.
  const clearing = notionalUsd * 0.00005 * 0.6 * (termDays / 360);
  const coc = notionalUsd * (sofrPct / 100) * (termDays / 360);
  return clearing + coc;
}
function evmL1Cost(gasGwei, ethPriceUsd) {
  if (gasGwei === null || gasGwei === undefined) return null;
  const price = ethPriceUsd || ETH_PRICE_FALLBACK;
  // 65000 gas units * gwei * 1e-9 (gwei→ETH) * live ETH price
  return gasGwei * 65000 * 1e-9 * price;
}
function solanaCost(feeLamports, solPriceUsd) {
  if (feeLamports === null || feeLamports === undefined) return null;
  const price = solPriceUsd || SOL_PRICE_FALLBACK;
  return feeLamports * 1e-9 * price;
}

// ── TOOL DEFINITIONS ─────────────────────────────────────────────────────────
const TOOLS = [

  // ── NY FED TOOLS ──────────────────────────────────────────────────────────
  {
    name: "get_sofr",
    description: "SOFR (Secured Overnight Financing Rate) — the benchmark rate replacing LIBOR, based on overnight Treasury repo transactions cleared through FICC. Critical for eFICC pricing, swap valuation, and repo book management.",
    inputSchema: { type: "object", properties: {
      days: { type: "number", description: "Number of days of history (default 10)", default: 10 }
    }}
  },
  {
    name: "get_repo_reference_rates",
    description: "NY Fed repo reference rates: SOFR, BGCR (Broad General Collateral Rate — tri-party repo), TGCR (Tri-party General Collateral Rate). Essential for repo desk pricing and collateral valuation.",
    inputSchema: { type: "object", properties: {
      rate_type: { type: "string", enum: ["sofr", "bgcr", "tgcr", "all"], description: "Rate type to retrieve", default: "all" }
    }}
  },
  {
    name: "get_effr",
    description: "EFFR (Effective Federal Funds Rate) — the actual overnight interbank lending rate set by the Fed. Core eFICC macro context for rate product positioning.",
    inputSchema: { type: "object", properties: {
      days: { type: "number", description: "Days of history", default: 10 }
    }}
  },
  {
    name: "get_repo_operations",
    description: "NY Fed open market repo and reverse repo operations — daily Fed intervention in repo market. Shows Fed liquidity posture. Critical context for repo clearing mandate compliance.",
    inputSchema: { type: "object", properties: {
      operation_type: { type: "string", enum: ["repo", "reverserepo", "all"], default: "all" },
      days: { type: "number", default: 5 }
    }}
  },

  // ── TREASURY YIELD CURVE TOOLS ────────────────────────────────────────────
  {
    name: "get_treasury_yield_curve",
    description: "US Treasury constant maturity yields — full curve from 1-month to 30-year. Foundation for all fixed income relative value analysis, duration risk, and swap pricing.",
    inputSchema: { type: "object", properties: {
      tenor: { type: "string", enum: ["1m","3m","6m","1y","2y","3y","5y","7y","10y","20y","30y","all"],
        description: "Specific tenor or 'all' for full curve", default: "all" },
      days: { type: "number", description: "Days of history", default: 5 }
    }}
  },
  {
    name: "get_tips_yields",
    description: "TIPS (Treasury Inflation-Protected Securities) real yields and breakeven inflation rates. Used for real rate analysis and inflation expectations in eFICC portfolios.",
    inputSchema: { type: "object", properties: {
      tenor: { type: "string", enum: ["5y","10y","20y","30y","all"], default: "all" },
      days: { type: "number", default: 10 }
    }}
  },
  {
    name: "get_treasury_auctions",
    description: "US Treasury auction results — bid-to-cover ratios, high yields, indirect bidder participation. Real-time signal for institutional demand in Treasury market.",
    inputSchema: { type: "object", properties: {
      security_type: { type: "string", enum: ["Bill","Note","Bond","CMB","TIPS","FRN","all"], default: "all" },
      limit: { type: "number", description: "Number of recent auctions", default: 10 }
    }}
  },
  {
    name: "get_yield_curve_spread",
    description: "Treasury yield curve spreads: 2y10y, 3m10y (recession indicator), 5y30y. Key eFICC regime indicators for rate product positioning.",
    inputSchema: { type: "object", properties: {
      spread: { type: "string", enum: ["2y10y","3m10y","5y30y","all"], default: "all" },
      days: { type: "number", default: 30 }
    }}
  },

  // ── MACRO REGIME TOOLS ────────────────────────────────────────────────────
  {
    name: "get_macro_regime_snapshot",
    description: "Full eFICC macro regime snapshot: fed funds rate, SOFR, 10y Treasury, 2y10y spread, CPI YoY, unemployment. Single call for Neptune Spear signal context.",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "get_cpi",
    description: "CPI (Consumer Price Index) — inflation data critical for TIPS valuation, real rate calculation, and Fed policy expectations in rate product trading.",
    inputSchema: { type: "object", properties: {
      series: { type: "string", enum: ["headline","core","all"], default: "all" },
      months: { type: "number", default: 12 }
    }}
  },
  {
    name: "get_fed_balance_sheet",
    description: "Federal Reserve balance sheet — total assets, Treasury holdings, MBS holdings, reserve balances. Critical for understanding quantitative tightening impact on eFICC supply/demand.",
    inputSchema: { type: "object", properties: {
      weeks: { type: "number", default: 12 }
    }}
  },

  // ── OFR / MONEY MARKETS ───────────────────────────────────────────────────
  {
    name: "get_ofr_stress_index",
    description: "OFR Financial Stress Index — composite measure of systemic stress across money markets, equity markets, funding markets. Verana L0 systemic stress overlay for doctrine gate decisions.",
    inputSchema: { type: "object", properties: {
      days: { type: "number", default: 30 }
    }}
  },
  {
    name: "get_money_market_rates",
    description: "Money market rates: commercial paper, banker acceptances, certificates of deposit. eFICC short-end context for repo pricing and MMF sweep optimization.",
    inputSchema: { type: "object", properties: {
      instrument: { type: "string", enum: ["cp_aa_nonfinancial","cp_aa_financial","cp_a2p2","all"], default: "all" },
      days: { type: "number", default: 10 }
    }}
  },

  // ── REPO MARKET TOOLS ─────────────────────────────────────────────────────
  {
    name: "get_repo_market_context",
    description: "Repo market context: overnight repo rate (SOFR), term SOFR rates (1m, 3m, 6m), reverse repo facility usage. Critical for repo clearing mandate compliance analysis.",
    inputSchema: { type: "object", properties: {
      include_term_sofr: { type: "boolean", default: true },
      days: { type: "number", default: 10 }
    }}
  },
  {
    name: "get_term_sofr",
    description: "CME Term SOFR reference rates (1-month, 3-month, 6-month, 12-month) via FRED. Forward-looking rates used in swap pricing and loan documentation post-LIBOR transition.",
    inputSchema: { type: "object", properties: {
      tenor: { type: "string", enum: ["1m","3m","6m","12m","all"], default: "all" },
      days: { type: "number", default: 10 }
    }}
  },

  // ── SEC EDGAR TOOLS ───────────────────────────────────────────────────────
  {
    name: "get_recent_13f_filers",
    description: "Recent 13F filings from SEC EDGAR — institutional positioning data. Fixed income and rates hedge fund positioning signal for Neptune Spear alpha origination.",
    inputSchema: { type: "object", properties: {
      days_back: { type: "number", description: "Days to look back for filings", default: 30 }
    }}
  },
  {
    name: "get_company_filings",
    description: "SEC EDGAR company filings — 10-K, 10-Q, 8-K for credit analysis. CIK lookup by company name for fundamental fixed income credit research.",
    inputSchema: { type: "object", properties: {
      cik: { type: "string", description: "SEC CIK number (10 digits)" },
      form_type: { type: "string", enum: ["10-K","10-Q","8-K","13F-HR","all"], default: "10-K" },
      limit: { type: "number", default: 5 }
    }, required: ["cik"] }
  },

  // ── TOKENIZED SETTLEMENT TOOLS (Cato doctrine layer) ──────────────────────
  {
    name: "get_onchain_prices",
    description: "Live ETH and SOL USD prices from the free CoinGecko public API (no auth). Returns {eth, sol, source, timestamp, fallback_used}. Used internally by compare_settlement_rails and get_atomic_settlement_gate for accurate rail cost math; exposed as a standalone tool so LLM callers can query current spot prices without triggering the full rail comparison. Institutional deployments should swap this for a licensed feed (Bloomberg BVAL, Refinitiv, Chainlink Price Feeds).",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "get_multichain_gas",
    description: "Fetch current gas/fee conditions across every supported settlement rail simultaneously: Ethereum mainnet, Base L2, Arbitrum L2, and Solana. Each chain is fetched in parallel and isolated so one slow upstream can never block the others. Includes a documented `fed_l1` placeholder for tokenized Fed reserves (pending GENIUS Act / Duffie 2025 PORTS proposal). Output shape: { ethereum, base, arbitrum, solana, fed_l1 }.",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "get_tokenized_settlement_context",
    description: "Real-time signal for whether atomic on-chain settlement is viable right now. Combines Blockscout ETH gas price with FRED SOFR and OFR financial stress index. Returns settlement_posture of 'favorable' (stress < 0.5 AND gas < 30), 'monitor' (stress 0.5-1.0 OR gas 30-50), or 'elevated' (stress > 1.0 OR gas > 50).",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "compare_settlement_rails",
    description: "Given a notional repo trade size in USD, estimate all-in cost on every supported settlement rail (FICC traditional, Ethereum L1, Base L2, Arbitrum L2, Solana) and return a ranked table cheapest-to-most-expensive plus a recommended rail. FICC rail: 0.5bps clearing fee net of 40% netting benefit, plus SOFR cost-of-capital for the term. EVM rails: gas_gwei × 65000 × 1e-9 × ETH_PRICE_PROXY. Solana: (base 5000 + median priority) lamports × SOL_PRICE_PROXY. Routing logic respects OFR stress (forces FICC) and gas spikes (forces FICC) before cheapest-cost selection.",
    inputSchema: { type: "object", properties: {
      notional_usd: { type: "number", description: "Notional trade size in USD" },
      term_days: { type: "number", description: "Settlement term in days (default 1 for overnight repo)", default: 1 }
    }, required: ["notional_usd"] }
  },
  {
    name: "get_atomic_settlement_gate",
    description: "Verana L0 multi-chain doctrine gate for tokenized settlement. Calls cato_gate for rates and stress, get_tokenized_settlement_context for on-chain posture, and get_multichain_gas for rail conditions across Ethereum, Base, Arbitrum, and Solana. Returns PROCEED / HOLD / ESCALATE plus a recommended_chain. ESCALATE if OFR stress > 1.0. HOLD if OFR stress > 0.5 OR Ethereum gas > 50 gwei. PROCEED otherwise. Includes a solana_note (400ms finality, 2022-2023 outage history, fallback doctrine) and a fed_l1_note (PORTS pending, GENIUS Act, CBDC).",
    inputSchema: { type: "object", properties: {} }
  },

  // ── GOVERNANCE ────────────────────────────────────────────────────────────
  {
    name: "cato_gate",
    description: "Cato pre-settlement doctrine check — consolidated eFICC governance context for DSOR pre-trade record: SOFR, 10y yield, 2y10y spread, OFR stress index, fed liquidity posture. Single tool that Verana L0 calls before any tokenized settlement proceeds. (Renamed from get_ficc_context.)",
    inputSchema: { type: "object", properties: {} }
  }
];

// ── TOOL HANDLERS ─────────────────────────────────────────────────────────────
async function handleTool(name, args) {
  switch (name) {

    case "get_sofr": {
      const data = await get(`${NYFED_BASE}/rates/sofr/last/${args.days || 10}.json`);
      if (data.error) return data;
      return { source: "NY Fed", rate_type: "SOFR", data: data.refRates || data };
    }

    case "get_repo_reference_rates": {
      const type = args.rate_type || "all";
      const results = {};
      const types = type === "all" ? ["sofr","bgcr","tgcr"] : [type];
      for (const t of types) {
        const d = await get(`${NYFED_BASE}/rates/${t}/last/5.json`);
        results[t.toUpperCase()] = d.refRates || d;
      }
      return { source: "NY Fed", rates: results };
    }

    case "get_effr": {
      const data = await get(`${NYFED_BASE}/rates/effr/last/${args.days || 10}.json`);
      return { source: "NY Fed", rate_type: "EFFR", data: data.refRates || data };
    }

    case "get_repo_operations": {
      const type = args.operation_type || "all";
      const results = {};
      if (type === "repo" || type === "all") {
        const d = await get(`${NYFED_BASE}/rp/results/details/last/${args.days || 5}.json`);
        results.repo_operations = d.repo || d;
      }
      if (type === "reverserepo" || type === "all") {
        const d = await get(`${NYFED_BASE}/rp/reverserepo/propositions/details/last/${args.days || 5}.json`);
        results.reverse_repo = d.reverse_repo || d;
      }
      return { source: "NY Fed", operations: results };
    }

    case "get_treasury_yield_curve": {
      const tenor = args.tenor || "all";
      const days = args.days || 5;
      const SERIES = {
        "1m": "DGS1MO", "3m": "DGS3MO", "6m": "DGS6MO",
        "1y": "DGS1", "2y": "DGS2", "3y": "DGS3",
        "5y": "DGS5", "7y": "DGS7", "10y": "DGS10",
        "20y": "DGS20", "30y": "DGS30"
      };
      if (tenor !== "all") {
        const seriesId = SERIES[tenor];
        if (!seriesId) return { error: `Unknown tenor: ${tenor}` };
        return await fredSeries(seriesId, days);
      }
      const results = {};
      for (const [t, s] of Object.entries(SERIES)) {
        const d = await fredSeries(s, 1);
        if (d.observations && d.observations[0]) {
          results[t] = { date: d.observations[0].date, yield: d.observations[0].value };
        }
      }
      return { source: "FRED", description: "US Treasury Constant Maturity Yields", curve: results };
    }

    case "get_tips_yields": {
      const tenor = args.tenor || "all";
      const SERIES = { "5y": "DFII5", "10y": "DFII10", "20y": "DFII20", "30y": "DFII30" };
      const BREAKEVEN = { "5y": "T5YIE", "10y": "T10YIE" };
      const results = {};
      const tenors = tenor === "all" ? Object.keys(SERIES) : [tenor];
      for (const t of tenors) {
        if (SERIES[t]) {
          const d = await fredSeries(SERIES[t], args.days || 10);
          results[`${t}_real_yield`] = d.observations?.[0];
        }
        if (BREAKEVEN[t]) {
          const d = await fredSeries(BREAKEVEN[t], args.days || 10);
          results[`${t}_breakeven`] = d.observations?.[0];
        }
      }
      return { source: "FRED", description: "TIPS Real Yields and Breakeven Inflation", data: results };
    }

    case "get_treasury_auctions": {
      const type = args.security_type || "all";
      const limit = args.limit || 10;
      const params = {
        "fields": "security_type,security_term,auction_date,high_yield,bid_to_cover_ratio,indirect_bidders_accepted_pct,total_accepted",
        "sort": "-auction_date",
        "page[size]": limit,
        "page[number]": 1
      };
      if (type !== "all") params["filter"] = `security_type:eq:${type}`;
      const data = await get(`${TREASURY_BASE}/accounting/od/auctions_query`, params);
      return { source: "TreasuryDirect / Fiscal Data API", auctions: data.data || data };
    }

    case "get_yield_curve_spread": {
      const spread = args.spread || "all";
      const days = args.days || 30;
      const SPREADS = {
        "2y10y": ["DGS10", "DGS2"],
        "3m10y": ["DGS10", "DGS3MO"],
        "5y30y": ["DGS30", "DGS5"]
      };
      const spreadsToCalc = spread === "all" ? Object.keys(SPREADS) : [spread];
      const results = {};
      for (const s of spreadsToCalc) {
        const [longId, shortId] = SPREADS[s];
        const [longD, shortD] = await Promise.all([fredSeries(longId, days), fredSeries(shortId, days)]);
        const obs = (longD.observations || []).map((o, i) => {
          const shortObs = (shortD.observations || [])[i];
          if (!shortObs || o.value === "." || shortObs.value === ".") return null;
          return { date: o.date, spread_bps: ((parseFloat(o.value) - parseFloat(shortObs.value)) * 100).toFixed(1) };
        }).filter(Boolean);
        results[s] = { description: `${s} spread (basis points)`, data: obs.slice(0, days) };
      }
      return { source: "FRED", yield_curve_spreads: results };
    }

    case "get_macro_regime_snapshot": {
      const [effr, sofr, t10y, t2y, t3m, cpi, unrate] = await Promise.all([
        fredSeries("FEDFUNDS", 1),
        fredSeries("SOFR", 1),
        fredSeries("DGS10", 1),
        fredSeries("DGS2", 1),
        fredSeries("DGS3MO", 1),
        fredSeries("CPIAUCSL", 2),
        fredSeries("UNRATE", 1)
      ]);
      const t10 = parseFloat(t10y.observations?.[0]?.value || 0);
      const t2  = parseFloat(t2y.observations?.[0]?.value || 0);
      const t3mV = parseFloat(t3m.observations?.[0]?.value || 0);
      const cpiVals = cpi.observations || [];
      const cpiYoY = cpiVals.length >= 2
        ? (((parseFloat(cpiVals[0].value) - parseFloat(cpiVals[1].value)) / parseFloat(cpiVals[1].value)) * 100 * 12).toFixed(2)
        : "N/A";
      return {
        source: "FRED + NY Fed",
        snapshot_date: new Date().toISOString().split("T")[0],
        rates: {
          fed_funds_rate: effr.observations?.[0],
          sofr: sofr.observations?.[0],
          treasury_10y: t10y.observations?.[0],
          treasury_2y: t2y.observations?.[0],
          treasury_3m: t3m.observations?.[0]
        },
        spreads: {
          "2y10y_bps": ((t10 - t2) * 100).toFixed(1),
          "3m10y_bps": ((t10 - t3mV) * 100).toFixed(1)
        },
        macro: {
          cpi_mom_annualized: cpiYoY,
          unemployment_rate: unrate.observations?.[0]
        }
      };
    }

    case "get_cpi": {
      const s = args.series || "all";
      const months = args.months || 12;
      const results = {};
      if (s === "headline" || s === "all") results.headline_cpi = await fredSeries("CPIAUCSL", months);
      if (s === "core" || s === "all") results.core_cpi = await fredSeries("CPILFESL", months);
      return { source: "FRED / BLS", cpi_data: results };
    }

    case "get_fed_balance_sheet": {
      const weeks = args.weeks || 12;
      const [total, treasuries, mbs, reserves] = await Promise.all([
        fredSeries("WALCL", weeks),
        fredSeries("TREAST", weeks),
        fredSeries("MBST", weeks),
        fredSeries("WRESBAL", weeks)
      ]);
      return {
        source: "FRED / Federal Reserve H.4.1",
        fed_balance_sheet: {
          total_assets: total.observations,
          treasury_securities: treasuries.observations,
          mbs_holdings: mbs.observations,
          reserve_balances: reserves.observations
        }
      };
    }

    case "get_ofr_stress_index": {
      const data = await fredSeries("STLFSI4", args.days || 30);
      return {
        source: "OFR / FRED — St. Louis Fed Financial Stress Index",
        description: "Values above 0 indicate above-average financial stress. Verana L0 systemic stress signal.",
        stress_index: data.observations
      };
    }

    case "get_money_market_rates": {
      const inst = args.instrument || "all";
      const days = args.days || 10;
      const SERIES = {
        "cp_aa_nonfinancial": "DCPN3M",
        "cp_aa_financial": "DCPF3M",
        "cp_a2p2": "DCPN30"
      };
      const results = {};
      const insts = inst === "all" ? Object.keys(SERIES) : [inst];
      for (const i of insts) {
        if (SERIES[i]) results[i] = await fredSeries(SERIES[i], days);
      }
      return { source: "FRED / Federal Reserve", money_market_rates: results };
    }

    case "get_repo_market_context": {
      const days = args.days || 10;
      const includeTerm = args.include_term_sofr !== false;
      const [sofr, rrp, bgcr] = await Promise.all([
        fredSeries("SOFR", days),
        fredSeries("RRPONTSYD", days),
        fredSeries("BGCR", days)
      ]);
      const result = {
        source: "NY Fed + FRED",
        overnight_rates: { sofr: sofr.observations, bgcr: bgcr.observations },
        fed_reverse_repo_volume: rrp.observations
      };
      if (includeTerm) {
        const [t1m, t3m, t6m] = await Promise.all([
          fredSeries("SOFR1", days),
          fredSeries("SOFR3", days),
          fredSeries("SOFR6", days)
        ]);
        result.term_sofr = { "1m": t1m.observations, "3m": t3m.observations, "6m": t6m.observations };
      }
      return result;
    }

    case "get_term_sofr": {
      const tenor = args.tenor || "all";
      const days = args.days || 10;
      const SERIES = { "1m": "SOFR1", "3m": "SOFR3", "6m": "SOFR6", "12m": "SOFR12" };
      const tenors = tenor === "all" ? Object.keys(SERIES) : [tenor];
      const results = {};
      for (const t of tenors) {
        if (SERIES[t]) results[t] = await fredSeries(SERIES[t], days);
      }
      return { source: "FRED — CME Term SOFR", term_sofr: results };
    }

    case "get_recent_13f_filers": {
      const days = args.days_back || 30;
      const cutoff = new Date(Date.now() - days * 86400000).toISOString().split("T")[0];
      const search = await get(
        `${EDGAR_BASE}/efts/v1/hits.json`,
        { q: '"13F-HR"', dateRange: "custom", startdt: cutoff, forms: "13F-HR" }
      );
      return {
        source: "SEC EDGAR",
        description: "Recent 13F institutional holdings filings",
        note: "Use get_company_filings with a specific CIK for full filing details",
        recent_filers: search.hits?.hits?.slice(0, 20).map(h => ({
          company: h._source?.display_names?.[0],
          filed: h._source?.file_date,
          accession: h._source?.accession_no
        })) || search
      };
    }

    case "get_company_filings": {
      const cik = args.cik.padStart(10, "0");
      const formType = args.form_type || "10-K";
      const limit = args.limit || 5;
      const data = await get(`${EDGAR_BASE}/submissions/CIK${cik}.json`);
      if (data.error) return data;
      const filings = data.filings?.recent;
      if (!filings) return { error: "No filings found", cik };
      const filtered = [];
      for (let i = 0; i < filings.form.length && filtered.length < limit; i++) {
        if (formType === "all" || filings.form[i] === formType) {
          filtered.push({
            form: filings.form[i],
            filed: filings.filingDate[i],
            accession: filings.accessionNumber[i],
            url: `https://www.sec.gov/Archives/edgar/full-index/${filings.filingDate[i].slice(0,4)}/`
          });
        }
      }
      return { source: "SEC EDGAR", company: data.name, cik, filings: filtered };
    }

    // ── CATO GATE (was get_ficc_context) ────────────────────────────────────
    case "cato_gate": {
      // v0.2.1: fetch live prices, FRED/NY Fed rates+stress, and multichain
      // rail state in parallel so the DSOR context includes a chain
      // recommendation alongside rates + stress.
      const prices = await getLivePrices();
      const [sofr, t10y, t2y, t3m, stress, rrp, rails] = await Promise.all([
        fredSeries("SOFR", 1),
        fredSeries("DGS10", 1),
        fredSeries("DGS2", 1),
        fredSeries("DGS3MO", 1),
        fredSeries("STLFSI4", 1),
        fredSeries("RRPONTSYD", 1),
        multichainGas(prices),
      ]);
      const t10 = parseFloat(t10y.observations?.[0]?.value || 0);
      const t2  = parseFloat(t2y.observations?.[0]?.value || 0);
      const t3mV = parseFloat(t3m.observations?.[0]?.value || 0);
      const ofrVal = parseFloat(stress.observations?.[0]?.value || 0);

      // Chain recommendation — mirrors routing logic from
      // get_atomic_settlement_gate so cato_gate's answer is consistent.
      const sol_fee = rails.solana.fee_usd_estimate;
      const base_gas = rails.base.gas_gwei;
      const eth_gas = rails.ethereum.gas_gwei;
      let recommended_chain = null;
      if (ofrVal <= 1.0 && (eth_gas === null || eth_gas <= 50) && ofrVal <= 0.5) {
        if (sol_fee !== null && sol_fee < 0.01) recommended_chain = "solana";
        else if (base_gas !== null && base_gas < 1) recommended_chain = "base";
        else if (eth_gas !== null) recommended_chain = "ethereum";
      }

      return {
        source: "FRED + NY Fed + Blockscout + Solana RPC",
        dsor_context_date: new Date().toISOString(),
        description: "Cato pre-settlement doctrine check — DSOR governance context snapshot (v0.2.0 multi-chain)",
        rates: {
          sofr: sofr.observations?.[0],
          treasury_10y: t10y.observations?.[0],
          treasury_2y: t2y.observations?.[0],
          treasury_3m: t3m.observations?.[0]
        },
        spreads: {
          "2y10y_bps": ((t10 - t2) * 100).toFixed(1),
          "3m10y_bps": ((t10 - t3mV) * 100).toFixed(1),
          curve_shape: (t10 - t2) > 0 ? "normal" : (t10 - t2) < -0.25 ? "inverted" : "flat"
        },
        systemic_stress: {
          ofr_stress_index: stress.observations?.[0],
          stress_level: ofrVal > 1 ? "elevated" :
                        ofrVal > 0 ? "above_average" : "normal"
        },
        fed_liquidity: {
          reverse_repo_facility_volume: rrp.observations?.[0]
        },
        chain_state: rails,
        recommended_chain,
        price_sources: {
          eth_usd: prices.eth,
          sol_usd: prices.sol,
          source: prices.source,
          timestamp: prices.timestamp,
          fallback_used: prices.fallback_used,
        },
      };
    }

    // ── ONCHAIN PRICES (Cato v0.2.1) ───────────────────────────────────────
    case "get_onchain_prices": {
      const prices = await getLivePrices();
      return {
        source: "CoinGecko public API",
        eth_usd: prices.eth,
        sol_usd: prices.sol,
        fetch_source: prices.source,
        timestamp: prices.timestamp,
        fallback_used: prices.fallback_used,
        note: prices.note,
      };
    }

    // ── MULTI-CHAIN GAS (Cato v0.2.0, live prices in v0.2.1) ───────────────
    case "get_multichain_gas": {
      const prices = await getLivePrices();
      const rails = await multichainGas(prices);
      return {
        source: "Blockscout (ETH/Base/Arbitrum) + Solana RPC + CoinGecko",
        timestamp: new Date().toISOString(),
        price_sources: {
          eth_usd: prices.eth,
          sol_usd: prices.sol,
          source: prices.source,
          timestamp: prices.timestamp,
          fallback_used: prices.fallback_used,
        },
        ...rails,
      };
    }

    // ── TOKENIZED SETTLEMENT CONTEXT ────────────────────────────────────────
    case "get_tokenized_settlement_context": {
      const [chain, sofr, stress] = await Promise.all([
        blockscoutStats(),
        fredSeries("SOFR", 1),
        fredSeries("STLFSI4", 1)
      ]);
      const gas_gwei = chain?.gas_gwei;
      const sofr_rate = parseFloat(sofr.observations?.[0]?.value || "0");
      const ofr_stress = parseFloat(stress.observations?.[0]?.value || "0");

      // Settlement posture per Cato doctrine thresholds:
      //   elevated  — stress > 1.0 OR gas > 50
      //   monitor   — stress 0.5..1.0 OR gas 30..50
      //   favorable — stress < 0.5 AND gas < 30
      let settlement_posture;
      if (ofr_stress > 1.0 || (gas_gwei !== null && gas_gwei > 50)) {
        settlement_posture = "elevated";
      } else if (ofr_stress > 0.5 || (gas_gwei !== null && gas_gwei > 30)) {
        settlement_posture = "monitor";
      } else {
        settlement_posture = "favorable";
      }

      return {
        source: "Blockscout + FRED (SOFR, STLFSI4)",
        timestamp: new Date().toISOString(),
        gas_gwei,
        sofr_rate,
        ofr_stress,
        settlement_posture
      };
    }

    // ── COMPARE SETTLEMENT RAILS (Cato v0.2.2 — SOFR delta in routing) ─────
    case "compare_settlement_rails": {
      const notional_usd = parseFloat(args.notional_usd);
      if (!Number.isFinite(notional_usd) || notional_usd <= 0) {
        return { error: "notional_usd is required and must be a positive number" };
      }
      const term_days = args.term_days || 1;

      // v0.2.2: fetch live ETH/SOL prices, SOFR with 2 observations
      // (today + prior day for delta), OFR FSI, and multichainGas in
      // parallel. The SOFR delta is now a routing stress override
      // alongside OFR stress.
      const prices = await getLivePrices();
      const [sofrSeries, stressSeries, rails] = await Promise.all([
        fredSeries("SOFR", 2),
        fredSeries("STLFSI4", 1),
        multichainGas(prices),
      ]);
      const sofrObsList = sofrSeries.observations || [];
      const sofr = parseFloat(sofrObsList[0]?.value || "0");
      const sofrPrev = sofrObsList[1]?.value !== undefined ? parseFloat(sofrObsList[1].value) : null;
      const sofrDeltaBps = (sofrPrev !== null && !Number.isNaN(sofrPrev) && !Number.isNaN(sofr))
        ? Math.abs(sofr - sofrPrev) * 100
        : null;
      const ofr_stress = parseFloat(stressSeries.observations?.[0]?.value || "0");

      // ── Per-rail cost calculations (using live prices) ─────────────────
      const ficc_cost = ficcCost(notional_usd, sofr, term_days);
      const eth_cost = evmL1Cost(rails.ethereum.gas_gwei, prices.eth);
      const base_cost = evmL1Cost(rails.base.gas_gwei, prices.eth);
      const arb_cost = evmL1Cost(rails.arbitrum.gas_gwei, prices.eth);
      const sol_cost = solanaCost(rails.solana.fee_lamports, prices.sol);

      const railTable = {
        ficc_traditional: {
          cost_usd: +ficc_cost.toFixed(4),
          speed: "T+1",
          status: "live",
          inputs: { sofr_pct: sofr, term_days, clearing_fee_bps: 0.5, netting_benefit_pct: 40 },
        },
        ethereum_l1: {
          cost_usd: eth_cost !== null ? +eth_cost.toFixed(4) : null,
          speed: rails.ethereum.settlement_speed,
          status: rails.ethereum.status,
          inputs: { gas_gwei: rails.ethereum.gas_gwei, gas_units: 65000, eth_price_usd: prices.eth },
        },
        base: {
          cost_usd: base_cost !== null ? +base_cost.toFixed(4) : null,
          speed: rails.base.settlement_speed,
          status: rails.base.status,
          inputs: { gas_gwei: rails.base.gas_gwei, gas_units: 65000, eth_price_usd: prices.eth },
        },
        arbitrum: {
          cost_usd: arb_cost !== null ? +arb_cost.toFixed(4) : null,
          speed: rails.arbitrum.settlement_speed,
          status: rails.arbitrum.status,
          inputs: { gas_gwei: rails.arbitrum.gas_gwei, gas_units: 65000, eth_price_usd: prices.eth },
        },
        solana: {
          cost_usd: sol_cost !== null ? +sol_cost.toFixed(6) : null,
          speed: rails.solana.settlement_speed,
          status: rails.solana.status,
          inputs: { fee_lamports: rails.solana.fee_lamports, sol_price_usd: prices.sol },
        },
        fed_l1: {
          cost_usd: null,
          speed: "instant",
          status: "not_yet_issued",
          note: "PORTS — Duffie 2025. Pending GENIUS Act.",
        },
      };

      // Ranked cheapest → most expensive (excluding rails with null cost).
      const ranked = Object.entries(railTable)
        .filter(([, r]) => typeof r.cost_usd === "number")
        .sort((a, b) => a[1].cost_usd - b[1].cost_usd)
        .map(([name, r]) => ({ rail: name, cost_usd: r.cost_usd, speed: r.speed, status: r.status }));

      // ── Routing logic (Cato v0.2.2 doctrine — SOFR delta override added)
      const eth_gas = rails.ethereum.gas_gwei;
      const base_gas = rails.base.gas_gwei;
      const solana_fee_usd = rails.solana.fee_usd_estimate;

      let recommended_rail;
      if (ofr_stress > CATO_OFR_HOLD_THRESHOLD) {
        recommended_rail = "ficc_traditional";            // OFR stress override
      } else if (sofrDeltaBps !== null && sofrDeltaBps > CATO_SOFR_DELTA_HOLD_BPS) {
        recommended_rail = "ficc_traditional";            // SOFR delta override (v0.2.2)
      } else if (notional_usd > 10_000_000 && eth_gas !== null && eth_gas < 30) {
        recommended_rail = "ethereum_l1";                 // large notional, gas is noise
      } else if (solana_fee_usd !== null && solana_fee_usd < 0.01) {
        recommended_rail = "solana";                      // ultra-low cost for any size
      } else if (base_gas !== null && base_gas < 1) {
        recommended_rail = "base";                        // L2 default when available
      } else if (eth_gas !== null && eth_gas > CATO_GAS_GWEI_HOLD_THRESHOLD) {
        recommended_rail = "ficc_traditional";            // gas too high
      } else {
        recommended_rail = "ethereum_l1";                 // fallback
      }

      return {
        source: "FRED (SOFR, STLFSI4) + Blockscout (ETH/Base/Arbitrum) + Solana RPC + CoinGecko",
        timestamp: new Date().toISOString(),
        inputs: {
          notional_usd,
          term_days,
          sofr_prev_pct: sofrPrev,
          sofr_delta_bps: sofrDeltaBps !== null ? +sofrDeltaBps.toFixed(2) : null,
        },
        market_state: {
          sofr_pct: sofr,
          sofr_prev_pct: sofrPrev,
          sofr_delta_bps: sofrDeltaBps !== null ? +sofrDeltaBps.toFixed(2) : null,
          ofr_stress,
          ethereum_gas_gwei: eth_gas,
          base_gas_gwei: base_gas,
          arbitrum_gas_gwei: rails.arbitrum.gas_gwei,
          solana_fee_usd_estimate: solana_fee_usd,
          eth_price_usd: prices.eth,
          sol_price_usd: prices.sol,
        },
        price_sources: {
          eth_usd: prices.eth,
          sol_usd: prices.sol,
          source: prices.source,
          timestamp: prices.timestamp,
          fallback_used: prices.fallback_used,
          note: "Live prices via CoinGecko public API. For institutional deployment use a licensed price feed (Bloomberg BVAL, Refinitiv, Chainlink Price Feeds).",
        },
        rails: railTable,
        ranked,
        recommended_rail,
        doctrine_note: "On-chain atomic DvP eliminates T+1 counterparty risk window. FICC clearing provides netting benefit at scale. Cato v0.2.2 routes by notional, gas, OFR stress, AND SOFR 1-day delta — stress overrides (OFR > 0.5 or |SOFR delta| > 10 bps) are absolute and force ficc_traditional.",
        fed_l1_note: "Federal Reserve tokenized deposits (reserves) not yet available for on-chain settlement. PORTS (Duffie 2025) proposes sovereign instrument bridging this gap. Cato will route to Fed L1 when available. Monitor: GENIUS Act, CBDC working groups.",
      };
    }

    // ── ATOMIC SETTLEMENT GATE (Cato v0.2.2 — SOFR delta restored) ─────────
    case "get_atomic_settlement_gate": {
      // v0.2.2: fetch live prices, cato_gate + settlement context,
      // multichain rails, AND a 2-observation SOFR history so we can
      // compute the 1-day delta. The SOFR delta check is the v0.1.0-era
      // funding-market shock detector that was dropped in v0.2.0 and
      // restored after the cato_backtest.py revealed the Sept 2019
      // repo spike gap.
      const prices = await getLivePrices();
      const [gateContext, settlementContext, rails, sofrHistory] = await Promise.all([
        handleTool("cato_gate", {}),
        handleTool("get_tokenized_settlement_context", {}),
        multichainGas(prices),
        fredSeries("SOFR", 2),
      ]);

      const ofr_stress = parseFloat(
        gateContext?.systemic_stress?.ofr_stress_index?.value ?? "0"
      );
      const gas_gwei = settlementContext?.gas_gwei;

      // SOFR 1-day delta computation — null if either observation missing.
      const sofrObs = (sofrHistory && sofrHistory.observations) || [];
      const sofrToday = sofrObs[0]?.value !== undefined ? parseFloat(sofrObs[0].value) : null;
      const sofrPrev = sofrObs[1]?.value !== undefined ? parseFloat(sofrObs[1].value) : null;
      const sofrDeltaBps = (sofrToday !== null && sofrPrev !== null && !Number.isNaN(sofrToday) && !Number.isNaN(sofrPrev))
        ? Math.abs(sofrToday - sofrPrev) * 100
        : null;

      const reasons = [];
      let gate_decision = "PROCEED";
      let recommended_rail = "atomic";
      let recommended_chain = null;

      // ESCALATE first — systemic stress overrides everything
      if (ofr_stress > CATO_OFR_ESCALATE_THRESHOLD) {
        gate_decision = "ESCALATE";
        recommended_rail = "human_authority";
        reasons.push(`OFR stress index at ${ofr_stress.toFixed(2)} — systemic stress threshold (>${CATO_OFR_ESCALATE_THRESHOLD}) breached`);
      } else {
        // HOLD if non-systemic friction
        if (ofr_stress > CATO_OFR_HOLD_THRESHOLD) {
          gate_decision = "HOLD";
          reasons.push(`OFR stress index at ${ofr_stress.toFixed(2)} — above-average stress (>${CATO_OFR_HOLD_THRESHOLD})`);
        }
        if (gas_gwei !== null && gas_gwei !== undefined && gas_gwei > CATO_GAS_GWEI_HOLD_THRESHOLD) {
          gate_decision = "HOLD";
          reasons.push(`ETH gas at ${gas_gwei} gwei — above ${CATO_GAS_GWEI_HOLD_THRESHOLD} gwei doctrine threshold`);
        }
        // v0.2.2: SOFR 1-day delta trigger (funding-market shock detector)
        if (sofrDeltaBps !== null && sofrDeltaBps > CATO_SOFR_DELTA_HOLD_BPS) {
          gate_decision = "HOLD";
          reasons.push(`SOFR 1-day move of ${sofrDeltaBps.toFixed(1)} bps exceeds ${CATO_SOFR_DELTA_HOLD_BPS} bps doctrine threshold (funding-market shock indicator)`);
        }
        if (gate_decision === "HOLD") {
          recommended_rail = "traditional";
        } else {
          reasons.push("All doctrine thresholds clear — atomic settlement viable");
          recommended_rail = "atomic";
        }
      }

      // Recommended chain selection (only meaningful for PROCEED).
      if (gate_decision === "PROCEED") {
        const solana_fee_usd = rails.solana.fee_usd_estimate;
        const base_gas = rails.base.gas_gwei;
        const eth_gas = rails.ethereum.gas_gwei;
        if (solana_fee_usd !== null && solana_fee_usd < 0.01) {
          recommended_chain = "solana";
        } else if (base_gas !== null && base_gas < 1) {
          recommended_chain = "base";
        } else if (eth_gas !== null) {
          recommended_chain = "ethereum";
        } else {
          recommended_chain = null;
        }
      }

      return {
        gate_decision,
        reasons,
        recommended_rail,
        recommended_chain,
        timestamp: new Date().toISOString(),
        doctrine: "Verana L0 — Cato settlement gate v0.2.2",
        inputs: {
          ofr_stress,
          gas_gwei,
          sofr_today_pct: sofrToday,
          sofr_prev_pct: sofrPrev,
          sofr_delta_bps: sofrDeltaBps !== null ? +sofrDeltaBps.toFixed(2) : null,
          settlement_posture: settlementContext?.settlement_posture ?? null,
        },
        thresholds: {
          escalate_ofr: CATO_OFR_ESCALATE_THRESHOLD,
          hold_ofr: CATO_OFR_HOLD_THRESHOLD,
          hold_gas_gwei: CATO_GAS_GWEI_HOLD_THRESHOLD,
          hold_sofr_delta_bps: CATO_SOFR_DELTA_HOLD_BPS,
        },
        chain_state: rails,
        price_sources: {
          eth_usd: prices.eth,
          sol_usd: prices.sol,
          source: prices.source,
          timestamp: prices.timestamp,
          fallback_used: prices.fallback_used,
        },
        solana_note: "Solana 400ms finality eliminates T+1 window entirely at near-zero cost. Network outage history (2022-2023) requires doctrine-level resilience planning. Fallback: Base L2.",
        fed_l1_note: "Federal Reserve tokenized deposits (reserves) not yet available for on-chain settlement. PORTS (Duffie 2025) proposes sovereign instrument bridging this gap. Cato will route to Fed L1 when available. Monitor: GENIUS Act, CBDC working groups.",
      };
    }

    default:
      return { error: `Unknown tool: ${name}` };
  }
}

// ── SERVER SETUP ─────────────────────────────────────────────────────────────
const server = new Server(
  { name: "cato", version: "0.2.2" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: TOOLS
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  try {
    const result = await handleTool(name, args || {});
    return {
      content: [{ type: "text", text: JSON.stringify(result, null, 2) }]
    };
  } catch (err) {
    return {
      content: [{ type: "text", text: JSON.stringify({ error: err.message }) }],
      isError: true
    };
  }
});

// ── START ────────────────────────────────────────────────────────────────────
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write("Cato MCP Server v0.2.2 running — 23 tools across NY Fed, FRED, TreasuryDirect, OFR, SEC EDGAR, Blockscout (ETH/Base/Arbitrum), Solana RPC, CoinGecko. Multi-chain settlement router with live prices + SOFR delta funding-shock detector. Absolute doctrine for tokenized settlement governance.\n");
}

main().catch(err => {
  process.stderr.write(`Fatal: ${err.message}\n`);
  process.exit(1);
});
