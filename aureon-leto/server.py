"""
Aureon-Leto — CAOM-001 Operator Console — local Flask backend on port 5002.

Single pane of glass for everything Sam executes on the operator's behalf.
Health-monitored proxy to Railway production, direct Kraken bypass for
kill-switch, file-queue bridge to Sam (Claude Code), local DSOR archive.

Doctrine:
  - Kraken DOWN  -> trading actions blocked (circuit OPEN)
  - Railway DOWN -> stale-state read-only mode, kill-switch still works direct
  - Circuit re-arm requires explicit operator action; no auto-resume
  - Kill-switch always enabled regardless of health
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Flask, Response, jsonify, request, send_from_directory

# ─────────────────────────────────────────────────────────────────
# CONFIG — load aureon-leto/.env (no python-dotenv dependency)
# ─────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

_load_env(ENV_FILE)

KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.environ.get("KRAKEN_API_SECRET", "")
RAILWAY_BASE = os.environ.get("RAILWAY_BASE", "https://aureon-production.up.railway.app").rstrip("/")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "br-collab/aureon")
VERCEL_URL = os.environ.get("VERCEL_URL", "").rstrip("/")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
PORT = int(os.environ.get("CONSOLE_PORT", "5002"))
HEALTH_INTERVAL = int(os.environ.get("HEALTH_INTERVAL", "30"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

DSOR_ARCHIVE = ROOT / "dsor_archive"
SAM_INBOX = ROOT / "sam_inbox"
SAM_OUTBOX = ROOT / "sam_outbox"
for d in (DSOR_ARCHIVE, SAM_INBOX, SAM_OUTBOX):
    d.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LETO] %(levelname)s %(message)s",
)
log = logging.getLogger("leto")


# ─────────────────────────────────────────────────────────────────
# KRAKEN DIRECT CLIENT — minimal, for health + kill-switch fallback
# ─────────────────────────────────────────────────────────────────

class KrakenDirect:
    BASE_URL = "https://api.kraken.com"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def _sign(self, uri_path: str, data: dict) -> str:
        encoded = urllib.parse.urlencode(data).encode()
        sha256_hash = hashlib.sha256(data["nonce"].encode() + encoded).digest()
        secret = base64.b64decode(self.api_secret)
        mac = hmac.new(secret, uri_path.encode() + sha256_hash, hashlib.sha512)
        return base64.b64encode(mac.digest()).decode()

    def _post(self, uri_path: str, data: dict, timeout: float = 8.0) -> dict:
        if not (self.api_key and self.api_secret):
            return {"error": ["KRAKEN credentials not configured"], "result": {}}
        data = dict(data)
        data["nonce"] = str(int(time.time() * 1000))
        signature = self._sign(uri_path, data)
        headers = {
            "API-Key": self.api_key,
            "API-Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        url = self.BASE_URL + uri_path
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(data).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return {"error": [f"HTTP {e.code}: {e.read().decode()[:120]}"], "result": {}}
        except Exception as e:
            return {"error": [f"{type(e).__name__}: {e}"], "result": {}}

    def get_time(self, timeout: float = 5.0) -> dict:
        try:
            with urllib.request.urlopen(self.BASE_URL + "/0/public/Time", timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": [f"{type(e).__name__}: {e}"], "result": {}}

    def get_balance(self) -> dict:
        return self._post("/0/private/Balance", {})

    def cancel_all(self) -> dict:
        return self._post("/0/private/CancelAll", {})

    def get_open_orders(self) -> dict:
        return self._post("/0/private/OpenOrders", {})


KRAKEN = KrakenDirect(KRAKEN_API_KEY, KRAKEN_API_SECRET)


# ─────────────────────────────────────────────────────────────────
# HEALTH MONITOR — 7 deps, three tiers, background thread, SSE push
# ─────────────────────────────────────────────────────────────────

@dataclass
class DepStatus:
    name: str
    tier: int
    status: str = "UNKNOWN"      # UP | DEGRADED | DOWN | UNKNOWN
    latency_ms: Optional[int] = None
    last_ok: Optional[str] = None
    last_checked: Optional[str] = None
    detail: str = ""


HEALTH: dict[str, DepStatus] = {
    "railway":     DepStatus(name="Railway Prod",   tier=1),
    "kraken_rest": DepStatus(name="Kraken REST",    tier=1),
    "kraken_auth": DepStatus(name="Kraken Auth",    tier=1),
    "github":      DepStatus(name="GitHub",         tier=2),
    "dsor_volume": DepStatus(name="DSOR Archive",   tier=3),
}

# Circuit breaker state.
# Trips OPEN when a Tier-1 Kraken dep transitions UP -> DOWN.
# Stays open until /api/circuit/rearm called (Kraken must be UP at re-arm time).
_circuit_open = False
_circuit_reason = ""
_circuit_lock = threading.Lock()

# SSE subscribers — each is a Queue the broadcaster pushes payloads to.
_sse_subscribers: list[queue.Queue] = []
_sse_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_ping(url: str, timeout: float = 5.0, headers: Optional[dict] = None) -> tuple[Optional[int], int, str]:
    """Returns (http_code, latency_ms, error_or_empty). http_code=None on connection failure."""
    headers = headers or {}
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(256)  # drain a little
            return r.status, int((time.time() - t0) * 1000), ""
    except urllib.error.HTTPError as e:
        return e.code, int((time.time() - t0) * 1000), f"HTTP {e.code}"
    except Exception as e:
        return None, int((time.time() - t0) * 1000), f"{type(e).__name__}: {e}"


def _classify(latency_ms: int, threshold_ok: int, threshold_slow: int) -> str:
    if latency_ms <= threshold_ok:
        return "UP"
    if latency_ms <= threshold_slow:
        return "DEGRADED"
    return "DEGRADED"  # latency above slow but reachable still degraded


def _check_railway() -> None:
    code, lat, err = _http_ping(f"{RAILWAY_BASE}/api/snapshot", timeout=8.0)
    s = HEALTH["railway"]
    s.last_checked = _now_iso()
    s.latency_ms = lat
    if code == 200:
        s.status = "UP" if lat < 500 else "DEGRADED"
        s.last_ok = _now_iso()
        s.detail = ""
    else:
        s.status = "DOWN"
        s.detail = err or f"HTTP {code}"


def _check_kraken_rest() -> None:
    code, lat, err = _http_ping(KRAKEN.BASE_URL + "/0/public/Time", timeout=5.0)
    s = HEALTH["kraken_rest"]
    s.last_checked = _now_iso()
    s.latency_ms = lat
    if code == 200:
        s.status = "UP" if lat < 500 else "DEGRADED"
        s.last_ok = _now_iso()
        s.detail = ""
    else:
        s.status = "DOWN"
        s.detail = err or f"HTTP {code}"


def _check_kraken_auth() -> None:
    s = HEALTH["kraken_auth"]
    s.last_checked = _now_iso()
    if not (KRAKEN_API_KEY and KRAKEN_API_SECRET):
        s.status = "DOWN"
        s.latency_ms = None
        s.detail = "credentials not configured"
        return
    t0 = time.time()
    res = KRAKEN.get_balance()
    s.latency_ms = int((time.time() - t0) * 1000)
    err = res.get("error") or []
    if err:
        s.status = "DOWN"
        s.detail = str(err[0])[:120]
    else:
        s.status = "UP" if s.latency_ms < 800 else "DEGRADED"
        s.last_ok = _now_iso()
        s.detail = ""


def _check_github() -> None:
    code, lat, err = _http_ping(
        f"https://api.github.com/repos/{GITHUB_REPO}/commits?per_page=1",
        timeout=6.0,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "aureon-leto"},
    )
    s = HEALTH["github"]
    s.last_checked = _now_iso()
    s.latency_ms = lat
    if code == 200:
        s.status = "UP" if lat < 800 else "DEGRADED"
        s.last_ok = _now_iso()
        s.detail = ""
    else:
        s.status = "DOWN"
        s.detail = err or f"HTTP {code}"


def _check_dsor_volume() -> None:
    s = HEALTH["dsor_volume"]
    s.last_checked = _now_iso()
    t0 = time.time()
    try:
        probe = DSOR_ARCHIVE / ".health_probe"
        probe.write_text(_now_iso())
        probe.unlink(missing_ok=True)
        s.latency_ms = int((time.time() - t0) * 1000)
        s.status = "UP"
        s.last_ok = _now_iso()
        s.detail = ""
    except Exception as e:
        s.latency_ms = int((time.time() - t0) * 1000)
        s.status = "DOWN"
        s.detail = f"{type(e).__name__}: {e}"


CHECKS = [
    _check_railway,
    _check_kraken_rest,
    _check_kraken_auth,
    _check_github,
    _check_dsor_volume,
]


def _broadcast_health() -> None:
    payload = {
        "type": "health",
        "ts": _now_iso(),
        "deps": {k: asdict(v) for k, v in HEALTH.items()},
        "circuit_open": _circuit_open,
        "circuit_reason": _circuit_reason,
    }
    msg = f"data: {json.dumps(payload)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


def _maybe_trip_circuit() -> None:
    """Trip OPEN if any Tier-1 Kraken dep is DOWN. Never auto-close."""
    global _circuit_open, _circuit_reason
    with _circuit_lock:
        if _circuit_open:
            return
        for k in ("kraken_rest", "kraken_auth"):
            if HEALTH[k].status == "DOWN":
                _circuit_open = True
                _circuit_reason = f"{HEALTH[k].name} DOWN — {HEALTH[k].detail}"
                log.warning(f"CIRCUIT OPEN — {_circuit_reason}")
                return


def _health_loop() -> None:
    while True:
        for fn in CHECKS:
            try:
                fn()
            except Exception as e:
                log.error(f"health check {fn.__name__} crashed: {e}")
        _maybe_trip_circuit()
        _broadcast_health()
        time.sleep(HEALTH_INTERVAL)


def _trading_blocked() -> Optional[str]:
    """Returns a reason string if trading is currently blocked, else None."""
    if _circuit_open:
        return f"Circuit OPEN — {_circuit_reason}. Re-arm via /api/circuit/rearm."
    if HEALTH["railway"].status == "DOWN":
        return "Railway production unreachable — trading actions disabled."
    if HEALTH["kraken_rest"].status == "DOWN":
        return "Kraken REST unreachable — trading halted."
    if HEALTH["kraken_auth"].status == "DOWN":
        return f"Kraken auth failure — {HEALTH['kraken_auth'].detail}"
    return None


# ─────────────────────────────────────────────────────────────────
# RAILWAY PROXY HELPERS
# ─────────────────────────────────────────────────────────────────

def _railway_request(method: str, path: str, body: Optional[dict] = None, timeout: float = 12.0) -> tuple[int, dict]:
    url = RAILWAY_BASE + path
    data = json.dumps(body or {}).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            try:
                payload = json.loads(r.read())
            except Exception:
                payload = {"_raw": True}
            return r.status, payload
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read())
        except Exception:
            payload = {"error": e.read().decode()[:200] if hasattr(e, "read") else str(e)}
        return e.code, payload
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


# ─────────────────────────────────────────────────────────────────
# FLASK APP
# ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)


@app.route("/")
def index():
    return send_from_directory(str(ROOT), "index.html")


@app.route("/api/health")
def api_health():
    return jsonify({
        "deps": {k: asdict(v) for k, v in HEALTH.items()},
        "circuit_open": _circuit_open,
        "circuit_reason": _circuit_reason,
        "trading_blocked": _trading_blocked(),
        "ts": _now_iso(),
    })


@app.route("/api/health/stream")
def api_health_stream():
    q: queue.Queue = queue.Queue(maxsize=32)
    with _sse_lock:
        _sse_subscribers.append(q)

    def gen():
        # Send current state immediately on connect.
        snap = {
            "type": "health",
            "ts": _now_iso(),
            "deps": {k: asdict(v) for k, v in HEALTH.items()},
            "circuit_open": _circuit_open,
            "circuit_reason": _circuit_reason,
        }
        yield f"data: {json.dumps(snap)}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _sse_lock:
                if q in _sse_subscribers:
                    _sse_subscribers.remove(q)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/circuit/rearm", methods=["POST"])
def api_circuit_rearm():
    global _circuit_open, _circuit_reason
    with _circuit_lock:
        if not _circuit_open:
            return jsonify({"status": "noop", "message": "Circuit already closed."})
        for k in ("kraken_rest", "kraken_auth"):
            if HEALTH[k].status != "UP":
                return jsonify({
                    "status": "error",
                    "message": f"Cannot re-arm: {HEALTH[k].name} is {HEALTH[k].status}.",
                }), 409
        _circuit_open = False
        prev_reason = _circuit_reason
        _circuit_reason = ""
        log.warning(f"CIRCUIT RE-ARMED by operator — previously {prev_reason}")
    _broadcast_health()
    return jsonify({"status": "ok", "message": "Circuit re-armed.", "previous_reason": prev_reason})


# ── Mission Status (proxy) ─────────────────────────────────────────

_snapshot_cache = {"ts": None, "payload": None}

@app.route("/api/snapshot")
def api_snapshot():
    code, payload = _railway_request("GET", "/api/snapshot", timeout=6.0)
    if code == 200:
        _snapshot_cache["ts"] = _now_iso()
        _snapshot_cache["payload"] = payload
        return jsonify({"live": True, "ts": _snapshot_cache["ts"], "data": payload})
    if _snapshot_cache["payload"] is not None:
        return jsonify({
            "live": False,
            "ts": _snapshot_cache["ts"],
            "data": _snapshot_cache["payload"],
            "stale_reason": f"Railway {code}",
        })
    return jsonify({"live": False, "ts": None, "data": None, "stale_reason": f"Railway {code}, no cache"}), 502


# ── Thifur-H proxies ───────────────────────────────────────────────

def _gated_post(path: str, body: dict):
    blocked = _trading_blocked()
    if blocked:
        return jsonify({"status": "blocked", "message": blocked}), 423
    code, payload = _railway_request("POST", path, body)
    return jsonify(payload), code


@app.route("/api/thifur/session")
def api_thifur_session():
    code, payload = _railway_request("GET", "/api/thifur-h/session", timeout=6.0)
    return jsonify(payload), code


@app.route("/api/thifur/start", methods=["POST"])
def api_thifur_start():
    return _gated_post("/api/thifur-h/session/start", request.get_json(silent=True) or {})


@app.route("/api/thifur/signal", methods=["POST"])
def api_thifur_signal():
    return _gated_post("/api/thifur-h/signal", request.get_json(silent=True) or {})


@app.route("/api/thifur/approve", methods=["POST"])
def api_thifur_approve():
    return _gated_post("/api/thifur-h/approve", request.get_json(silent=True) or {})


@app.route("/api/thifur/rollback", methods=["POST"])
def api_thifur_rollback():
    return _gated_post("/api/thifur-h/rollback", request.get_json(silent=True) or {})


@app.route("/api/thifur/kill", methods=["POST"])
def api_thifur_kill():
    """
    Kill switch — ALWAYS enabled. Calls Kraken DIRECTLY (bypasses Railway).
    Also notifies Railway if reachable, so the session ledger stays consistent.
    """
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "operator kill switch")
    direct = KRAKEN.cancel_all()
    railway = None
    if HEALTH["railway"].status != "DOWN":
        _, railway = _railway_request("POST", "/api/thifur-h/kill-switch", {"reason": reason})
    return jsonify({
        "status": "killed",
        "kraken_direct": direct,
        "railway_notified": railway,
        "ts": _now_iso(),
    })


# ── DSOR — proxy + local archive ────────────────────────────────────

@app.route("/api/dsor/live")
def api_dsor_live():
    code, payload = _railway_request("GET", "/api/thifur-h/dsor", timeout=10.0)
    if code == 200 and isinstance(payload, dict) and "dsor_entries" in payload:
        try:
            session_id = (payload.get("session_summary") or {}).get("session_id", "unknown")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            (DSOR_ARCHIVE / f"dsor_{session_id}_{stamp}.json").write_text(json.dumps(payload, indent=2))
        except Exception as e:
            log.error(f"DSOR archive write failed: {e}")
    return jsonify(payload), code


@app.route("/api/dsor/archive")
def api_dsor_archive():
    files = sorted(
        (p for p in DSOR_ARCHIVE.glob("dsor_*.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return jsonify({
        "count": len(files),
        "files": [{
            "name": p.name,
            "size": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
        } for p in files[:200]],
    })


@app.route("/api/dsor/archive/<name>")
def api_dsor_archive_file(name: str):
    if "/" in name or ".." in name:
        return jsonify({"error": "invalid name"}), 400
    p = DSOR_ARCHIVE / name
    if not p.exists():
        return jsonify({"error": "not found"}), 404
    return Response(p.read_bytes(), mimetype="application/json")


# ── Sam command surface — file queue ───────────────────────────────

_kraken_balance_cache = {"ts": 0.0, "payload": None}


@app.route("/api/kraken/balance")
def api_kraken_balance():
    """30s-cached Kraken balance. UI uses this for the LIVE ACCT tile."""
    now = time.time()
    if _kraken_balance_cache["payload"] is None or (now - _kraken_balance_cache["ts"]) > 30:
        res = KRAKEN.get_balance()
        if not res.get("error"):
            _kraken_balance_cache["payload"] = res.get("result", {})
            _kraken_balance_cache["ts"] = now
        else:
            return jsonify({"error": res.get("error", []), "ts": _now_iso()}), 502
    bal = _kraken_balance_cache["payload"] or {}
    zusd = float(bal.get("ZUSD", 0))
    xxbt = float(bal.get("XXBT", 0))
    return jsonify({
        "zusd": zusd,
        "xxbt": xxbt,
        "all": bal,
        "cached_at": datetime.fromtimestamp(_kraken_balance_cache["ts"], tz=timezone.utc).isoformat(),
        "ts": _now_iso(),
    })


# ─────────────────────────────────────────────────────────────────
# CLAUDE API DISPATCH — auto-respond to Sam tasks via Anthropic API
# Optional: requires ANTHROPIC_API_KEY in environment.
# Runs on a background thread per task; writes outbox when done.
# This Sam is a stateless API instance — different from a Claude Code
# session. Good for status/Q&A. Tasks needing real shell/file/git work
# still need to be dispatched to Claude Code via the inbox path.
# ─────────────────────────────────────────────────────────────────

_SAM_SYSTEM_PROMPT = """You are Sam, the Claude-grade agent surface that the CAOM-001 operator dispatches through the Aureon-Leto operator console.

