# eFICC MCP Server

Free, open-source MCP (Model Context Protocol) server for Fixed Income, Currencies & Commodities market data.

**No API keys required for core functionality.** All data sourced from free public APIs.

---

## Data Sources

| Source | Data | Auth Required |
|--------|------|---------------|
| **NY Fed** | SOFR, BGCR, TGCR, EFFR, repo operations | None |
| **FRED** | Treasury yields, fed funds, CPI, Fed balance sheet, Term SOFR | None (optional key for higher rate limits) |
| **TreasuryDirect / Fiscal Data API** | Auction results, bid-to-cover, indirect bidder % | None |
| **OFR (Office of Financial Research)** | Financial Stress Index, systemic risk indicators | None |
| **SEC EDGAR** | 13F filings, institutional positioning, company filings | None |

---

## Tools (17)

### NY Fed
- `get_sofr` — SOFR daily rate history
- `get_repo_reference_rates` — SOFR, BGCR, TGCR
- `get_effr` — Effective Federal Funds Rate
- `get_repo_operations` — Fed open market repo/reverse repo operations

### Treasury Yield Curve
- `get_treasury_yield_curve` — Full curve 1m → 30y or specific tenor
- `get_tips_yields` — TIPS real yields and breakeven inflation
- `get_treasury_auctions` — Auction results, bid-to-cover, indirect bidder %
- `get_yield_curve_spread` — 2y10y, 3m10y, 5y30y spreads in basis points

### Macro Regime
- `get_macro_regime_snapshot` — Full eFICC regime in one call
- `get_cpi` — CPI headline and core
- `get_fed_balance_sheet` — Total assets, Treasury holdings, MBS, reserves

### OFR Systemic Risk
- `get_ofr_stress_index` — Financial stress composite
- `get_money_market_rates` — Commercial paper rates

### Repo Market
- `get_repo_market_context` — Overnight + term SOFR + reverse repo facility
- `get_term_sofr` — CME Term SOFR 1m/3m/6m/12m

### SEC EDGAR
- `get_recent_13f_filers` — Recent institutional holdings filings
- `get_company_filings` — Company-specific SEC filings by CIK

### Governance
- `get_ficc_context` — Pre-trade DSOR governance context package (Aureon integration)

---

## Installation

```bash
git clone https://github.com/[org]/eficc-mcp
cd eficc-mcp
npm install
```

## Usage with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "eficc": {
      "command": "node",
      "args": ["/path/to/eficc-mcp/index.js"],
      "env": {
        "FRED_API_KEY": "optional_free_key_from_fred_stlouisfed_org"
      }
    }
  }
}
```

## Optional: FRED API Key

Free FRED API keys available at https://fred.stlouisfed.org/docs/api/api_key.html

Without a key, FRED endpoints still work at lower rate limits. Add your key as `FRED_API_KEY` environment variable for higher throughput.

---

## Aureon Integration

The `get_ficc_context` tool is designed as a pre-trade DSOR governance context package for Aureon Post-Trade eFICC. It returns:
- Current rate regime (SOFR, 2y10y spread, curve shape)
- Systemic stress level (OFR Financial Stress Index)
- Fed liquidity posture (reverse repo facility volume)

This package feeds directly into Mentat doctrine gate decisions and Thifur-R settlement context.

---

## License

MIT — free to use, fork, and build on.

---

*Built as part of Project Aureon — doctrine-governed financial operating system.*
*Ravelo Strategic Solutions LLC · Columbia University MS Technology Management*
