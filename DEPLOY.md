# Project Aureon — deployment

How the service is deployed, what it needs, and how to change or rebuild it.

This describes the deployment **as it stands**. It is not a migration guide: the
Railway service exists, the configuration files are committed, and the patches
the previous version of this document told you to apply were applied long ago.
The [history](#history) section at the end says what changed and when.

Acronyms on first use: SMTP = Simple Mail Transfer Protocol. OFR = Office of
Financial Research. MCP = Model Context Protocol. DSOR = Decision System of Record.

---

## What runs where

```
Browser ──► Railway service (Flask + gunicorn)
              ├─ serves index.html and the cockpit dashboard
              ├─ /api/*            the governed surface
              ├─ /mcp              Model Context Protocol endpoint (read-only by default)
              └─ background threads: market loop, Atrox refresh, scheduled reports
                      │
                      └─► Railway volume at /data — persisted state
```

**One service, one worker.** `gunicorn.conf.py` starts the background threads in
`post_fork`, so they begin only after gunicorn is bound and serving. The worker
count is 1 deliberately: the market loop, the Atrox refresh and the in-memory
state are per process, and a second worker would run a second copy of each.

`vercel.json` is committed and configures a static frontend that proxies `/api/*`
to Railway. **The live dashboard is served by Flask from the Railway service**,
not from Vercel. Treat `vercel.json` as an available alternative rather than a
description of what is running.

## The configuration files, and what each one decides

| File | What it sets |
|---|---|
| `railway.json` | Builder **NIXPACKS**; the gunicorn start command; health check `/api/snapshot` with a 30-second timeout; restart `ON_FAILURE`, up to 3 retries |
| `Procfile` | The same gunicorn line, for any platform that reads a Procfile rather than `railway.json` |
| `runtime.txt` | `python-3.11.9` |
| `requirements.txt` | **What the build installs.** Nixpacks reads this file |
| `requirements.lock.txt` | **Not installed by the deploy.** It is the pinned set CI resolves against, so tests run on a fixed dependency set. `scripts/compile_lock.py` generates it |
| `gunicorn.conf.py` | A 120-second worker timeout (XRPL work in the request path can take ~60s) and the `post_fork` hook that starts the background threads |

**Changing a dependency:** edit `requirements.txt`, then run
`python scripts/compile_lock.py` and commit both. CI fails if they disagree.

## Environment variables

Set in Railway → the service → **Variables**. Railway redeploys on save.

### Required for the service to be usable

| Variable | Without it |
|---|---|
| `AUREON_ADMIN_KEY` | **Every authority mutation is refused with 403.** Approving or rejecting a decision, opening the session, doctrine, MMF, Atrox promote and dismiss, the cockpit steps, halt and resume — all of it fails closed. The dashboard will prompt for the key and then be told no key is configured |
| `FRED_API_KEY` | The systemic-stress reading falls back to fixed constants. Since W2B-3 that is recorded as `FABRICATED_DEFAULT`, the pre-trade gate returns `INDETERMINATE`, and **every approval is refused**. This is intended — an absent reading must not read as clear — but it means an unset key stops trading, not just monitoring |
| `RAILWAY_VOLUME_MOUNT_PATH` | Injected automatically when a volume is attached (`/data`). Without a volume, state resets on every redeploy: positions, trades, the authority log, **and pending decisions** (AUR-I-17) |

### Shapes behaviour

| Variable | Effect |
|---|---|
| `TWELVE_DATA_API_KEY` | Primary market-data feed. Unset, prices come from yfinance, and when that is unreachable from a random walk. Since W2-ADD-03 each fill records which, and a simulated price is labelled as one rather than passing as a market fact |
| `AUREON_EMAIL`, `AUREON_EMAIL_PW`, `AUREON_EMAIL_RECIPIENT` | Gmail SMTP for scheduled reports and trade confirmations. `AUREON_EMAIL_PW` is an app password, not the account password |
| `KRAKEN_API_KEY`, `KRAKEN_API_SECRET` | The Thifur-H live path. Absent, that path has no exchange |
| `ALPACA_API_KEY`, `ALPACA_API_SECRET` | The Alpaca data pipe |
| `AUREON_MCP_WRITE_ENABLED` | **Leave unset.** `true` registers the MCP approval tool, which lets an MCP client approve a decision. Agents never authorize (charter §7, JUM-D-07); this exists for a human who deliberately turns it on for a session |
| `AUREON_ENV`, `AUREON_PORT` | Local development only. Railway supplies `PORT` |

**Rotating `AUREON_ADMIN_KEY`** takes effect on the redeploy that follows the
save. Anyone mid-session on the dashboard is prompted again on their next
authority action.

## Deploying

Merging to `main` deploys. There is no separate release step, so **a merge is a
production deploy** and the pull request that precedes it should say what an
operator will see change.

After a deploy:

1. `GET /api/snapshot` returns 200 and carries `deploy_sha`. That value is the
   merge commit now serving traffic — check it rather than assuming.
2. During the container swap the endpoint may briefly answer without a
   `deploy_sha` field at all. That is the old container going away, not a
   regression. Read it again.
3. The session protocol auto-completes at boot; `GET /api/session/status`
   should report `OPEN`.

## Recreating the service

If the Railway service is lost, this is what to recreate, in order:

1. New project → deploy from GitHub → `br-collab/aureon`, branch `main`. Railway
   reads `railway.json`, so the builder, start command and health check come with
   the repository.
2. Attach a **volume** mounted at `/data` before the first real use, or state will
   not survive a redeploy.
3. Set the variables above, at minimum `AUREON_ADMIN_KEY`, `FRED_API_KEY` and the
   mail credentials.
4. Generate a domain under **Networking**.
5. Confirm `/api/snapshot` is 200, `deploy_sha` matches the commit you deployed,
   and the build log shows `atreides` and `cannae-kernel` installed from their
   pinned tags.

## History

- **Sep 2026 —** this document was rewritten. The previous version was the
  original migration narrative: copy four files in, apply four patches to
  `server.py`, create the Railway project, then deploy a Vercel frontend. All of
  that had been done; the files and patches are in the repository. It also
  omitted `AUREON_ADMIN_KEY`, so following it produced a service where every
  approval returned 403.
- **Sep 2026 —** `requirements.lock.txt` stopped being described as mirroring
  what Railway installs. It never did: Nixpacks installs `requirements.txt`.
- **Apr 2026 —** initial Railway deployment.
