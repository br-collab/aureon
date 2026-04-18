"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/mcp/atrox_client.py                                        ║
║  Atrox — Unusual Whales MCP Data Pipe Client                 ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Atrox's first live external data pipe.                    ║
║    Ingests options flow, dark pool prints, and market sentiment      ║
║    from Unusual Whales (unusualwhales.com/public-api/mcp).           ║
║                                                                      ║
║  ARCHITECTURE NOTE:                                                  ║
║    Unusual Whales exposes a skill.md REST API manifest               ║
║    (Anthropic tool-use pattern), not a JSON-RPC MCP server.          ║
║    This client wraps their REST API as a structured MCP data pipe    ║
║    with full provenance — every ingestion record carries:            ║
║      - source URI (aureon://atrox/pipe/unusual-whales/{resource})  ║
║      - timestamp, endpoint, API version                              ║
║      - raw response hash for lineage                                 ║
║                                                                      ║
║  API SPEC REF: https://unusualwhales.com/skill.md                    ║
║  Base URL: https://api.unusualwhales.com                             ║
║  Auth: Authorization: Bearer <UW_API_TOKEN>                          ║
║        UW-CLIENT-API-ID: 100001                                      ║
║                                                                      ║
║  DOCTRINE: Every data source Atrox consumes is a named,            ║
║  versioned resource URI. Not a raw API call. This is what makes      ║
║  Atrox's recommendations auditable — "what data did Atrox        ║
║  use?" is answered by the provenance record, not memory.             ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import json
import os
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from typing import Optional

# ── Unusual Whales API Config ─────────────────────────────────────────────────
UW_BASE_URL      = "https://api.unusualwhales.com"
UW_CLIENT_ID     = "100001"
UW_SKILL_MANIFEST = "https://unusualwhales.com/skill.md"

# ── Atrox Pipe Resource URI prefix ─────────────────────────────────────────
# Every data ingestion record carries a URI so Atrox's recommendations
# can cite the exact data source — the MCP provenance standard.
PIPE_URI_PREFIX  = "aureon://atrox/pipe/unusual-whales"

# ── Data pipe identity ────────────────────────────────────────────────────────
PIPE_ID      = "UW-PIPE-001"
PIPE_NAME    = "Unusual Whales — Options Flow + Dark Pool"
PIPE_VERSION = "1.0"


class UnusualWhalesClient:
    """
    Atrox MCP data pipe client for Unusual Whales.

    Wraps the Unusual Whales REST API as a structured data pipe
    with full provenance — each response carries source URI,
    timestamp, endpoint, and content hash.

    Usage:
        client = UnusualWhalesClient(api_token=os.environ["UW_API_TOKEN"])

        # Options flow alerts
        flow = client.get_flow_alerts(limit=25, min_premium=50000)

        # Dark pool — market wide
        dp = client.get_darkpool_recent(limit=25)

        # Dark pool — specific ticker
        dp_spy = client.get_darkpool_ticker("SPY")

        # Market tide (sentiment)
        tide = client.get_market_tide()

        # Full Atrox ingestion packet — all three in one call
        packet = client.get_atrox_ingestion_packet(tickers=["SPY","QQQ","MSFT"])
    """

    def __init__(self, api_token: Optional[str] = None):
        self._token   = api_token or os.environ.get("UW_API_TOKEN", "")
        self._ready   = bool(self._token)

    @property
    def is_ready(self) -> bool:
        return self._ready

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """
        Execute a GET request against the Unusual Whales API.
        Returns a provenance-wrapped response dict.

        Raises: RuntimeError if token missing.
                urllib.error.HTTPError on API errors.
        """
        if not self._ready:
            raise RuntimeError(
                "UW_API_TOKEN not configured. "
                "Add UW_API_TOKEN to .env and Railway Variables. "
                "Purchase at: https://unusualwhales.com/pricing?product=api"
            )

        url = f"{UW_BASE_URL}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )

        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("UW-CLIENT-API-ID", UW_CLIENT_ID)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "aureon-atrox/1.0")

        ts = datetime.now(timezone.utc).isoformat()

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw   = resp.read()
                data  = json.loads(raw)
                digest = hashlib.sha256(raw).hexdigest()[:16].upper()
                return {
                    "ok":        True,
                    "pipe_id":   PIPE_ID,
                    "source_uri": f"{PIPE_URI_PREFIX}{path}",
                    "endpoint":  path,
                    "params":    params or {},
                    "ts":        ts,
                    "content_hash": digest,
                    "data":      data,
                }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            return {
                "ok":        False,
                "pipe_id":   PIPE_ID,
                "source_uri": f"{PIPE_URI_PREFIX}{path}",
                "endpoint":  path,
                "ts":        ts,
                "error":     f"HTTP {exc.code}: {body[:200]}",
                "data":      None,
            }
        except Exception as exc:
            return {
                "ok":        False,
                "pipe_id":   PIPE_ID,
                "source_uri": f"{PIPE_URI_PREFIX}{path}",
                "endpoint":  path,
                "ts":        ts,
                "error":     str(exc),
                "data":      None,
            }

    # ─────────────────────────────────────────────────────────────────────────
    # OPTIONS FLOW
    # ─────────────────────────────────────────────────────────────────────────

    def get_flow_alerts(self,
                        limit: int = 25,
                        min_premium: Optional[int] = None,
                        ticker_symbol: Optional[str] = None,
                        is_call: Optional[bool] = None,
                        is_put: Optional[bool] = None,
                        is_otm: Optional[bool] = None,
                        size_greater_oi: Optional[bool] = None) -> dict:
        """
        Unusual options flow alerts — whale trades.
        Endpoint: GET /api/option-trades/flow-alerts
        Atrox domain: Trade Origination + Market Intelligence
        """
        params = {"limit": limit}
        if min_premium is not None:
            params["min_premium"] = min_premium
        if ticker_symbol:
            params["ticker_symbol"] = ticker_symbol
        if is_call is not None:
            params["is_call"] = str(is_call).lower()
        if is_put is not None:
            params["is_put"] = str(is_put).lower()
        if is_otm is not None:
            params["is_otm"] = str(is_otm).lower()
        if size_greater_oi is not None:
            params["size_greater_oi"] = str(size_greater_oi).lower()

        result = self._get("/api/option-trades/flow-alerts", params)
        result["atrox_domain"] = "TRADE_ORIGINATION"
        result["signal_type"]    = "OPTIONS_FLOW_ALERT"
        return result

    def get_flow_recent(self, ticker: str) -> dict:
        """
        Recent options flow for a specific ticker.
        Endpoint: GET /api/stock/{ticker}/flow-recent
        """
        result = self._get(f"/api/stock/{ticker.upper()}/flow-recent")
        result["atrox_domain"] = "MARKET_INTELLIGENCE"
        result["signal_type"]    = "TICKER_FLOW_RECENT"
        result["ticker"]         = ticker.upper()
        return result

    def get_options_screener(self,
                             limit: int = 25,
                             min_premium: Optional[int] = None,
                             option_type: Optional[str] = None,
                             is_otm: Optional[bool] = None,
                             min_volume_oi_ratio: Optional[float] = None) -> dict:
        """
        Hottest chains / options screener.
        Endpoint: GET /api/screener/option-contracts
        """
        params = {"limit": limit}
        if min_premium is not None:
            params["min_premium"] = min_premium
        if option_type:
            params["type"] = option_type
        if is_otm is not None:
            params["is_otm"] = str(is_otm).lower()
        if min_volume_oi_ratio is not None:
            params["min_volume_oi_ratio"] = min_volume_oi_ratio

        result = self._get("/api/screener/option-contracts", params)
        result["atrox_domain"] = "TRADE_ORIGINATION"
        result["signal_type"]    = "OPTIONS_SCREENER"
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # DARK POOL
    # ─────────────────────────────────────────────────────────────────────────

    def get_darkpool_recent(self, limit: int = 25) -> dict:
        """
        Market-wide dark pool prints.
        Endpoint: GET /api/darkpool/recent
        Atrox domain: Market Intelligence
        """
        result = self._get("/api/darkpool/recent", {"limit": limit})
        result["atrox_domain"] = "MARKET_INTELLIGENCE"
        result["signal_type"]    = "DARK_POOL_MARKET_WIDE"
        return result

    def get_darkpool_ticker(self, ticker: str) -> dict:
        """
        Dark pool prints for a specific ticker.
        Endpoint: GET /api/darkpool/{ticker}
        """
        result = self._get(f"/api/darkpool/{ticker.upper()}")
        result["atrox_domain"] = "MARKET_INTELLIGENCE"
        result["signal_type"]    = "DARK_POOL_TICKER"
        result["ticker"]         = ticker.upper()
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # MARKET SENTIMENT
    # ─────────────────────────────────────────────────────────────────────────

    def get_market_tide(self) -> dict:
        """
        Market tide — net premium, put/call sentiment.
        Endpoint: GET /api/market/market-tide
        Atrox domain: Market Intelligence
        """
        result = self._get("/api/market/market-tide")
        result["atrox_domain"] = "MARKET_INTELLIGENCE"
        result["signal_type"]    = "MARKET_TIDE"
        return result

    def get_net_prem_ticks(self, ticker: str) -> dict:
        """
        Net premium ticks for a ticker.
        Endpoint: GET /api/stock/{ticker}/net-prem-ticks
        """
        result = self._get(f"/api/stock/{ticker.upper()}/net-prem-ticks")
        result["atrox_domain"] = "MARKET_INTELLIGENCE"
        result["signal_type"]    = "NET_PREMIUM_TICKS"
        result["ticker"]         = ticker.upper()
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # GREEKS + IV
    # ─────────────────────────────────────────────────────────────────────────

    def get_greeks(self, ticker: str) -> dict:
        """Greeks per strike/expiry. Endpoint: GET /api/stock/{ticker}/greeks"""
        result = self._get(f"/api/stock/{ticker.upper()}/greeks")
        result["atrox_domain"] = "MARKET_INTELLIGENCE"
        result["signal_type"]    = "OPTIONS_GREEKS"
        result["ticker"]         = ticker.upper()
        return result

    def get_spot_gex(self, ticker: str) -> dict:
        """Spot gamma exposure by strike. Endpoint: GET /api/stock/{ticker}/spot-exposures/strike"""
        result = self._get(f"/api/stock/{ticker.upper()}/spot-exposures/strike")
        result["atrox_domain"] = "MARKET_INTELLIGENCE"
        result["signal_type"]    = "SPOT_GEX"
        result["ticker"]         = ticker.upper()
        return result

    def get_options_volume(self, ticker: str) -> dict:
        """Options volume + put/call ratio. Endpoint: GET /api/stock/{ticker}/options-volume"""
        result = self._get(f"/api/stock/{ticker.upper()}/options-volume")
        result["atrox_domain"] = "MARKET_INTELLIGENCE"
        result["signal_type"]    = "OPTIONS_VOLUME_PC"
        result["ticker"]         = ticker.upper()
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # ATROX INGESTION PACKET
    # Primary entry point for the Atrox intelligence cycle
    # ─────────────────────────────────────────────────────────────────────────

    def get_atrox_ingestion_packet(self,
                                     tickers: Optional[list] = None,
                                     flow_min_premium: int = 100_000,
                                     flow_limit: int = 25,
                                     darkpool_limit: int = 25) -> dict:
        """
        Full Atrox ingestion packet — all three primary domains.

        Pulls options flow alerts, market-wide dark pool, market tide,
        and ticker-level flow/dark pool for each specified ticker.

        Returns a single provenance-wrapped packet that Atrox uses
        to generate investment theses. Every field carries source URI
        so the operator can trace exactly what Atrox saw.

        This is what makes Atrox's recommendations auditable.
        """
        ts     = datetime.now(timezone.utc).isoformat()
        tickers = [t.upper() for t in (tickers or [])]

        packet = {
            "packet_id":    f"ATROX-PKT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "pipe_id":      PIPE_ID,
            "pipe_name":    PIPE_NAME,
            "pipe_version": PIPE_VERSION,
            "ts":           ts,
            "tickers":      tickers,
            "provenance": {
                "source":   "Unusual Whales API",
                "skill_manifest": UW_SKILL_MANIFEST,
                "base_url": UW_BASE_URL,
                "pipe_uri": f"{PIPE_URI_PREFIX}/atrox-packet",
            },
            "domains": {
                "TRADE_ORIGINATION": {},
                "MARKET_INTELLIGENCE": {},
            },
            "errors": [],
        }

        # ── Domain 1: Trade Origination — options flow ────────────────
        flow = self.get_flow_alerts(
            limit       = flow_limit,
            min_premium = flow_min_premium,
        )
        packet["domains"]["TRADE_ORIGINATION"]["flow_alerts"] = flow
        if not flow["ok"]:
            packet["errors"].append({"source": "flow_alerts", "error": flow.get("error")})

        screener = self.get_options_screener(limit=flow_limit, min_premium=flow_min_premium)
        packet["domains"]["TRADE_ORIGINATION"]["screener"] = screener
        if not screener["ok"]:
            packet["errors"].append({"source": "screener", "error": screener.get("error")})

        # ── Domain 2: Market Intelligence — dark pool + sentiment ─────
        dp = self.get_darkpool_recent(limit=darkpool_limit)
        packet["domains"]["MARKET_INTELLIGENCE"]["darkpool_market"] = dp
        if not dp["ok"]:
            packet["errors"].append({"source": "darkpool_market", "error": dp.get("error")})

        tide = self.get_market_tide()
        packet["domains"]["MARKET_INTELLIGENCE"]["market_tide"] = tide
        if not tide["ok"]:
            packet["errors"].append({"source": "market_tide", "error": tide.get("error")})

        # ── Ticker-level enrichment ───────────────────────────────────
        ticker_data = {}
        for ticker in tickers:
            ticker_data[ticker] = {}

            flow_r = self.get_flow_recent(ticker)
            ticker_data[ticker]["flow_recent"] = flow_r
            if not flow_r["ok"]:
                packet["errors"].append({"source": f"{ticker}/flow_recent", "error": flow_r.get("error")})

            dp_t = self.get_darkpool_ticker(ticker)
            ticker_data[ticker]["darkpool"] = dp_t
            if not dp_t["ok"]:
                packet["errors"].append({"source": f"{ticker}/darkpool", "error": dp_t.get("error")})

            vol = self.get_options_volume(ticker)
            ticker_data[ticker]["options_volume"] = vol
            if not vol["ok"]:
                packet["errors"].append({"source": f"{ticker}/options_volume", "error": vol.get("error")})

        packet["domains"]["MARKET_INTELLIGENCE"]["tickers"] = ticker_data

        # ── Packet summary ────────────────────────────────────────────
        packet["summary"] = {
            "calls_attempted":  4 + len(tickers) * 3,
            "calls_succeeded":  4 + len(tickers) * 3 - len(packet["errors"]),
            "errors":           len(packet["errors"]),
            "ready_for_atrox": len(packet["errors"]) == 0,
        }

        return packet


