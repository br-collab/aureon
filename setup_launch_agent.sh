#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# PROJECT AUREON — macOS Launch Agent Installer
# ─────────────────────────────────────────────────────────────────
# Run once from Terminal:
#   cd "/path/to/The Grid 3"
#   bash setup_launch_agent.sh
#
# This script:
#   1. Auto-detects the Grid 3 directory and python3 path
#   2. Writes ~/Library/LaunchAgents/com.aureon.gridserver.plist
#   3. Loads the agent so Aureon starts immediately
#   4. Aureon will now auto-start at every login and restart on crash
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Resolve paths ────────────────────────────────────────────────
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SERVER_PY="$SCRIPT_DIR/server.py"
PYTHON_BIN="$(which python3)"
PLIST_LABEL="com.aureon.gridserver"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_OUT="$SCRIPT_DIR/aureon.log"
LOG_ERR="$SCRIPT_DIR/aureon_error.log"

# ── Pre-flight checks ────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║        AUREON LAUNCH AGENT INSTALLER             ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo ""

if [ ! -f "$SERVER_PY" ]; then
  echo "  ✗ ERROR: server.py not found at $SERVER_PY"
  echo "    Make sure you run this script from The Grid 3 folder."
  exit 1
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "  ✗ ERROR: python3 not found in PATH."
  exit 1
fi

echo "  • Grid 3 folder : $SCRIPT_DIR"
echo "  • python3       : $PYTHON_BIN"
echo "  • Plist target  : $PLIST_PATH"
echo "  • Log output    : $LOG_OUT"
echo "  • Log errors    : $LOG_ERR"
echo ""

# ── Unload existing agent if already installed ───────────────────
if launchctl list | grep -q "$PLIST_LABEL" 2>/dev/null; then
  echo "  → Unloading existing Aureon agent..."
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi

# ── Write the plist ──────────────────────────────────────────────
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>

  <!-- Identity -->
  <key>Label</key>
  <string>${PLIST_LABEL}</string>

  <!-- Command to run -->
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${SERVER_PY}</string>
  </array>

  <!-- Working directory (so .env and relative paths resolve) -->
  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>

  <!-- Start automatically at login -->
  <key>RunAtLoad</key>
  <true/>

  <!-- Restart automatically if it crashes -->
  <key>KeepAlive</key>
  <true/>

  <!-- Throttle restarts — wait 10s before restarting after crash -->
  <key>ThrottleInterval</key>
  <integer>10</integer>

  <!-- Logging -->
  <key>StandardOutPath</key>
  <string>${LOG_OUT}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_ERR}</string>

  <!-- Run as current user (not root) -->
  <key>UserName</key>
  <string>$(whoami)</string>

</dict>
</plist>
PLIST

echo "  ✓ Plist written."

# ── Load the agent ───────────────────────────────────────────────
launchctl load "$PLIST_PATH"
echo "  ✓ Agent loaded — Aureon is now running."
echo ""

# ── Status check ─────────────────────────────────────────────────
sleep 2
if launchctl list | grep -q "$PLIST_LABEL"; then
  PID=$(launchctl list | grep "$PLIST_LABEL" | awk '{print $1}')
  echo "  ✓ STATUS: Running (PID $PID)"
else
  echo "  ✗ Agent loaded but process not detected."
  echo "    Check $LOG_ERR for errors."
fi

echo ""
echo "  ─────────────────────────────────────────────────"
echo "  Aureon will now:"
echo "    • Start automatically every time you log in"
echo "    • Restart automatically if it ever crashes"
echo "    • Log output to: aureon.log"
echo "    • Log errors to: aureon_error.log"
echo ""
echo "  Useful commands:"
echo "    Stop:    launchctl unload ~/Library/LaunchAgents/com.aureon.gridserver.plist"
echo "    Start:   launchctl load   ~/Library/LaunchAgents/com.aureon.gridserver.plist"
echo "    Logs:    tail -f \"$LOG_OUT\""
echo "    Errors:  tail -f \"$LOG_ERR\""
echo "  ─────────────────────────────────────────────────"
echo ""
