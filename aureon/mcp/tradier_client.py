"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/mcp/tradier_client.py                                        ║
║  Atrox — Tradier Options Data Pipe                           ║
║                                                                      ║
║  MANDATE:                                                            ║
║    Provides Thifur with live options chains, greeks, and IV          ║
║    surface data for stress testing and pre-trade analysis.           ║
║                                                                      ║
║  DATA DOMAINS:                                                       ║
║    - Options chains (strikes, expiries, bid/ask)                     ║
║    - Greeks (delta, gamma, theta, vega, rho)                         ║
║    - Implied Volatility surface                                       ║
║    - Historical volatility                                           ║
║    - Quote data (equity + options)                                   ║
║                                                                      ║
║  API: Tradier Brokerage REST API                                     ║
║  Base URL: https://api.tradier.com/v1                                ║
║  Auth: Authorization: Bearer <TRADIER_API_TOKEN>                     ║
║  Free tier: paper trading environment at sandbox.tradier.com         ║
║  Live tier: brokerage account required                               ║
║                                                                      ║
║  Env vars:                                                           ║
║    TRADIER_API_TOKEN  — bearer token (live or sandbox)               ║
║    TRADIER_SANDBOX    — set to "true" to use sandbox endpoint        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import json
import os
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from typing import Optional, List

# ── Tradier API Config ────────────────────────────────────────────────────────
TRADIER_LIVE_BASE    = "https://api.tradier.com/v1"
TRADIER_SANDBOX_BASE = "https://sandbox.tradier.com/v1"

# ── Atrox Pipe Identity ─────────────────────────────────────────────────────
PIPE_ID          = "TRADIER-PIPE-001"
PIPE_NAME        = "Tradier — Options Chains + Greeks + IV Surface"
PIPE_VERSION     = "1.0"
PIPE_URI_PREFIX  = "aureon://atrox/pipe/tradier"

# Module-level client singleton
_client: Optional["TradierClient"] = None