# ── Module-level singleton (injected by server.py) ────────────────────────────
_client: Optional[UnusualWhalesClient] = None


def init_atrox_pipe(api_token: Optional[str] = None) -> UnusualWhalesClient:
    """
    Initialize the Atrox / Unusual Whales data pipe.
    Called by server.py at startup — token read from UW_API_TOKEN env var.
    """
    global _client
    token   = api_token or os.environ.get("UW_API_TOKEN", "")
    _client = UnusualWhalesClient(api_token=token)
    status  = "READY" if _client.is_ready else "NO TOKEN — add UW_API_TOKEN"
    print(f"[ATROX] Unusual Whales data pipe — {status}")
    return _client


def get_client() -> Optional[UnusualWhalesClient]:
    """Return the initialized client, or None if not initialized."""
    return _client


def pipe_status() -> dict:
    """Return data pipe status for API exposure."""
    return {
        "pipe_id":      PIPE_ID,
        "pipe_name":    PIPE_NAME,
        "pipe_version": PIPE_VERSION,
        "source":       "Unusual Whales API",
        "skill_manifest": UW_SKILL_MANIFEST,
        "base_url":     UW_BASE_URL,
        "ready":        _client.is_ready if _client else False,
        "endpoints": [
            "flow_alerts", "flow_recent", "options_screener",
            "darkpool_recent", "darkpool_ticker",
            "market_tide", "net_prem_ticks",
            "greeks", "spot_gex", "options_volume",
            "atrox_ingestion_packet",
        ],
        "atrox_domains": ["TRADE_ORIGINATION", "MARKET_INTELLIGENCE"],
        "provenance_uri_prefix": PIPE_URI_PREFIX,
    }
