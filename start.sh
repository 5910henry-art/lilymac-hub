#!/usr/bin/env bash
# start.sh - Start/stop LilyMac: gateway (SPA), Redis, Gunicorn, and Cloudflare tunnel.
# Optimized: no bc dependency, faster Gunicorn settings, single tunnel.

set -euo pipefail
PROJECT="${PROJECT:-$HOME/lilymac-hub}"
BACKEND="$PROJECT/backend"
FRONTEND="$PROJECT/frontend"
LOG_DIR="$PROJECT/logs"

mkdir -p "$LOG_DIR"

# ----------------------------
# Helpers
# ----------------------------
check_running(){
    # pgrep -f pattern
    pgrep -f "$1" >/dev/null 2>&1
}

wait_for_http_ok(){
    PORT=$1
    TIMEOUT=${2:-30}
    EXPECT=${3:-""}
    echo "Waiting for HTTP OK on http://localhost:$PORT (timeout ${TIMEOUT}s)..."
    for i in $(seq 1 $TIMEOUT); do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT" || echo "000")
        if [[ "$HTTP_CODE" =~ ^[23] ]]; then
            if [ -n "$EXPECT" ]; then
                if curl -s "http://localhost:$PORT" | grep -q "$EXPECT"; then
                    return 0
                fi
            else
                return 0
            fi
        fi
        sleep 1
    done
    return 1
}

start_service(){
    NAME=$1
    MATCH=$2
    CMD=$3
    LOG=$4
    if check_running "$MATCH"; then
        echo "$NAME already running"
    else
        echo "Starting $NAME..."
        nohup bash -c "$CMD" > "$LOG_DIR/$LOG" 2>&1 &
        sleep 2
    fi
}

get_tunnel_url_from_log(){
    LOGFILE=$1
    for i in {1..30}; do
        if [ -f "$LOG_DIR/$LOGFILE" ]; then
            URL=$(grep -o "https://[a-z0-9.-]*trycloudflare.com" "$LOG_DIR/$LOGFILE" | head -n1 || true)
            if [ -n "$URL" ]; then
                echo "$URL"
                return 0
            fi
        fi
        sleep 1
    done
    echo "URL_NOT_FOUND"
    return 1
}

# Build frontend if needed (no bc dependency)
build_frontend_if_needed(){
    cd "$FRONTEND" || return 1
    # Install deps if missing
    if [ ! -d node_modules ]; then
        echo "Installing frontend dependencies..."
        npm install
    fi

    if [ ! -d build ]; then
        echo "build/ missing → building frontend"
        npm run build
        return $?
    fi

    LAST_BUILD=$(stat -c %Y build 2>/dev/null || echo 0)
    LAST_SRC=$(find src -type f -printf "%T@\n" 2>/dev/null | sort -n | tail -1 || echo 0)
    # convert LAST_SRC decimal to integer (seconds)
    LAST_SRC_INT=${LAST_SRC%%.*}
    if [ -z "$LAST_SRC_INT" ]; then LAST_SRC_INT=0; fi

    if [ "$LAST_SRC_INT" -gt "$LAST_BUILD" ]; then
        echo "Frontend sources changed → building frontend"
        npm run build
    else
        echo "Frontend unchanged → skipping build"
    fi
}

kill_old_cloudflared(){
    if check_running "cloudflared"; then
        echo "Killing existing cloudflared processes..."
        pkill -f cloudflared || true
        sleep 1
    fi
}

