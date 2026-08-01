# Thifur-H — canonical code path

**This directory is the canonical Thifur-H implementation.** It closes the consolidation
action recorded at `AUR-CANONICAL-001 v1.6 §549`, which read:

> The deployed Thifur-H lives at `aureon/thifur/thifur_h.py` and is the canonical
> implementation. A stub at `aureon/agents/hunter_killer/` exists but is not imported by
> `server.py`. Action: archive or delete the stub and document that `aureon/thifur/` is the
> canonical Thifur-H code path. Add a README to `aureon/thifur/` that names the consolidation.

**Half of that action is closed by this file.** The other half — "archive or delete the stub" —
**must not be executed as written, because it would break boot.**

`AUR-CANONICAL-001 §549` states that the stub "is not imported by `server.py`." That is true
only of the direct import path. `server.py` line 97 does `from aureon.agents import ThifurJ,
SettlementOps`, which executes `aureon/agents/__init__.py`, which does `from
aureon.agents.hunter_killer import ThifurH` at line 11. Deleting the directory raises
`ImportError` on one of the first imports at boot — the same class of failure as the Railway
502 in `1410e36`. Two further sites import it: `aureon/cli/main.py:36` and
`aureon/mcp/agents_server.py:31`, both pulling `HUNTER_KILLER_AGENTS` for registry discovery.

It is also not a stub. `aureon/agents/hunter_killer/_base.py` is 532 lines and defines `class
ThifurH(HunterKillerAgent)` at line 200 — a second, differently-shaped `ThifurH` living in the
same distribution as the one in this directory. The real finding is a **name collision inside
one package**, not a dead file:

| Symbol | Location | Role |
| --- | --- | --- |
| `aureon.thifur.thifur_h.ThifurH` | here | Session engine. What `server.py` runs and what the eleven `/api/thifur-h/*` routes drive. **Canonical.** |
| `aureon.agents.ThifurH` | `aureon/agents/hunter_killer/_base.py:200` | Agent-framework class, exported through `aureon.agents.__all__` and surfaced in the CLI and MCP agent registries. Imported at boot; not exercised for execution. |

**Retirement sequence, in order.** Disambiguate first: either rename the agent-framework class
or drop it from `aureon.agents.__all__` and repoint `cli/main.py` and `mcp/agents_server.py`.
Only once nothing imports the directory can it be removed. Doing it in the other order is a
boot failure, and the fact that the canonical prescribes the other order is recorded in
`Atreides Inventory 312350Z §IV` as a doctrine finding rather than silently worked around.

Until then: `server.py` runs **this** implementation. If you are adding Thifur-H behaviour, add
it here.

---

## Activation state — read before describing this agent to anyone

Thifur-H is **two-state**, and the two states are governed independently
(`AUR-CANONICAL-001 v1.6 §II`).

**Advisory mode — ACTIVE in deployment.** Signal surfacing, gate validation, session-bounded
execution under explicit per-signal operator approval (CAOM-001 human-in-the-loop), and DSOR
write-through against the live Kraken account in the Leto operator console. Every advisory-mode
action that opens a position requires explicit operator approval before it reaches the exchange.

**Autonomous mode — DECLARED, NOT ACTIVATED.** The continuous optimization surface — VWAP,
TWAP and POV strategy selection, autonomous collateral optimization, autonomous FX hedging
within the risk envelope — is architecturally specified and not enabled. Activation *per
domain* requires independent SR 11-7 Tier 1 validation, EU AI Act high-risk system EU database
registration, and a formal doctrine amendment recorded in the version log.

Do **not** describe Thifur-H as "declared, not activated" without qualification. That was the
v1.1 rendering; v1.6 §II replaced it because it was inconsistent with the deployed Kraken
integration. Advisory is live. Autonomous is not.

---

## Nothing here learns

This is a property worth defending, not an omission.

`atrox_live.py` runs a fixed rule set with operator-specified, doctrine-bounded constants:

| Constant | Value | Meaning |
| --- | --- | --- |
| `LOOP_INTERVAL_SEC` | 300 | 5-minute cadence |
| `LOOKBACK_CANDLES` | 12 | 1-hour rolling high |
| `BUY_TRIGGER_DROP_PCT` | 0.003 | 0.3% drop from recent high |
| `SELL_TRIGGER_GAIN_PCT` | 0.005 | 0.5% above entry |
| `STOP_TRIGGER_LOSS_PCT` | 0.003 | 0.3% below entry |

No module in this directory fits, trains, calibrates against outcomes, or feeds realised P&L
back into a threshold. The decision function changes when a human edits a constant and records
why. That is what keeps SR 11-7 ongoing-monitoring and independent-validation obligations
tractable, and it is what makes any given session deterministically replayable from its DSOR
record. Introducing an outcome-driven parameter update here is a doctrine event, not a
refactor.

---

## Modules

| File | Role |
| --- | --- |
| `thifur_h.py` | Session engine, gates, ledger, doctrine bindings. The entry point. |
| `agent_h.py` | Agent-level wrapper and SR 11-7 Tier 1 framing. |
| `atrox_live.py` | Live signal generator — 5-minute XBTUSD loop on the Railway worker. Dormant unless a session is ACTIVE. |
| `atrox_sandbox.py` | Sandbox signal generator for non-live sessions. |
| `kraken_client.py` | Exchange client and the live doctrine variant (`ThifurHDoctrineLive`). |

## Operator surface

Eleven routes in `server.py`: `session/start`, `signal`, `approve`, `rollback`,
`kill-switch`, `session`, `session/state` (`/state`), `dsor`, `balance`, `auto-close/arm`,
`auto-close/disarm`. `approve` is the CAOM-001 gate — signals stage there and go no
further without it. `kill-switch` cancels every open order and halts the session; Level 2
suspension (`AUR-CANONICAL-001` §429) cancels all Thifur-H and Thifur-J orders across all
domains within five seconds, and any Tier 2 authority can trigger it.

Session state persists to `$RAILWAY_VOLUME_MOUNT_PATH/thifur_h_state.json`.

## Explainability

`AUR-CANONICAL-001 v1.6 §206`: every Thifur-H action, advisory or autonomous, must be
explainable in human-readable terms *before* execution. If it cannot be explained, it does not
execute. This is the EU AI Act high-risk requirement applied architecturally rather than
compliance-theatrically, and it constrains what may be added to this directory.

---

*Project Aureon · canonical code path record · DTG 312350Z JUL 26*