Context:
  - Aureon = doctrine-governed pre-trade governance + execution-intelligence platform
  - Aureon-Leto = the local operator console (port 5002) the operator is using right now
  - CAOM-001 = single-operator authority pattern (Consolidated Authority Operating Mode)
  - Thifur-H = Phase 2 adaptive execution layer running live against Kraken (5-gate governance, $10/$5 caps, XBTUSD only)

Operator preferences (load-bearing):
  - BLUF (bottom line up front), no sycophancy, spell out acronyms first time
  - Honest > polished: raw observations beat smooth narrative
  - Operator runs Python only; if you reference other code, translate to Python intent
  - Don't ask permission between sub-steps once a directional yes is given
  - You do NOT have shell, git, file-write, or deploy access in this dispatch path. If a task requires those, say so explicitly and tell the operator to dispatch via Claude Code chat with the inbox path.

Output: be concrete and tight. If the task is a question, answer it. If the task asks for action you can't take, say so in one sentence and stop."""


def _dispatch_to_claude(task_id: str, task_text: str) -> None:
    """Background: call Anthropic API, write structured outbox JSON when done."""
    try:
        body = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1024,
            "system": _SAM_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": task_text}],
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read())
        text = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
        usage = payload.get("usage", {})
        result = {
            "status": "complete",
            "summary": text.strip(),
            "actions_taken": [],
            "follow_ups": [],
            "dispatched_via": "anthropic_api",
            "model": payload.get("model", ANTHROPIC_MODEL),
            "tokens": {"in": usage.get("input_tokens"), "out": usage.get("output_tokens")},
            "ts": _now_iso(),
        }
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read())
        except Exception:
            err_body = {"error": str(e)}
        result = {
            "status": "error",
            "summary": f"Anthropic API HTTP {e.code}: {err_body}",
            "dispatched_via": "anthropic_api",
            "ts": _now_iso(),
        }
    except Exception as e:
        result = {
            "status": "error",
            "summary": f"Dispatch failed: {type(e).__name__}: {e}",
            "dispatched_via": "anthropic_api",
            "ts": _now_iso(),
        }
    out = SAM_OUTBOX / f"task-{task_id}.json"
    out.write_text(json.dumps(result, indent=2))
    log.info(f"SAM api dispatch complete: {task_id} -> {result.get('status')}")


