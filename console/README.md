# CAOM-001 Operator Console

Local single-pane-of-glass for everything the operator and Sam (Claude Code) execute against The Grid 3 production stack.

Runs on **port 5002** (configurable). Bind is `127.0.0.1` only — not exposed to the network.

```
CAOM-001 Operator Console (local, port 5002)
          │
          ├── Railway Production API   (Thifur-H routes, snapshot, portfolio)
          ├── Kraken Pro API (direct)  (balance, kill-switch fallback, order history)
          ├── Sam (Claude Code)        (file-queue bridge: sam_inbox/ + sam_outbox/)
          ├── GitHub                   (commit health, repo pings)
          ├── Vercel / Twelve Data     (HTTP pings, optional)
          └── DSOR Archive (local)     (mirror of every /api/dsor/live response)
```

---

## Boot

```bash
cd console
cp .env.example .env       # then edit .env and add KRAKEN_API_KEY / KRAKEN_API_SECRET
chmod +x start.sh
./start.sh
```

Open **http://127.0.0.1:5002** in your browser.

The console has zero external pip dependencies beyond Flask itself. Standard library only: `urllib`, `hashlib`, `hmac`, `base64`, `json`, `threading`, `queue`, `pathlib`.

---

## Four panels + health bar

| Panel | What it shows |
|---|---|
| **Mission Status** | Cycle, doctrine, portfolio, P&L, market, alerts, session state. Polls Railway `/api/snapshot` every 5s. |
| **System Health** | 7 dependencies in 3 tiers, with latency and last-OK time. Pushed via SSE on every check (default 30s). |
| **Thifur-H · HITL Console** | Open session, generate signal, APPROVE/DECLINE pending signal, view live gate state. |
| **DSOR · Audit Trail** | Decision-system-of-record entries for the active session. Refresh, download, browse local archive. |
| **Session Ledger** | Counters and SR 11-7 evidence summary for the active session. |
| **Sam · Command Surface** | File-queue bridge to your Claude Code session (see below). |
| **Kill switch (footer)** | Always enabled. Calls Kraken **directly**, bypasses Railway. Notifies Railway after if reachable. |

---

## Health monitor

Three tiers, polled every 30s in a background thread, broadcast to the UI via SSE.

| Tier | Dependency | Probe | If DOWN |
|---|---|---|---|
| 1 | Railway Prod | `/api/snapshot` < 500ms | Stale-state read-only mode; trading actions blocked |
| 1 | Kraken REST | `/0/public/Time` | Trading halted, **circuit OPEN** |
| 1 | Kraken Auth | `/0/private/Balance` (signed) | Trading halted, **circuit OPEN** |
| 2 | GitHub | `api.github.com/repos/...` | Informational; doesn't block trading |
| 2 | Vercel | HTTP ping (if `VERCEL_URL` set) | Informational |
| 3 | Twelve Data | `api_usage` (if key set) | Informational |
| 3 | DSOR Archive | local write probe | DSOR mirroring fails silently to log |

### Circuit breaker

If a Tier-1 Kraken dependency transitions UP → DOWN, the circuit trips OPEN. While open:

- `/api/thifur/start`, `/signal`, `/approve`, `/rollback` all return HTTP 423.
- Banner shows "Circuit OPEN — re-arm required."
- **Kill-switch stays enabled** (it talks to Kraken directly, not Railway).

When Kraken comes back UP, the circuit does **not** auto-close. Operator must hit `RE-ARM CIRCUIT` in the UI (or `POST /api/circuit/rearm`). Re-arm fails if Kraken is still not UP.

This matches doctrine: no automatic resume into live trading after an exchange disconnect.

---

## Sam command-surface workflow (file-queue bridge)

The console doesn't have a direct hook into your Claude Code session. The bridge is a file queue:

1. **Operator submits a task** via the UI input box.
2. Console writes `console/sam_inbox/task-<timestamp>-<rand>.md`.
3. UI shows a popup with the inbox path. Operator pastes that path into Claude Code chat.
4. **Sam (Claude Code) reads** the inbox file, executes the task, and writes a result JSON to `console/sam_outbox/task-<task_id>.json` via `POST /api/sam/result/<task_id>`.
5. Console polls `/api/sam/tasks` every 5s. Pending → complete state visible in the UI.

Inbox file format:

```markdown
# Task <task_id>

Submitted: <iso ts>
Status: pending

## Body

<operator's task text>
```

Outbox file format (Sam's structured response):

```json
{
  "status": "complete",
  "summary": "...",
  "actions_taken": [{"type": "commit", "sha": "abc1234", "message": "..."}],
  "follow_ups": []
}
```

Sam shape can evolve. UI currently just renders the JSON; richer schema-aware rendering can come later.

---

## Kill switch — architectural note

The kill switch in the bottom-right is the **only** UI action that:

- Always stays enabled regardless of health monitor state
- Calls Kraken **directly** from the local console (not via Railway)
- Also notifies Railway if Railway is up, so the session ledger stays consistent

That preserves the operator's last-resort control even if Railway is down with positions open. The local console must therefore have its own copy of `KRAKEN_API_KEY` / `KRAKEN_API_SECRET` in `console/.env`.

---

## Endpoint reference (local API)

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Serves `index.html` |
| `/api/health` | GET | Current dep snapshot + circuit state + `trading_blocked` reason |
| `/api/health/stream` | GET | SSE stream of health updates |
| `/api/circuit/rearm` | POST | Operator-initiated circuit re-arm |
| `/api/snapshot` | GET | Railway snapshot proxy with stale-cache fallback |
| `/api/thifur/session` | GET | Railway `/api/thifur-h/session` proxy |
| `/api/thifur/start` | POST | Gated proxy to `/api/thifur-h/session/start` |
| `/api/thifur/signal` | POST | Gated proxy to `/api/thifur-h/signal` |
| `/api/thifur/approve` | POST | Gated proxy to `/api/thifur-h/approve` |
| `/api/thifur/rollback` | POST | Gated proxy to `/api/thifur-h/rollback` |
| `/api/thifur/kill` | POST | Direct Kraken `CancelAll` + Railway notify |
| `/api/dsor/live` | GET | Railway `/api/thifur-h/dsor` proxy + auto-archive |
| `/api/dsor/archive` | GET | List of locally archived DSOR snapshots |
| `/api/dsor/archive/<name>` | GET | Fetch one archived snapshot |
| `/api/sam/task` | POST | Queue a new task to `sam_inbox/` |
| `/api/sam/tasks` | GET | List inbox/outbox state |
| `/api/sam/result/<task_id>` | POST | Sam writes structured result here |

---

## What's gitignored

`console/.env`, `console/dsor_archive/`, `console/sam_inbox/`, `console/sam_outbox/`, `*.pyc`, `__pycache__/`, `console/console.log`.

Operational state (real Kraken keys, raw DSOR exports, task queues) stays out of the repo.
