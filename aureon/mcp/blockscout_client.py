"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  aureon/mcp/blockscout_client.py                                     ║
║  Neptune Spear — Blockscout On-Chain Intelligence Pipe               ║
║                                                                      ║
║  MANDATE:                                                            ║
║    On-chain intelligence for TradFi-DeFi convergence monitoring.    ║
║    ETH gas, block production, whale wallet activity, token flows,   ║
║    and DeFi protocol state — all with structured provenance.        ║
║                                                                      ║
║  DATA DOMAINS:                                                       ║
║    - Ethereum network stats (gas, block height, TPS)                ║
║    - Address balance and activity (whale monitoring)                 ║
║    - Token transfer tracking                                         ║
║    - Transaction inspection                                          ║
║    - Smart contract read (DeFi protocol state)                       ║
║                                                                      ║
║  API: Blockscout public REST API (no auth required)                  ║
║  Base: https://eth.blockscout.com/api/v2                             ║
║  Chains: Ethereum (1), Polygon (137), Base (8453), Arbitrum (42161) ║
║                                                                      ║
║  NO API KEY REQUIRED — public Blockscout explorer data.             ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional, List, Dict

# ── Blockscout API Endpoints ─────────────────────────────────────────────────
BLOCKSCOUT_CHAINS = {
    "1":     "https://eth.blockscout.com",
    "137":   "https://polygon.blockscout.com",
    "8453":  "https://base.blockscout.com",
    "42161": "https://arbitrum.blockscout.com",
    "10":    "https://optimism.blockscout.com",
    "100":   "https://gnosis.blockscout.com",
}

DEFAULT_CHAIN_ID = "1"  # Ethereum Mainnet

# ── Neptune Pipe Identity ─────────────────────────────────────────────────────
PIPE_ID         = "BLOCKSCOUT-PIPE-001"
PIPE_NAME       = "Blockscout — On-Chain Intelligence"
PIPE_VERSION    = "1.0"
PIPE_URI_PREFIX = "aureon://neptune/pipe/blockscout"

# Module-level client singleton
_client: Optional["BlockscoutClient"] = None


