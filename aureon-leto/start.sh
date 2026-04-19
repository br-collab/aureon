#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "ERROR: aureon-leto/.env missing."
    echo "Copy .env.example to .env and fill in KRAKEN_API_KEY / KRAKEN_API_SECRET."
    exit 1
fi

mkdir -p dsor_archive sam_inbox sam_outbox

PORT="${CONSOLE_PORT:-5002}"
echo "Aureon-Leto — CAOM-001 Operator Console — booting on port ${PORT}"
echo "URL: http://127.0.0.1:${PORT}"
echo "---"
exec python3 server.py
