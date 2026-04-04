import os
_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
_DATA_DIR  = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", _REPO_ROOT)
STATE_FILE = os.path.join(_DATA_DIR, "aureon_state_persist.json")
LOG_FILE   = os.path.join(_DATA_DIR, "aureon_errors.log")
IS_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT"))
IS_PRODUCTION = IS_RAILWAY or os.environ.get("AUREON_ENV") == "production"
if IS_RAILWAY:
    print(f"[AUREON] Railway environment — state: {STATE_FILE}")
else:
    print(f"[AUREON] Local environment — state: {STATE_FILE}")
