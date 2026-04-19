"""
Thifur-H — Kraken Live Client
==============================
Replaces GeminiSandboxClient for live Kraken account execution.

Kraken API signing: two-step HMAC-SHA512
  1. nonce + POST data → SHA256
  2. URI path + SHA256 result → SHA512 with API secret

Doctrine constants tightened for live account:
  MAX_POSITION_USD   : $10  (was $50 sandbox)
  MAX_SESSION_LOSS   : $5   (was $25 sandbox)
  MAX_ORDER_QTY_BTC  : 0.0001 BTC (~$10 at $100k)

Author: Project Aureon · Guillermo "Bill" Ravelo
"""

import hashlib
import hmac
import base64
import urllib.parse
import urllib.request
import urllib.error
import json
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger("thifur_h.kraken")


# ─────────────────────────────────────────────
# DOCTRINE CONSTANTS — LIVE ACCOUNT
# Agent cannot read, modify, or reason about these.
# ─────────────────────────────────────────────

class ThifurHDoctrineLive:
    MAX_POSITION_USD: float = 10.0
    MAX_SESSION_LOSS_USD: float = 5.0
    MAX_ORDER_QTY_BTC: float = 0.0001
    MAX_ORDERS_PER_SESSION: int = 20
    HITL_REQUIRED: bool = True
    SANDBOX_ONLY: bool = False          # Live account
    ALLOWED_SYMBOLS: tuple = ("XBTUSD",)  # Kraken BTC symbol
    ALLOWED_SIDES: tuple = ("buy", "sell")
    ALLOWED_ORDER_TYPES: tuple = ("limit",)


class KrakenLiveClient:
    """
    Kraken REST client for Thifur-H live account validation.
    Endpoints: place order, cancel order, cancel all, get order status, get balance.
    No market orders. Limit only. Position bounds enforced by gate layer above.
    """

    BASE_URL = "https://api.kraken.com"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def _sign(self, uri_path: str, data: dict) -> str:
        """
        Kraken two-step HMAC-SHA512 signing.
        Step 1: SHA256(nonce + encoded_data)
        Step 2: HMAC-SHA512(uri_path + step1, base64_decoded_secret)
        """
        encoded = urllib.parse.urlencode(data).encode()
        sha256_hash = hashlib.sha256(
            data["nonce"].encode() + encoded
        ).digest()
        secret = base64.b64decode(self.api_secret)
        mac = hmac.new(
            secret,
            uri_path.encode() + sha256_hash,
            hashlib.sha512
        )
        return base64.b64encode(mac.digest()).decode()

    def _post(self, uri_path: str, data: dict) -> dict:
        data["nonce"] = str(int(time.time() * 1000))
        signature = self._sign(uri_path, data)
        headers = {
            "API-Key": self.api_key,
            "API-Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        url = self.BASE_URL + uri_path
        encoded_data = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(
            url, data=encoded_data, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                if result.get("error"):
                    logger.error(f"Kraken API error: {result['error']}")
                return result
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            logger.error(f"Kraken HTTP error {e.code}: {body}")
            return {"error": [body], "result": {}}

    def get_balance(self) -> dict:
        return self._post("/0/private/Balance", {})

    def get_ticker(self, pair: str = "XBTUSD") -> dict:
        url = f"{self.BASE_URL}/0/public/Ticker?pair={pair}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {"error": [str(e)], "result": {}}

    def get_current_price(self, pair: str = "XBTUSD") -> float:
        ticker = self.get_ticker(pair)
        try:
            # Kraken returns pair data under result key
            result = ticker.get("result", {})
            pair_data = result.get(pair) or result.get("XXBTZUSD", {})
            return float(pair_data.get("c", [0])[0])
        except Exception:
            return 0.0

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        price: str,
        quantity: str,
        client_order_id: str
    ) -> dict:
        assert symbol in ThifurHDoctrineLive.ALLOWED_SYMBOLS, \
            f"DOCTRINE BREACH: {symbol} not in whitelist"
        assert side in ThifurHDoctrineLive.ALLOWED_SIDES, \
            f"DOCTRINE BREACH: side {side} not allowed"

        data = {
            "ordertype": "limit",
            "type": side,
            "volume": quantity,
            "pair": symbol,
            "price": price,
            "oflags": "post",        # Post-only — maker order, no immediate fill
            "cl_ord_id": client_order_id[:36],  # Kraken max 36 chars
        }
        result = self._post("/0/private/AddOrder", data)
        logger.info(f"Kraken order placed: {result}")
        return result

    def cancel_order(self, txid: str) -> dict:
        """Rollback — cancel by transaction ID."""
        result = self._post("/0/private/CancelOrder", {"txid": txid})
        logger.info(f"Kraken order cancelled: {txid} → {result}")
        return result

    def cancel_all_orders(self) -> dict:
        """Kill switch — cancel ALL open orders."""
        result = self._post("/0/private/CancelAll", {})
        logger.warning(f"Kraken CANCEL ALL: {result}")
        return result

    def get_open_orders(self) -> dict:
        return self._post("/0/private/OpenOrders", {})

    def get_order_status(self, txid: str) -> dict:
        return self._post("/0/private/QueryOrders", {"txids": txid})
