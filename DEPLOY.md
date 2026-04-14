# Project Aureon — Deployment Guide
## Railway (Backend) + Vercel (Frontend) — Crawl Phase

---

## Architecture

```
Browser → Vercel (index.html, static dashboard)
             ↓ /api/* proxied to Railway
         Railway (Flask + market_loop + doctrine stack, persistent)
```

Railway runs continuously — market loop ticks every 5s, paper trades accumulate.
Vercel serves the dashboard — free, global CDN, auto-deploys on git push.

---

## Step 1 — Add deployment files to your repo

Copy these four files into the ROOT of your GitHub repo (same level as server.py):

- `railway.json`
- `requirements.txt`  ← replace existing if one exists
- `Procfile`
- `runtime.txt`

Commit and push to main.

```bash
git add railway.json requirements.txt Procfile runtime.txt
git commit -m "Add Railway deployment config"
git push origin main
```

---

## Step 2 — Apply server.py patches

Apply the four patches from `server_railway_patch.py` to server.py:

**Patch 1** — Port binding (5 seconds):
```python
# FIND:
port = int(os.environ.get("AUREON_PORT", "5001"))
# REPLACE:
port = int(os.environ.get("PORT", os.environ.get("AUREON_PORT", "5001")))
```

**Patch 2** — State file path. Open `aureon/config/settings.py` and update
STATE_FILE and LOG_FILE to use RAILWAY_VOLUME_MOUNT_PATH env var.

**Patch 3** — Background thread startup. Replace the `if __name__ == "__main__":`
block at the bottom of server.py per the patch file instructions.

**Patch 4** — Add flask-cors to requirements.txt and add CORS(app) after
`app = Flask(...)`.

Commit patches:
```bash
git add server.py aureon/config/settings.py requirements.txt
git commit -m "Railway compatibility patches"
git push origin main
```

---

## Step 3 — Create Railway account and deploy

1. Go to https://railway.app
2. Sign up with GitHub (use the same account that owns br-collab/aureon)
3. Click **New Project** → **Deploy from GitHub repo**
4. Select **br-collab/aureon** (Railway will request private repo access — grant it)
5. Railway detects `railway.json` and `Procfile` automatically
6. Click **Deploy** — build takes ~2 minutes

---

## Step 4 — Set environment variables in Railway

Railway Dashboard → Your Project → Variables → Add:

| Variable | Value |
|----------|-------|
| `AUREON_EMAIL` | aureonfsos@gmail.com |
| `AUREON_EMAIL_PW` | your Gmail app password |
| `FRED_API_KEY` | your FRED key (optional) |
| `RAILWAY_VOLUME_MOUNT_PATH` | /data |
| `PYTHON_VERSION` | 3.11.9 |

Railway redeploys automatically after saving variables.

---

## Step 5 — Add a Railway Volume (persistent state)

Without a volume, `aureon_state_persist.json` resets on every redeploy.
For the paper trade crawl phase you want positions to persist.

Railway Dashboard → Your Project → **+ New** → **Volume**
- Mount path: `/data`
- Size: 1GB (free tier)

Railway automatically injects `RAILWAY_VOLUME_MOUNT_PATH=/data`.
Your state file now survives redeploys.

---

## Step 6 — Get your Railway URL

Railway Dashboard → Your Project → Settings → **Domains**
- Click **Generate Domain** → Railway gives you:
  `https://aureon-production.up.railway.app`
  (or similar — copy the exact URL)

Test it:
```
https://aureon-production.up.railway.app/api/snapshot
```
You should see the Aureon JSON snapshot. Paper trades are live.

---

## Step 7 — Deploy Vercel frontend

**Update vercel.json first:**
Replace `https://aureon-production.up.railway.app` with your actual Railway URL
in two places in `vercel.json`.

1. Go to https://vercel.com
2. Sign up with GitHub (same account)
3. Click **Add New Project** → Import `br-collab/aureon`
4. Framework Preset: **Other**
5. Root Directory: `.` (repo root)
6. Click **Deploy**

Vercel builds in ~30 seconds. You get:
`https://aureon-xxxx.vercel.app`

---

## Step 8 — Update CORS in server.py

Replace the placeholder Vercel URL in the CORS config with your actual URL:
```python
CORS(app, origins=[
    "https://aureon-xxxx.vercel.app",   # ← your actual Vercel URL
    "http://localhost:3000",
    "http://localhost:5001",
])
```
Commit and push — Railway redeploys automatically.

---

## What you have after Step 8

| Component | Status |
|-----------|--------|
| Railway backend | Running 24/7 — market loop, paper trades, doctrine stack |
| State persistence | Survives redeploys via Railway Volume |
| Vercel dashboard | Auto-deploys on every git push to main |
| Paper trade data | Accumulating — positions, P&L, decisions, compliance alerts |
| Email reports | Pre-market briefing, EOD digest, weekly P&L hitting your inbox |
| API endpoints | `/api/snapshot`, `/api/portfolio`, `/api/decisions`, etc. |

---

## Crawl Phase Data Collection

Once live, Railway collects:
- Paper trade signal quality (Thifur-H REBALANCE vs OPPORTUNISTIC)
- Approval latency (time from signal to human decision)
- Drawdown behavior under simulated market conditions
- Compliance alert frequency and type
- Doctrine version stability across market cycles
- C2 handoff log and unified lineage records (once patch is applied)

This is the testbed data that feeds the Walk phase positioning.

---

## Troubleshooting

**Build fails:** Check Railway build logs. Most common issue is a missing
dependency in requirements.txt. Add it and push.

**App crashes on start:** Check Railway deploy logs for import errors.
Usually a missing `aureon/` module or settings.py path issue.

**CORS error in browser:** Vercel URL not in the CORS allowlist in server.py.
Update and redeploy.

**State resets on redeploy:** Volume not mounted. Check
RAILWAY_VOLUME_MOUNT_PATH is set and Volume is attached to the project.

**Email not sending:** AUREON_EMAIL_PW must be a Gmail App Password,
not your Gmail account password. Generate one at:
https://myaccount.google.com/apppasswords

---

*Project Aureon · Guillermo "Bill" Ravelo · Columbia University MS Technology Management*
*Crawl Phase — Paper Trade Data Collection · Railway + Vercel*