class BlockscoutClient:
    """
    Neptune Spear MCP data pipe client for Blockscout on-chain data.

    No API key required — pulls from public Blockscout explorer API.
    All responses include structured provenance (source URI, timestamp, hash).

    Usage:
        client = BlockscoutClient()

        # Network stats
        stats = client.get_network_stats()

        # Address info + balance
        addr = client.get_address("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")

        # Token transfers for a wallet
        xfers = client.get_token_transfers("0x...")

        # Full on-chain packet
        packet = client.get_onchain_packet()
    """

    def __init__(self, default_chain_id: str = DEFAULT_CHAIN_ID):
        self._default_chain = default_chain_id
        self._ready = True

    @property
    def is_ready(self) -> bool:
        return True

    def _base_url(self, chain_id: str = None) -> str:
        cid = chain_id or self._default_chain
        return BLOCKSCOUT_CHAINS.get(cid, BLOCKSCOUT_CHAINS[DEFAULT_CHAIN_ID])

    def _fetch(self, path: str, chain_id: str = None) -> dict:
        """GET a Blockscout API endpoint and return parsed JSON."""
        base = self._base_url(chain_id)
        url = f"{base}{path}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "Aureon/1.0 (Neptune Spear Blockscout Pipe)",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                return json.loads(raw)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            return {"error": str(e), "url": url}

    def _provenance(self, data: dict, chain_id: str = None, resource: str = "") -> dict:
        """Wrap response with Neptune provenance envelope."""
        cid = chain_id or self._default_chain
        raw = json.dumps(data, sort_keys=True, default=str)
        return {
            "ok": "error" not in data,
            "pipe_id": PIPE_ID,
            "source": f"{self._base_url(cid)}/api/v2",
            "source_uri": f"{PIPE_URI_PREFIX}/{resource}",
            "chain_id": cid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content_hash": hashlib.sha256(raw.encode()).hexdigest()[:16],
            "data": data,
        }

    # ── Network Stats ────────────────────────────────────────────────────────

    def get_network_stats(self, chain_id: str = None) -> dict:
        """
        Ethereum network statistics — gas price, total transactions,
        average block time, market cap, total addresses.
        """
        data = self._fetch("/api/v2/stats", chain_id)
        return self._provenance(data, chain_id, "network-stats")

    def get_block_number(self, chain_id: str = None) -> dict:
        """Current block height."""
        data = self._fetch("/api/v2/main-page/blocks?type=block", chain_id)
        block_number = None
        if isinstance(data, list) and len(data) > 0:
            block_number = data[0].get("height") or data[0].get("number")
            data = {"block_number": block_number, "blocks": data[:5]}
        elif isinstance(data, dict) and "items" in data:
            items = data["items"]
            if items:
                block_number = items[0].get("height") or items[0].get("number")
            data = {"block_number": block_number, "blocks": items[:5]}
        return self._provenance(data, chain_id, "block-number")

    # ── Address Intelligence ─────────────────────────────────────────────────

    def get_address(self, address: str, chain_id: str = None) -> dict:
        """
        Address info — balance, tx count, token holdings, contract status.
        Key for whale wallet monitoring.
        """
        data = self._fetch(f"/api/v2/addresses/{address}", chain_id)
        return self._provenance(data, chain_id, f"address/{address[:10]}")

    def get_address_transactions(self, address: str, chain_id: str = None,
                                  limit: int = 10) -> dict:
        """Recent transactions for an address."""
        data = self._fetch(
            f"/api/v2/addresses/{address}/transactions?limit={limit}", chain_id
        )
        return self._provenance(data, chain_id, f"address-txns/{address[:10]}")

    def get_token_transfers(self, address: str, chain_id: str = None,
                             limit: int = 20) -> dict:
        """ERC-20/721/1155 token transfers for an address."""
        data = self._fetch(
            f"/api/v2/addresses/{address}/token-transfers?limit={limit}", chain_id
        )
        return self._provenance(data, chain_id, f"token-transfers/{address[:10]}")

    def get_address_tokens(self, address: str, chain_id: str = None) -> dict:
        """Token balances held by an address."""
        data = self._fetch(f"/api/v2/addresses/{address}/tokens", chain_id)
        return self._provenance(data, chain_id, f"tokens/{address[:10]}")

    # ── Transaction / Block ──────────────────────────────────────────────────

    def get_transaction(self, tx_hash: str, chain_id: str = None) -> dict:
        """Full transaction details by hash."""
        data = self._fetch(f"/api/v2/transactions/{tx_hash}", chain_id)
        return self._provenance(data, chain_id, f"tx/{tx_hash[:10]}")

    def get_block(self, block_id: str, chain_id: str = None) -> dict:
        """Block info by number or hash."""
        data = self._fetch(f"/api/v2/blocks/{block_id}", chain_id)
        return self._provenance(data, chain_id, f"block/{block_id}")

    # ── Token Lookup ─────────────────────────────────────────────────────────

    def search_token(self, query: str, chain_id: str = None) -> dict:
        """Search tokens by name or symbol."""
        data = self._fetch(f"/api/v2/search?q={query}", chain_id)
        return self._provenance(data, chain_id, f"search/{query}")

    # ── Smart Contract ───────────────────────────────────────────────────────

    def get_contract(self, address: str, chain_id: str = None) -> dict:
        """Contract ABI and verification info."""
        data = self._fetch(f"/api/v2/smart-contracts/{address}", chain_id)
        return self._provenance(data, chain_id, f"contract/{address[:10]}")

    # ── Market / DeFi ────────────────────────────────────────────────────────

    def get_market_chart(self, chain_id: str = None) -> dict:
        """Native token market chart data."""
        data = self._fetch("/api/v2/stats/charts/market", chain_id)
        return self._provenance(data, chain_id, "market-chart")

    def get_gas_tracker(self, chain_id: str = None) -> dict:
        """Current gas price tracker."""
        data = self._fetch("/api/v2/stats/charts/gas", chain_id)
        return self._provenance(data, chain_id, "gas-tracker")

    # ── Neptune Composite Packet ─────────────────────────────────────────────

    def get_onchain_packet(self, chain_id: str = None,
                           watch_addresses: List[str] = None) -> dict:
        """
        Full Neptune on-chain intelligence packet.
        Network stats + gas + recent blocks + optional whale watch.
        """
        cid = chain_id or self._default_chain

        # Network stats
        stats = self._fetch("/api/v2/stats", cid)

        # Gas chart
        gas = self._fetch("/api/v2/stats/charts/gas", cid)

        # Recent blocks
        blocks = self._fetch("/api/v2/main-page/blocks?type=block", cid)

        # Whale watch (if addresses provided)
        whale_data = []
        for addr in (watch_addresses or [])[:5]:  # cap at 5
            info = self._fetch(f"/api/v2/addresses/{addr}", cid)
            if "error" not in info:
                whale_data.append({
                    "address": addr,
                    "balance": info.get("coin_balance") or info.get("fetched_coin_balance"),
                    "tx_count": info.get("transactions_count"),
                    "token_count": info.get("token_transfers_count"),
                })

        packet = {
            "network_stats": stats if "error" not in stats else None,
            "gas": gas if "error" not in gas else None,
            "recent_blocks": (blocks[:5] if isinstance(blocks, list)
                             else blocks.get("items", [])[:5] if isinstance(blocks, dict)
                             else None),
            "whale_watch": whale_data if whale_data else None,
            "chain_id": cid,
            "chain_name": {
                "1": "Ethereum", "137": "Polygon", "8453": "Base",
                "42161": "Arbitrum", "10": "Optimism", "100": "Gnosis",
            }.get(cid, f"Chain {cid}"),
        }

        raw = json.dumps(packet, sort_keys=True, default=str)
        return {
            "ok": True,
            "pipe_id": PIPE_ID,
            "source": f"{self._base_url(cid)}/api/v2",
            "source_uri": f"{PIPE_URI_PREFIX}/onchain-packet",
            "chain_id": cid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content_hash": hashlib.sha256(raw.encode()).hexdigest()[:16],
            "data": packet,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level pipe interface
# ─────────────────────────────────────────────────────────────────────────────

def init_blockscout_pipe(default_chain_id: str = DEFAULT_CHAIN_ID) -> "BlockscoutClient":
    """Initialize (or re-initialize) the Blockscout pipe client."""
    global _client
    _client = BlockscoutClient(default_chain_id=default_chain_id)
    return _client


def get_client() -> Optional["BlockscoutClient"]:
    return _client


def pipe_status() -> dict:
    """Blockscout requires no credentials — always live."""
    return {
        "pipe_id": PIPE_ID,
        "name":    PIPE_NAME,
        "version": PIPE_VERSION,
        "status":  "live",
        "source":  "eth.blockscout.com (public, no auth required)",
        "token":   "none required",
        "chains":  list(BLOCKSCOUT_CHAINS.keys()),
        "docs":    "https://docs.blockscout.com/devs/apis",
        "ts":      datetime.now(timezone.utc).isoformat(),
    }
