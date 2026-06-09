#!/bin/bash
# ============================================================
# Docker Entrypoint: Xvfb + VNC + noVNC + Worker
#
# Starts a virtual display, VNC server, and web-based VNC client
# so you can see and interact with Chrome from your browser.
#
# Access noVNC at: http://<vps-ip>:6080/vnc.html
#
# ROBUST against container restarts:
#   - Force-kills orphan Xvfb/VNC processes from previous runs
#   - Removes stale lock files and sockets
#   - Retries Xvfb startup if first attempt fails
# ============================================================

set -e

# Virtual display config
DISPLAY_NUM="${DISPLAY_NUM:-99}"
SCREEN_RES="${SCREEN_RES:-1920x1080x24}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
MAX_RETRIES=3

export DISPLAY=":${DISPLAY_NUM}"

# ---------------------------------------------------------------
# Cleanup: kill processes + remove lock files
# ---------------------------------------------------------------
cleanup_display() {
    echo "[entrypoint] Cleaning up display :${DISPLAY_NUM}..."

    # Force-kill any Xvfb, x11vnc, websockify processes
    pkill -9 -f "Xvfb :${DISPLAY_NUM}" 2>/dev/null || true
    pkill -9 -f "x11vnc.*${VNC_PORT}" 2>/dev/null || true
    pkill -9 -f "websockify.*${NOVNC_PORT}" 2>/dev/null || true

    # Wait for processes to fully exit
    sleep 1

    # Remove ALL stale lock files and sockets
    rm -f "/tmp/.X${DISPLAY_NUM}-lock" 2>/dev/null || true
    rm -f "/tmp/.X11-unix/X${DISPLAY_NUM}" 2>/dev/null || true

    # Ensure X11 socket directory exists with correct permissions
    mkdir -p /tmp/.X11-unix
    chmod 1777 /tmp/.X11-unix

    echo "[entrypoint] Cleanup complete."
}

# Trap for graceful shutdown
cleanup_on_exit() {
    echo "[entrypoint] Shutting down..."
    # Kill processes gracefully first
    for pid in $NOVNC_PID $X11VNC_PID $XVFB_PID; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    sleep 1
    # Force kill if still alive
    for pid in $NOVNC_PID $X11VNC_PID $XVFB_PID; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    # Clean up lock files
    rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}" 2>/dev/null || true
    echo "[entrypoint] All services stopped."
}
trap cleanup_on_exit EXIT INT TERM

# ---------------------------------------------------------------
# Step 1: Force cleanup from previous run (handles restart case)
# ---------------------------------------------------------------
cleanup_display

# ---------------------------------------------------------------
# Step 2: Start Xvfb with retry logic
# ---------------------------------------------------------------
echo "[entrypoint] Starting Xvfb on display :${DISPLAY_NUM} (${SCREEN_RES})..."

XVFB_STARTED=false
for attempt in $(seq 1 $MAX_RETRIES); do
    Xvfb ":${DISPLAY_NUM}" -screen 0 "${SCREEN_RES}" -ac +extension GLX +render -noreset &
    XVFB_PID=$!
    sleep 2

    if kill -0 $XVFB_PID 2>/dev/null; then
        echo "[entrypoint] Xvfb running (PID: $XVFB_PID) on attempt ${attempt}"
        XVFB_STARTED=true
        break
    else
        echo "[entrypoint] WARN: Xvfb failed on attempt ${attempt}/${MAX_RETRIES}"
        # Clean up and retry
        rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}" 2>/dev/null || true
        sleep 1
    fi
done

if [ "$XVFB_STARTED" != "true" ]; then
    echo "[entrypoint] ERROR: Xvfb failed to start after ${MAX_RETRIES} attempts!"
    exit 1
fi

# ---------------------------------------------------------------
# Step 3 + 4: Start x11vnc + noVNC (chi khi ENABLE_VNC=1)
# Worker prod chi can Xvfb cho Chrome anti-bot; VNC/noVNC ngon CPU/RAM
# va khong can thiet o steady state. Bat khi can debug bang ENABLE_VNC=1.
# ---------------------------------------------------------------
if [ "${ENABLE_VNC:-0}" = "1" ]; then
    echo "[entrypoint] ENABLE_VNC=1 -> Starting x11vnc on port ${VNC_PORT}..."
    x11vnc \
        -display ":${DISPLAY_NUM}" \
        -forever \
        -shared \
        -nopw \
        -rfbport "${VNC_PORT}" \
        -xkb \
        -noxrecord \
        -noxfixes \
        -noxdamage \
        -wait 5 \
        -defer 5 \
        2>/dev/null &
    X11VNC_PID=$!
    sleep 2

    if ! kill -0 $X11VNC_PID 2>/dev/null; then
        echo "[entrypoint] WARN: x11vnc failed to start, continuing without VNC"
    else
        echo "[entrypoint] x11vnc running (PID: $X11VNC_PID)"
    fi

    echo "[entrypoint] Starting noVNC (websockify) on port ${NOVNC_PORT}..."
    websockify \
        --web /usr/share/novnc \
        "${NOVNC_PORT}" \
        "localhost:${VNC_PORT}" \
        2>/dev/null &
    NOVNC_PID=$!
    sleep 1

    if ! kill -0 $NOVNC_PID 2>/dev/null; then
        echo "[entrypoint] WARN: noVNC failed to start, continuing without noVNC"
    else
        echo "[entrypoint] noVNC running (PID: $NOVNC_PID)"
        echo "[entrypoint] ================================================"
        echo "[entrypoint] noVNC ready at: http://localhost:${NOVNC_PORT}/vnc.html"
        echo "[entrypoint] ================================================"
    fi