# ----------------------------
# Start platform
# ----------------------------
start_platform(){
    echo
    echo "Starting LilyMac Platform (Gateway + Frontend + Tunnel)..."
    echo

    kill_old_cloudflared

    # Redis
    if ! check_running "redis-server"; then
        echo "Starting Redis..."
        redis-server --daemonize yes
        sleep 1
    else
        echo "Redis already running"
    fi

    # Build frontend if needed
    build_frontend_if_needed || { echo "Frontend build failed"; return 1; }

    # Start Gateway via Gunicorn (mounts SPA + backend apps)
    cd "$BACKEND" || { echo "Backend dir not found: $BACKEND"; return 1; }

    GUNICORN_CMD="gunicorn -b 0.0.0.0:5000 gateway:application --workers 3 --threads 2 --log-file -"
    start_service "Gateway (Gunicorn)" "gunicorn" "$GUNICORN_CMD" gateway.log

    # Wait for gateway
    if wait_for_http_ok 5000 30; then
        echo "Gateway on port 5000 is responding."
    else
        echo "ERROR: Gateway port 5000 did not respond."
        tail -n 80 "$LOG_DIR/gateway.log"
        return 1
    fi

    # Start Cloudflare Tunnel to Gateway
    start_service "Cloudflare Tunnel" "cloudflared tunnel --url http://localhost:5000" \
        "cloudflared tunnel --url http://localhost:5000" tunnel.log

    TUNNEL_URL=$(get_tunnel_url_from_log tunnel.log)
    echo "Platform public URL: ${TUNNEL_URL:-unavailable}"

    echo
    echo "======================================"
    echo "        LilyMac Platform Ready"
    echo "======================================"
    echo "Public URL  : ${TUNNEL_URL:-unavailable}"
    echo "Local URL   : http://127.0.0.1:5000"
    echo "======================================"
}

# ----------------------------
# Stop platform
# ----------------------------
stop_platform(){
    echo "Stopping platform..."
    pkill -f "gateway:application" || true
    pkill -f "gunicorn" || true
    pkill -f cloudflared || true
    redis-cli shutdown 2>/dev/null || true
    echo "Platform stopped"
}

# ----------------------------
# Status
# ----------------------------
status_platform(){
    echo
    check_running redis-server && echo "Redis: RUNNING" || echo "Redis: STOPPED"
    check_running gunicorn && echo "Gateway (gunicorn): RUNNING" || echo "Gateway (gunicorn): STOPPED"
    check_running cloudflared && echo "Tunnel: RUNNING" || echo "Tunnel: STOPPED"
    ( curl -s -o /dev/null -w "%{http_code}" http://localhost:5000 | grep -q '[23]') && echo "Frontend + API (5000): RUNNING" || echo "Frontend + API (5000): STOPPED"
}

# ----------------------------
# Logs
# ----------------------------
view_gateway_logs(){ tail -f "$LOG_DIR/gateway.log"; }
view_tunnel_logs(){ tail -f "$LOG_DIR/tunnel.log"; }

# ----------------------------
# Menu
# ----------------------------
while true; do
    echo
    echo "================================"
    echo "      LilyMac Control Panel"
    echo "================================"
    echo "1 Start Platform"
    echo "2 Stop Platform"
    echo "3 Restart Platform"
    echo "4 Status"
    echo "5 Gateway Logs"
    echo "6 Tunnel Logs"
    echo "7 DevOps Dashboard"
    echo "8 Exit"
    echo "================================"
    read -p "Select option: " option
    case $option in
        1) start_platform ;;
        2) stop_platform ;;
        3) stop_platform; sleep 2; start_platform ;;
        4) status_platform ;;
        5) view_gateway_logs ;;
        6) view_tunnel_logs ;;
        7)
            while true; do
                clear
                CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print $2 + $4}')
                RAM=$(free -h | awk '/Mem:/ {print $3 "/" $2}')
                check_running gunicorn && GW="RUNNING" || GW="STOPPED"
                check_running cloudflared && TUN="RUNNING" || TUN="STOPPED"
                ( curl -s -o /dev/null -w "%{http_code}" http://localhost:5000 | grep -q '[23]') && FE="RUNNING" || FE="STOPPED"
                echo "================================"
                echo "      LilyMac DevOps Dashboard"
                echo "================================"
                echo ""
                echo "Gateway + Frontend : $FE"
                echo "Redis             : $(check_running redis-server && echo RUNNING || echo STOPPED)"
                echo "Tunnel             : $TUN"
                echo ""
                echo "CPU Usage : $CPU %"
                echo "RAM Usage : $RAM"
                echo ""
                echo "CTRL+C to exit"
                sleep 3
            done
            ;;
        8) exit 0 ;;
        *) echo "Invalid option" ;;
    esac
done
