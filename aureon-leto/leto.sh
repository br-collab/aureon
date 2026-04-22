#!/bin/bash
# Aureon-Leto local supervisor.
#
# Subcommands:
#   start   — launch Leto in the background (nohup), capture stdout/stderr
#             to logs/leto_<ts>.log, write PID to .leto.pid. Idempotent:
#             refuses to start a second copy if one is already running.
#   stop    — SIGTERM the tracked PID, SIGKILL fallback, clear .leto.pid.
#   status  — report whether Leto is running + etime/rss/command.
#   logs    — tail -f the most recent log file.
#   adopt   — associate an already-running PID with .leto.pid (used when
#             Leto was launched manually and you want the supervisor to
#             take over without restarting it).
#
# WHY THIS EXISTS: start.sh runs Leto in the foreground (exec python3).
# That ties the process lifetime to the launching terminal — close the
# tab, sleep the Mac, switch WiFi, and SIGHUP takes Leto down. This
# supervisor detaches Leto from the terminal via nohup so those events
# no longer kill it.

set -e
cd "$(dirname "$0")"

PID_FILE=".leto.pid"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

_alive() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid="$(cat "$PID_FILE" 2>/dev/null)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi
    return 1
}

cmd="${1:-status}"

case "$cmd" in
    start)
        if pid="$(_alive)"; then
            echo "Leto already running — pid $pid"
            exit 0
        fi
        log_file="$LOG_DIR/leto_$(date -u +%Y%m%dT%H%M%SZ).log"
        nohup ./start.sh > "$log_file" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 2
        if pid="$(_alive)"; then
            echo "Leto started — pid $pid"
            echo "  log: $log_file"
            echo "  url: http://127.0.0.1:${CONSOLE_PORT:-5002}"
        else
            echo "ERROR: Leto failed to start — tail of $log_file:"
            tail -20 "$log_file" 2>/dev/null || true
            rm -f "$PID_FILE"
            exit 1
        fi
        ;;
    stop)
        if pid="$(_alive)"; then
            kill "$pid" 2>/dev/null || true
            for _ in 1 2 3 4 5; do
                if ! kill -0 "$pid" 2>/dev/null; then
                    break
                fi
                sleep 1
            done
            if kill -0 "$pid" 2>/dev/null; then
                echo "SIGTERM ignored; sending SIGKILL to pid $pid"
                kill -9 "$pid" 2>/dev/null || true
            fi
            rm -f "$PID_FILE"
            echo "Leto stopped (was pid $pid)"
        else
            echo "Leto not running"
            rm -f "$PID_FILE"
        fi
        ;;
    status)
        if pid="$(_alive)"; then
            echo "Leto RUNNING — pid $pid"
            ps -p "$pid" -o pid,etime,rss,command 2>/dev/null | tail -n +1
        else
            echo "Leto NOT RUNNING"
            [ -f "$PID_FILE" ] && echo "(stale $PID_FILE present — removing)" && rm -f "$PID_FILE"
            exit 1
        fi
        ;;
    logs)
        latest="$(ls -t "$LOG_DIR"/leto_*.log 2>/dev/null | head -1)"
        if [ -z "$latest" ]; then
            echo "No logs yet in $LOG_DIR/"
            exit 1
        fi
        echo "Tailing $latest (Ctrl+C to stop)"
        echo "---"
        tail -f "$latest"
        ;;
    adopt)
        pid_arg="$2"
        if [ -z "$pid_arg" ]; then
            echo "usage: leto.sh adopt <pid>"
            exit 1
        fi
        if ! kill -0 "$pid_arg" 2>/dev/null; then
            echo "ERROR: pid $pid_arg is not running"
            exit 1
        fi
        echo "$pid_arg" > "$PID_FILE"
        echo "Adopted pid $pid_arg into $PID_FILE"
        ;;
    *)
        echo "usage: leto.sh {start|stop|status|logs|adopt <pid>}"
        exit 1
        ;;
esac