else
    echo "[entrypoint] ENABLE_VNC=0 (default) -> bo qua x11vnc + noVNC (tiet kiem CPU/RAM)"
    echo "[entrypoint] De debug bat lai: dat ENABLE_VNC=1 trong env"
fi

# ---------------------------------------------------------------
# Step 5: Extract Master Chrome Profile (Master-Replica Architecture)
# Mounted volume contains master_profile.tar.gz (read-only)
# Extract to /tmp/worker_profile to avoid lock conflicts
# ---------------------------------------------------------------
CHROME_MASTER_DIR="/app/chrome_master"
WORKER_PROFILE_DIR="/tmp/worker_profile"
CHROME_ARCHIVE="${CHROME_MASTER_DIR}/master_profile.tar.gz"

if [ -f "$CHROME_ARCHIVE" ]; then
    echo "[entrypoint] Extracting master Chrome profile from archive..."
    mkdir -p "$WORKER_PROFILE_DIR"
    tar -xzf "$CHROME_ARCHIVE" -C "$WORKER_PROFILE_DIR" --strip-components=1 2>/dev/null || tar -xzf "$CHROME_ARCHIVE" -C "$WORKER_PROFILE_DIR" || true
    echo "[entrypoint] Master profile extracted to ${WORKER_PROFILE_DIR}"
    
    # Clean up Chrome profile locks (prevents SQLite lock errors)
    echo "[entrypoint] Cleaning Chrome profile locks..."
    rm -f "${WORKER_PROFILE_DIR}/SingletonLock" 2>/dev/null || true
    rm -f "${WORKER_PROFILE_DIR}/SingletonSocket" 2>/dev/null || true
    rm -f "${WORKER_PROFILE_DIR}/SingletonCookie" 2>/dev/null || true
    rm -f "${WORKER_PROFILE_DIR}/SingletonLock" 2>/dev/null || true
    rm -f "${WORKER_PROFILE_DIR}/.lock" 2>/dev/null || true
    
    # Clean Default profile locks if nested
    if [ -d "${WORKER_PROFILE_DIR}/Default" ]; then
        rm -f "${WORKER_PROFILE_DIR}/Default/SingletonLock" 2>/dev/null || true
        rm -f "${WORKER_PROFILE_DIR}/Default/SingletonSocket" 2>/dev/null || true
        rm -f "${WORKER_PROFILE_DIR}/Default/SingletonCookie" 2>/dev/null || true
        rm -f "${WORKER_PROFILE_DIR}/Default/.lock" 2>/dev/null || true
        rm -f "${WORKER_PROFILE_DIR}/Default/lock" 2>/dev/null || true
        # Clean up other lock-related files
        rm -rf "${WORKER_PROFILE_DIR}/Default/Session Storage" 2>/dev/null || true
        rm -rf "${WORKER_PROFILE_DIR}/Default/IndexedDB" 2>/dev/null || true
    fi
    
    echo "[entrypoint] Chrome profile locks cleaned."
    
    # Set CHROME_PROFILE_DIR for workers to use
    export CHROME_PROFILE_DIR="$WORKER_PROFILE_DIR"
    echo "[entrypoint] CHROME_PROFILE_DIR set to ${WORKER_PROFILE_DIR}"
    # Chown extracted profile cho user webreel (file duoc extract boi root)
    chown -R webreel:webreel "$WORKER_PROFILE_DIR"
elif [ -d "$CHROME_MASTER_DIR" ]; then
    # Fallback: copy from mounted directory if no archive
    echo "[entrypoint] No archive found, using mounted directory as fallback..."
    CHROME_PROFILE="${CHROME_PROFILE_DIR:-/app/chrome_profile}"
    mkdir -p "$CHROME_PROFILE"
    cp -a "$CHROME_MASTER_DIR/." "$CHROME_PROFILE/" 2>/dev/null || true
    
    # Clean locks
    rm -f "${CHROME_PROFILE}/SingletonLock" 2>/dev/null || true
    rm -f "${CHROME_PROFILE}/SingletonSocket" 2>/dev/null || true
    rm -f "${CHROME_PROFILE}/SingletonCookie" 2>/dev/null || true
    chown -R webreel:webreel "$CHROME_PROFILE"
    export CHROME_PROFILE_DIR="$CHROME_PROFILE"
else
    echo "[entrypoint] WARNING: No Chrome master profile found at ${CHROME_MASTER_DIR}"
    export CHROME_PROFILE_DIR="${CHROME_PROFILE_DIR:-/app/chrome_profile}"
fi

# Kill any orphan chromium/chrome processes from previous run
pkill -9 -f "chrome" 2>/dev/null || true
pkill -9 -f "chromium" 2>/dev/null || true
sleep 1

# ---------------------------------------------------------------
# Step 6: Fix ownership cho Docker volumes (xu ly data cu tao boi root)
# Chi can chay 1 lan, cac lan sau ownership da dung
# ---------------------------------------------------------------
echo "[entrypoint] Fixing ownership for output volume..."
chown -R webreel:webreel /app/output 2>/dev/null || true
chown -R webreel:webreel /app/chrome_profile 2>/dev/null || true

# Dam bao /tmp/.X11-unix co quyen sticky bit (Xvfb socket)
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix

# ---------------------------------------------------------------
# Step 7: Ha quyen va chay worker command
# Tat ca setup (cleanup, Xvfb, VNC, noVNC, profile extract) da xong duoi root.
# Bay gio drop xuong user webreel (UID 1000) de chay worker process.
# ---------------------------------------------------------------
echo "[entrypoint] Dropping privileges to user webreel (UID 1000)..."
echo "[entrypoint] Starting worker: $@"
exec gosu webreel "$@"
