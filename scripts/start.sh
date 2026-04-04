#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install flask yfinance reportlab python-dotenv

# Allow local runs on a non-default port without changing code.
PORT="${AUREON_PORT:-5001}"
export AUREON_PORT="$PORT"
exec python server.py
