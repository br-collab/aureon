"""
╔══════════════════════════════════════════════════════════════════════╗
║  PROJECT AUREON — The Grid 3                                         ║
║  server_railway_patch.py                                             ║
║                                                                      ║
║  RAILWAY DEPLOYMENT PATCH                                            ║
║                                                                      ║
║  Three changes required in server.py for Railway:                   ║
║                                                                      ║
║  CHANGE 1 — Port binding (already near bottom of server.py)         ║
║  CHANGE 2 — State file path (Railway filesystem is ephemeral)       ║
║  CHANGE 3 — Start function (gunicorn needs app exposed at module     ║
║             level, not wrapped in start())                           ║
║                                                                      ║
║  Apply each PATCH block below to server.py.                         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 1: Port binding
#
# FIND this in server.py start():
#   port = int(os.environ.get("AUREON_PORT", "5001"))
#
# REPLACE WITH:
#   port = int(os.environ.get("PORT", os.environ.get("AUREON_PORT", "5001")))
#
# WHY: Railway injects $PORT at runtime. Locally still falls back to 5001.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2: State file path
#
# FIND in aureon/config/settings.py (or wherever STATE_FILE is defined):
#   STATE_FILE = "aureon_state_persist.json"   (or similar)
#
# REPLACE WITH:
#   import os
#   _DATA_DIR  = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH",
#                               os.path.dirname(os.path.abspath(__file__)))
#   STATE_FILE = os.path.join(_DATA_DIR, "aureon_state_persist.json")
#   LOG_FILE   = os.path.join(_DATA_DIR, "aureon_errors.log")
#
# WHY: Railway's ephemeral filesystem resets on redeploy.
#      If you add a Railway Volume (free, persistent), mount it at /data
#      and set RAILWAY_VOLUME_MOUNT_PATH=/data in Railway env vars.
#      Without a volume, state resets on redeploy — fine for paper trade
#      crawl phase since positions are simulated.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3: Gunicorn app exposure
#
# Railway uses gunicorn which imports server.py as a module.
# The background threads (market_loop, doctrine_stack, email_scheduler)
# must start when the module loads, not only when start() is called.
#
# FIND at the BOTTOM of server.py:
#   if __name__ == "__main__":
#       start()
#
# REPLACE WITH:
#   def _start_background_threads():
#       """Start background threads once — safe for both gunicorn and direct run."""
#       import threading as _t
#       _t.Thread(target=run_doctrine_stack, daemon=True).start()
#       _t.Thread(target=market_loop, daemon=True).start()
#       _t.Thread(target=email_scheduler, daemon=True).start()
#       print("[AUREON] Background threads started")
#
#   # Start threads when module loads (gunicorn import) OR direct run
#   _start_background_threads()
#
#   if __name__ == "__main__":
#       port = int(os.environ.get("PORT", os.environ.get("AUREON_PORT", "5001")))
#       app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
#
# WHY: gunicorn calls `from server import app` — __main__ block never runs.
#      Moving thread startup to module level ensures the market loop and
#      doctrine stack fire regardless of how the server is invoked.
#      use_reloader=False prevents double-thread starts in dev mode.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 4: CORS header for Vercel frontend (add after app = Flask(...))
#
# from flask import Flask
# from flask_cors import CORS   # pip install flask-cors
# app = Flask(__name__, static_folder=THIS_DIR)
# CORS(app, origins=[
#     "https://aureon.vercel.app",      # your Vercel frontend domain
#     "http://localhost:3000",           # local frontend dev
#     "http://localhost:5001",           # local backend dev
# ])
#
# Add flask-cors to requirements.txt:
#   flask-cors>=4.0.0
#
# WHY: Vercel frontend (different domain) calling Railway backend API
#      will be blocked by browser CORS policy without this header.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT VARIABLES — set these in Railway dashboard
# Settings → Variables → Add Variable
# ─────────────────────────────────────────────────────────────────────────────
RAILWAY_ENV_VARS = """
AUREON_EMAIL=aureonfsos@gmail.com
AUREON_EMAIL_PW=<your_gmail_app_password>
FRED_API_KEY=<your_fred_api_key_optional>
RAILWAY_VOLUME_MOUNT_PATH=/data
PYTHON_VERSION=3.11.9
"""
# Do NOT put these in code or .env committed to GitHub.
# Railway injects them securely at runtime.