class TradierClient:
    """
    Atrox MCP data pipe client for Tradier.

    Wraps the Tradier REST API as a structured data pipe with full
    provenance. Supports live and sandbox environments.

    Usage:
        client = TradierClient()

        # Options chain for a ticker
        chain = client.get_options_chain("AAPL", expiration="2026-05-16")

        # Greeks for a specific option
        quote = client.get_options_quotes(["AAPL260516C00200000"])

        # IV surface (all expirations)
        surface = client.get_iv_surface("SPY")

        # Historical volatility
        hv = client.get_historical_volatility("SPY", interval="weekly")
    """

    def __init__(self, api_token: Optional[str] = None, sandbox: bool = False):
        self._token   = api_token or os.environ.get("TRADIER_API_TOKEN", "")
        self._sandbox = sandbox or os.environ.get("TRADIER_SANDBOX", "").lower() == "true"
        self._base    = TRADIER_SANDBOX_BASE if self._sandbox else TRADIER_LIVE_BASE
        self._ready   = bool(self._token)

    @property
    def is_ready(self) -> bool:
        return self._ready

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """GET request with provenance wrapping."""
        if not self._ready:
            raise RuntimeError(
                "TRADIER_API_TOKEN not configured. "
                "Register at tradier.com — free paper trading tier available."
            )

        url = f"{self._base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )

        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "aureon-atrox/1.0")

        ts = datetime.now(timezone.utc).isoformat()
        env_label = "sandbox" if self._sandbox else "live"

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw    = resp.read()
                data   = json.loads(raw)
                digest = hashlib.sha256(raw).hexdigest()[:16].upper()
                return {
                    "ok":           True,
                    "pipe_id":      PIPE_ID,
                    "source_uri":   f"{PIPE_URI_PREFIX}{path}",
                    "endpoint":     path,
                    "env":          env_label,
                    "params":       params or {},
                    "ts":           ts,
                    "content_hash": digest,
                    "data":         data,
                }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            return {
                "ok":       False,
                "pipe_id":  PIPE_ID,
                "source_uri": f"{PIPE_URI_PREFIX}{path}",
                "endpoint": path,
                "env":      env_label,
                "ts":       ts,
                "error":    f"HTTP {exc.code}: {body[:200]}",
                "data":     None,
            }
        except Exception as exc:
            return {
                "ok":       False,
                "pipe_id":  PIPE_ID,
                "source_uri": f"{PIPE_URI_PREFIX}{path}",
                "endpoint": path,
                "env":      env_label,
                "ts":       ts,
                "error":    str(exc),
                "data":     None,
            }

    # ─────────────────────────────────────────────────────────────────────────
    # EQUITY QUOTES
    # ─────────────────────────────────────────────────────────────────────────

    def get_quotes(self, symbols: List[str]) -> dict:
        """
        Real-time equity quotes.
        Endpoint: GET /markets/quotes
        """
        return self._get("/markets/quotes", {"symbols": ",".join(symbols), "greeks": "false"})

    # ─────────────────────────────────────────────────────────────────────────
    # OPTIONS CHAINS
    # ─────────────────────────────────────────────────────────────────────────

    def get_options_expirations(self, symbol: str, include_all_roots: bool = False) -> dict:
        """
        All available expiration dates for a symbol.
        Endpoint: GET /markets/options/expirations
        """
        return self._get("/markets/options/expirations", {
            "symbol":            symbol,
            "includeAllRoots":   "true" if include_all_roots else "false",
        })

    def get_options_chain(self, symbol: str, expiration: str, greeks: bool = True) -> dict:
        """
        Full options chain for a symbol + expiration date.
        Endpoint: GET /markets/options/chains

        Args:
            symbol:     Underlying ticker (e.g. "SPY")
            expiration: YYYY-MM-DD format
            greeks:     Include delta/gamma/theta/vega/rho
        """
        return self._get("/markets/options/chains", {
            "symbol":     symbol,
            "expiration": expiration,
            "greeks":     "true" if greeks else "false",
        })

    def get_options_quotes(self, option_symbols: List[str], greeks: bool = True) -> dict:
        """
        Quote + greeks for specific option contracts.
        Endpoint: GET /markets/options/quotes

        Args:
            option_symbols: OCC-standard symbols e.g. ["SPY260620C00500000"]
        """
        return self._get("/markets/options/quotes", {
            "symbols": ",".join(option_symbols),
            "greeks":  "true" if greeks else "false",
        })

    def get_option_strikes(self, symbol: str, expiration: str) -> dict:
        """
        Available strike prices for a symbol + expiration.
        Endpoint: GET /markets/options/strikes
        """
        return self._get("/markets/options/strikes", {
            "symbol":     symbol,
            "expiration": expiration,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # IMPLIED VOLATILITY SURFACE
    # ─────────────────────────────────────────────────────────────────────────

    def get_iv_surface(self, symbol: str) -> dict:
        """
        Build an IV surface across all available expirations.
        Calls expirations first, then pulls chains with greeks.

        Atrox domain: Volatility regime + stress test calibration.
        """
        ts = datetime.now(timezone.utc).isoformat()
        exp_result = self.get_options_expirations(symbol)
        if not exp_result.get("ok"):
            return {**exp_result, "surface_type": "iv_surface"}

        expirations_data = exp_result.get("data", {})
        expirations = []

        # Tradier returns {"expirations": {"date": [...] or "..."}}
        raw_exp = expirations_data.get("expirations", {})
        if isinstance(raw_exp, dict):
            d = raw_exp.get("date", [])
            expirations = d if isinstance(d, list) else [d]

        surface = []
        for exp_date in expirations[:8]:  # cap at 8 expirations — Thifur stress horizon
            chain_result = self.get_options_chain(symbol, exp_date, greeks=True)
            if chain_result.get("ok"):
                surface.append({
                    "expiration": exp_date,
                    "chain":      chain_result.get("data"),
                })

        raw_bytes = json.dumps(surface).encode()
        digest    = hashlib.sha256(raw_bytes).hexdigest()[:16].upper()

        return {
            "ok":           True,
            "pipe_id":      PIPE_ID,
            "source_uri":   f"{PIPE_URI_PREFIX}/iv-surface/{symbol}",
            "surface_type": "iv_surface",
            "symbol":       symbol,
            "expirations_count": len(surface),
            "ts":           ts,
            "content_hash": digest,
            "data":         surface,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # HISTORICAL VOLATILITY
    # ─────────────────────────────────────────────────────────────────────────

    def get_historical_volatility(self, symbol: str,
                                   interval: str = "daily",
                                   start: Optional[str] = None,
                                   end: Optional[str] = None) -> dict:
        """
        Historical price bars — used to compute realized volatility.
        Endpoint: GET /markets/history

        Args:
            interval: "daily" | "weekly" | "monthly"
            start/end: YYYY-MM-DD
        """
        return self._get("/markets/history", {
            "symbol":   symbol,
            "interval": interval,
            "start":    start,
            "end":      end,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # THIFUR STRESS PACKET
    # ─────────────────────────────────────────────────────────────────────────

    def get_thifur_stress_packet(self, symbols: List[str],
                                  expiration: Optional[str] = None) -> dict:
        """
        Full Thifur stress-test data packet for a list of symbols.
        Pulls: quotes, nearest expiration chain with greeks, HV.

        Atrox domain: Pre-trade stress testing + concentration analysis.
        """
        ts     = datetime.now(timezone.utc).isoformat()
        result = {
            "ok":        True,
            "pipe_id":   PIPE_ID,
            "source_uri": f"{PIPE_URI_PREFIX}/thifur-stress-packet",
            "ts":        ts,
            "symbols":   symbols,
            "data": {},
        }

        quotes = self.get_quotes(symbols)
        result["data"]["quotes"] = quotes

        for symbol in symbols[:5]:  # cap at 5 to stay within rate limits
            # Get nearest expiration if not specified
            if not expiration:
                exp_r = self.get_options_expirations(symbol)
                exp_date = None
                if exp_r.get("ok"):
                    raw = exp_r.get("data", {}).get("expirations", {})
                    d   = raw.get("date", []) if isinstance(raw, dict) else []
                    exp_date = d[0] if d else None
            else:
                exp_date = expiration

            symbol_data = {}
            if exp_date:
                chain = self.get_options_chain(symbol, exp_date, greeks=True)
                symbol_data["chain"] = chain
                symbol_data["expiration"] = exp_date

            hv = self.get_historical_volatility(symbol)
            symbol_data["historical_volatility"] = hv

            result["data"][symbol] = symbol_data

        raw_bytes = json.dumps(result["data"]).encode()
        result["content_hash"] = hashlib.sha256(raw_bytes).hexdigest()[:16].upper()
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Module-level pipe interface (matches atrox_client.py pattern)
# ─────────────────────────────────────────────────────────────────────────────

def init_tradier_pipe(api_token: Optional[str] = None) -> "TradierClient":
    """Initialize (or re-initialize) the Tradier pipe client."""
    global _client
    _client = TradierClient(api_token=api_token)
    return _client


def get_client() -> Optional["TradierClient"]:
    """Return the module-level client, or None if not initialized."""
    return _client


def pipe_status() -> dict:
    """Return pipe health dict for /api/atrox/status aggregation."""
    token_present = bool(os.environ.get("TRADIER_API_TOKEN", ""))
    sandbox       = os.environ.get("TRADIER_SANDBOX", "").lower() == "true"
    return {
        "pipe_id":  PIPE_ID,
        "name":     PIPE_NAME,
        "version":  PIPE_VERSION,
        "status":   "live" if token_present else "degraded",
        "env":      "sandbox" if sandbox else "live",
        "source":   "tradier.com",
        "token":    "present" if token_present else "missing — set TRADIER_API_TOKEN",
        "docs":     "https://documentation.tradier.com",
        "ts":       datetime.now(timezone.utc).isoformat(),
    }
