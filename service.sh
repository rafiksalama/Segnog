#!/usr/bin/env bash
#
# Agent Memory Service — start / stop / restart / status
#
# Usage:
#   ./service.sh start     Start backends + memory service
#   ./service.sh stop      Stop memory service + backends
#   ./service.sh restart   Stop then start
#   ./service.sh status    Show status of all components
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$SCRIPT_DIR/.service.pid"
LOGFILE="$SCRIPT_DIR/.service.log"

# Ports
DRAGONFLY_PORT=6381
FALKORDB_PORT=6380
GRPC_PORT=50051
REST_PORT=9000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_log() { echo "$(date '+%H:%M:%S')  $*"; }

_pid_alive() {
    [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

_wait_for_port() {
    local port=$1 name=$2 retries=${3:-30}
    local i=0
    while ! lsof -i :"$port" -sTCP:LISTEN >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -ge "$retries" ]; then
            _log "ERROR: $name did not start on :$port after ${retries}s"
            return 1
        fi
        sleep 1
    done
    _log "$name ready on :$port"
}

_wait_for_health() {
    local retries=${1:-30} i=0
    while ! curl -sf http://localhost:$REST_PORT/health >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -ge "$retries" ]; then
            _log "ERROR: REST health check failed after ${retries}s"
            return 1
        fi
        sleep 1
    done
}

# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

do_start() {
    if _pid_alive; then
        _log "Memory service already running (PID $(cat "$PIDFILE"))"
        return 0
    fi

    _log "Starting backends..."

    # Start DragonflyDB if not running
    if ! docker ps --format '{{.Names}}' | grep -q '^dragonfly$'; then
        docker run -d --name dragonfly \
            -p ${DRAGONFLY_PORT}:6379 \
            --health-cmd "redis-cli ping" \
            --health-interval 5s \
            --health-timeout 3s \
            --health-retries 3 \
            docker.dragonflydb.io/dragonflydb/dragonfly:latest >/dev/null 2>&1 \
        || docker start dragonfly >/dev/null 2>&1
        _log "DragonflyDB starting..."
    else
        _log "DragonflyDB already running"
    fi

    # Start FalkorDB if not running
    if ! docker ps --format '{{.Names}}' | grep -q '^falkordb$'; then
        docker run -d --name falkordb \
            -p ${FALKORDB_PORT}:6379 \
            -p 3001:3000 \
            -p 7687:7687 \
            --health-cmd "redis-cli ping" \
            --health-interval 5s \
            --health-timeout 3s \
            --health-retries 3 \
            falkordb/falkordb:latest >/dev/null 2>&1 \
        || docker start falkordb >/dev/null 2>&1
        _log "FalkorDB starting..."
    else
        _log "FalkorDB already running"
    fi

    # Wait for backends
    _wait_for_port $DRAGONFLY_PORT "DragonflyDB"
    _wait_for_port $FALKORDB_PORT "FalkorDB"

    _log "Starting memory service..."

    # Start the Python service in the background
    cd "$SCRIPT_DIR"
    export PYTHONPATH="$SCRIPT_DIR/src:$SCRIPT_DIR/client${PYTHONPATH:+:$PYTHONPATH}"
    nohup python -m memory_service.main > "$LOGFILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PIDFILE"

    # Wait for both servers to come up
    _wait_for_port $GRPC_PORT "gRPC" 30
    _wait_for_health 30

    _log "Memory service started (PID $pid)"
    _log "  gRPC  → localhost:$GRPC_PORT"
    _log "  REST  → localhost:$REST_PORT"
    _log "  Logs  → $LOGFILE"
}

# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

do_stop() {
    # Stop memory service
    if _pid_alive; then
        local pid
        pid=$(cat "$PIDFILE")
        _log "Stopping memory service (PID $pid)..."
        kill "$pid" 2>/dev/null || true
        # Wait for graceful shutdown
        local i=0
        while kill -0 "$pid" 2>/dev/null; do
            i=$((i + 1))
            if [ "$i" -ge 10 ]; then
                _log "Force killing PID $pid"
                kill -9 "$pid" 2>/dev/null || true
                break
            fi
            sleep 1
        done
        rm -f "$PIDFILE"
        _log "Memory service stopped"
    else
        # Check for orphan processes on our ports
        local orphan
        orphan=$(lsof -ti :$GRPC_PORT -sTCP:LISTEN 2>/dev/null || true)
        if [ -n "$orphan" ]; then
            _log "Stopping orphan process on :$GRPC_PORT (PID $orphan)..."
            kill "$orphan" 2>/dev/null || true
            sleep 2
            kill -9 "$orphan" 2>/dev/null || true
        fi
        rm -f "$PIDFILE"
        _log "Memory service not running"
    fi

    # Stop backends
    for name in falkordb dragonfly; do
        if docker ps --format '{{.Names}}' | grep -q "^${name}$"; then
            _log "Stopping $name..."
            docker stop "$name" >/dev/null 2>&1
        fi
    done

    _log "All services stopped"
}

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

do_status() {
    echo ""
    echo "  Component          Status         Port"
    echo "  ─────────────────  ─────────────  ─────"

    # DragonflyDB
    if docker ps --format '{{.Names}}' | grep -q '^dragonfly$'; then
        local df_status
        df_status=$(docker inspect --format='{{.State.Health.Status}}' dragonfly 2>/dev/null || echo "up")
        printf "  DragonflyDB        %-13s  :%s\n" "$df_status" "$DRAGONFLY_PORT"
    else
        printf "  DragonflyDB        %-13s  :%s\n" "stopped" "$DRAGONFLY_PORT"
    fi

    # FalkorDB
    if docker ps --format '{{.Names}}' | grep -q '^falkordb$'; then
        printf "  FalkorDB           %-13s  :%s\n" "running" "$FALKORDB_PORT"
    else
        printf "  FalkorDB           %-13s  :%s\n" "stopped" "$FALKORDB_PORT"
    fi

    # Memory Service
    if _pid_alive; then
        local pid
        pid=$(cat "$PIDFILE")
        printf "  Memory (gRPC)      %-13s  :%s\n" "PID $pid" "$GRPC_PORT"
        printf "  Memory (REST)      %-13s  :%s\n" "PID $pid" "$REST_PORT"
    elif lsof -i :$GRPC_PORT -sTCP:LISTEN >/dev/null 2>&1; then
        local pid
        pid=$(lsof -ti :$GRPC_PORT -sTCP:LISTEN 2>/dev/null || echo "?")
        printf "  Memory (gRPC)      %-13s  :%s\n" "PID $pid *" "$GRPC_PORT"
        printf "  Memory (REST)      %-13s  :%s\n" "PID $pid *" "$REST_PORT"
        echo ""
        echo "  * Running but not managed by this script"
    else
        printf "  Memory (gRPC)      %-13s  :%s\n" "stopped" "$GRPC_PORT"
        printf "  Memory (REST)      %-13s  :%s\n" "stopped" "$REST_PORT"
    fi

    # Health check
    echo ""
    if curl -sf http://localhost:$REST_PORT/health >/dev/null 2>&1; then
        echo "  Health: OK"
    else
        echo "  Health: UNREACHABLE"
    fi
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
    start)   do_start   ;;
    stop)    do_stop    ;;
    restart)
        do_stop
        sleep 2
        do_start
        ;;
    status)  do_status  ;;
    logs)
        if [ -f "$LOGFILE" ]; then
            tail -f "$LOGFILE"
        else
            echo "No log file found at $LOGFILE"
            exit 1
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