@app.route("/api/sam/task", methods=["POST"])
def api_sam_task():
    body = request.get_json(silent=True) or {}
    text = (body.get("task") or "").strip()
    if not text:
        return jsonify({"error": "task body required"}), 400
    task_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.urandom(2).hex()}"
    fname = SAM_INBOX / f"task-{task_id}.md"
    fname.write_text(
        f"# Task {task_id}\n\nSubmitted: {_now_iso()}\nStatus: pending\n\n## Body\n\n{text}\n"
    )
    log.info(f"SAM task created: {fname.name}")

    auto = bool(ANTHROPIC_API_KEY)
    if auto:
        threading.Thread(
            target=_dispatch_to_claude,
            args=(task_id, text),
            daemon=True,
            name=f"sam-dispatch-{task_id}",
        ).start()

    return jsonify({
        "task_id": task_id,
        "inbox_path": str(fname),
        "paste_hint": f"Read and execute: {fname}",
        "auto_dispatched": auto,
        "model": ANTHROPIC_MODEL if auto else None,
        "ts": _now_iso(),
    })


@app.route("/api/sam/tasks")
def api_sam_tasks():
    inbox = sorted(SAM_INBOX.glob("task-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    outbox = sorted(SAM_OUTBOX.glob("task-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out_by_id = {p.stem.replace("task-", ""): p for p in outbox}
    items = []
    for p in inbox[:50]:
        tid = p.stem.replace("task-", "")
        result_path = out_by_id.get(tid)
        item = {
            "task_id": tid,
            "submitted_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            "inbox": p.name,
            "body": p.read_text(),
            "result": None,
        }
        if result_path:
            try:
                item["result"] = json.loads(result_path.read_text())
                item["completed_at"] = datetime.fromtimestamp(result_path.stat().st_mtime, tz=timezone.utc).isoformat()
            except Exception as e:
                item["result"] = {"error": f"failed to parse outbox: {e}"}
        items.append(item)
    return jsonify({"count": len(items), "items": items})


@app.route("/api/sam/result/<task_id>", methods=["POST"])
def api_sam_result(task_id: str):
    """Sam writes its structured result here when a task is done. Idempotent."""
    if "/" in task_id or ".." in task_id:
        return jsonify({"error": "invalid task_id"}), 400
    body = request.get_json(silent=True) or {}
    out = SAM_OUTBOX / f"task-{task_id}.json"
    out.write_text(json.dumps(body, indent=2))
    return jsonify({"status": "ok", "outbox_path": str(out)})


@app.route("/api/sam/task/<task_id>", methods=["DELETE"])
def api_sam_task_delete(task_id: str):
    """Remove a task from inbox + outbox. Operator-driven cleanup."""
    if "/" in task_id or ".." in task_id:
        return jsonify({"error": "invalid task_id"}), 400
    removed = []
    for p in (SAM_INBOX / f"task-{task_id}.md", SAM_OUTBOX / f"task-{task_id}.json"):
        if p.exists():
            p.unlink()
            removed.append(p.name)
    return jsonify({"status": "ok", "removed": removed})


# ─────────────────────────────────────────────────────────────────
# BOOT
# ─────────────────────────────────────────────────────────────────

def _start_health_thread() -> None:
    t = threading.Thread(target=_health_loop, daemon=True, name="health-monitor")
    t.start()


if __name__ == "__main__":
    if not (KRAKEN_API_KEY and KRAKEN_API_SECRET):
        log.warning("KRAKEN credentials not set — auth health check will report DOWN, kill-switch direct call will fail.")
    _start_health_thread()
    log.info(f"Aureon-Leto listening on http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False, threaded=True)
