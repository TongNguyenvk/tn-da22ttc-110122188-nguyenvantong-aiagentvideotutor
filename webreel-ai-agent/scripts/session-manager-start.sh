#!/bin/bash
# ============================================================
# Session Manager Start Script
# Starts Xvfb + VNC + noVNC + Chrome + Internal API
# ============================================================

set -e

DISPLAY_NUM="${DISPLAY_NUM:-99}"
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"

export DISPLAY=":${DISPLAY_NUM}"

cleanup_display() {
    echo "[session-manager] Cleaning up display :${DISPLAY_NUM}..."
    pkill -9 -f "Xvfb :${DISPLAY_NUM}" 2>/dev/null || true
    pkill -9 -f "x11vnc.*${VNC_PORT}" 2>/dev/null || true
    pkill -9 -f "websockify.*${NOVNC_PORT}" 2>/dev/null || true
    sleep 1
    rm -f "/tmp/.X${DISPLAY_NUM}-lock" 2>/dev/null || true
    rm -f "/tmp/.X11-unix/X${DISPLAY_NUM}" 2>/dev/null || true
    mkdir -p /tmp/.X11-unix
    chmod 1777 /tmp/.X11-unix
    # Dam bao /tmp/worker_profile ton tai va thuoc webreel
    mkdir -p /tmp/worker_profile
    chown webreel:webreel /tmp/worker_profile
    echo "[session-manager] Cleanup complete."
}

cleanup_on_exit() {
    echo "[session-manager] Shutting down..."
    for pid in $NOVNC_PID $X11VNC_PID $XVFB_PID $CHROME_PID $PROXY_PID; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    echo "[session-manager] Stopped."
}
trap cleanup_on_exit EXIT INT TERM

cleanup_display

# Start Xvfb
echo "[session-manager] Starting Xvfb on display :${DISPLAY_NUM}..."
Xvfb ":${DISPLAY_NUM}" -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 2

if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "[session-manager] ERROR: Xvfb failed to start"
    exit 1
fi
echo "[session-manager] Xvfb running (PID: $XVFB_PID)"

# Start x11vnc
echo "[session-manager] Starting x11vnc on port ${VNC_PORT}..."
x11vnc -display ":${DISPLAY_NUM}" -forever -shared -nopw -rfbport "${VNC_PORT}" -xkb -noxrecord -noxfixes -noxdamage -wait 5 -defer 5 2>/dev/null &
X11VNC_PID=$!
sleep 1
echo "[session-manager] x11vnc running (PID: $X11VNC_PID)"

# Start noVNC
echo "[session-manager] Starting noVNC on port ${NOVNC_PORT}..."
websockify --web /usr/share/novnc "${NOVNC_PORT}" "localhost:${VNC_PORT}" 2>/dev/null &
NOVNC_PID=$!
sleep 1
echo "[session-manager] noVNC running (PID: $NOVNC_PID)"

echo "[session-manager] VNC services started"
echo "[session-manager] noVNC: http://localhost:${NOVNC_PORT}/vnc.html"

# Clean Chrome profile locks
CHROME_PROFILE="${CHROME_PROFILE_DIR:-/app/chrome_master}"
mkdir -p "$CHROME_PROFILE"
echo "[session-manager] Cleaning Chrome profile locks in ${CHROME_PROFILE}..."
rm -f "${CHROME_PROFILE}/SingletonLock" 2>/dev/null || true
rm -f "${CHROME_PROFILE}/SingletonSocket" 2>/dev/null || true
rm -f "${CHROME_PROFILE}/SingletonCookie" 2>/dev/null || true
rm -f "${CHROME_PROFILE}/Default/SingletonLock" 2>/dev/null || true
rm -f "${CHROME_PROFILE}/Default/SingletonSocket" 2>/dev/null || true
rm -f "${CHROME_PROFILE}/Default/SingletonCookie" 2>/dev/null || true

# Kill any orphan Chrome processes
pkill -9 -f "chrome" 2>/dev/null || true
pkill -9 -f "chromium" 2>/dev/null || true
sleep 1

# Fix ownership cho Chrome profile (volume co the co data cu tao boi root)
chown -R webreel:webreel "$CHROME_PROFILE" 2>/dev/null || true

# Start Chrome
echo "[session-manager] Starting Chrome..."

if command -v google-chrome &> /dev/null; then
    CHROME_BIN="google-chrome"
elif ls /opt/pw-browsers/chromium-*/chrome-linux64/chrome 1>/dev/null 2>&1; then
    CHROME_BIN=$(ls /opt/pw-browsers/chromium-*/chrome-linux64/chrome 2>/dev/null | head -1)
elif ls /opt/pw-browsers/chromium-*/chrome-linux/chrome 1>/dev/null 2>&1; then
    CHROME_BIN=$(ls /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)
elif command -v chromium-browser &> /dev/null; then
    CHROME_BIN="chromium-browser"
else
    echo "[session-manager] ERROR: Khong tim thay Chrome binary!"
    echo "[session-manager] Kiem tra: ls /opt/pw-browsers/"
    ls -la /opt/pw-browsers/ 2>/dev/null || true
    # Tiep tuc chay API ma khong co Chrome (VNC van hoat dong)
    CHROME_BIN=""
fi

echo "[session-manager] Using Chrome binary: $CHROME_BIN"

if [ -n "$CHROME_BIN" ]; then
    # Chrome chay duoi user webreel (non-root) voi --no-sandbox
    # Day la accepted risk: mat Chrome sandbox nhung duoc non-root isolation
    gosu webreel "$CHROME_BIN" \
        --display=:99 \
        --disable-gpu \
        --no-sandbox \
        --remote-debugging-port=9221 \
        --remote-debugging-address=127.0.0.1 \
        --remote-allow-origins=* \
        --window-size=1280,800 \
        --window-position=0,0 \
        --disable-dev-shm-usage \
        --disable-background-networking \
        --disable-default-apps \
        --disable-extensions \
        --disable-sync \
        --disable-translate \
        --start-maximized \
        --home-page "https://www.office.com" \
        --user-data-dir="$CHROME_PROFILE" \
        > /tmp/chrome.log 2>&1 &

    CHROME_PID=$!
    echo "[session-manager] Chrome started (PID: $CHROME_PID)"
    sleep 3

    if kill -0 $CHROME_PID 2>/dev/null; then
        echo "[session-manager] Chrome is running"
        
        # Start HTTP/WS proxy to expose Chrome DevTools (127.0.0.1:9221) to external network on port 9222
        # This resolves Host validation and rewrites websocket addresses with correct Content-Length.
        gosu webreel node -e "
const http = require('http');
const net = require('net');

const server = http.createServer((req, res) => {
    const headers = { ...req.headers };
    headers['host'] = 'localhost:9221';

    const proxyReq = http.request({
        host: '127.0.0.1',
        port: 9221,
        path: req.url,
        method: req.method,
        headers: headers
    }, (proxyRes) => {
        let body = [];
        proxyRes.on('data', chunk => body.push(chunk));
        proxyRes.on('end', () => {
            let buffer = Buffer.concat(body);
            if (proxyRes.headers['content-type'] && proxyRes.headers['content-type'].includes('application/json')) {
                let str = buffer.toString('utf8');
                const clientHost = req.headers['host'] || 'session-manager:9222';
                str = str.replace(/127\.0\.0\.1:9221/g, clientHost);
                str = str.replace(/localhost:9221/g, clientHost);
                buffer = Buffer.from(str, 'utf8');
            }
            
            const resHeaders = { ...proxyRes.headers };
            resHeaders['content-length'] = buffer.length;
            
            res.writeHead(proxyRes.statusCode, resHeaders);
            res.end(buffer);
        });
    });

    proxyReq.on('error', (err) => {
        res.writeHead(500);
        res.end(err.message);
    });

    req.pipe(proxyReq);
});

server.on('upgrade', (req, socket, head) => {
    const targetSocket = net.connect(9221, '127.0.0.1', () => {
        let upgradeRequest = req.method + ' ' + req.url + ' HTTP/' + req.httpVersion + '\r\n';
        for (let i = 0; i < req.rawHeaders.length; i += 2) {
            let key = req.rawHeaders[i];
            let val = req.rawHeaders[i+1];
            if (key.toLowerCase() === 'host') {
                val = 'localhost:9221';
            }
            upgradeRequest += key + ': ' + val + '\r\n';
        }
        upgradeRequest += '\r\n';
        
        targetSocket.write(upgradeRequest);
        if (head && head.length > 0) {
            targetSocket.write(head);
        }
        
        socket.pipe(targetSocket).pipe(socket);
    });
    
    targetSocket.on('error', () => socket.destroy());
    socket.on('error', () => targetSocket.destroy());
});

server.listen(9222, '0.0.0.0', () => {
    console.log('HTTP/WS Proxy listening on 0.0.0.0:9222 -> 127.0.0.1:9221');
});
" &
        PROXY_PID=$!
        echo "[session-manager] Chrome CDP TCP Proxy started (PID: $PROXY_PID, Port: 9222)"
    else
        echo "[session-manager] WARN: Chrome may have failed to start"
        echo "[session-manager] Chrome log:"
        cat /tmp/chrome.log
    fi
else
    echo "[session-manager] WARN: Chrome binary not found, skipping Chrome launch"
    echo "[session-manager] VNC desktop van hoat dong, co the cai Chrome thu cong"
fi

# Start internal API duoi user webreel
echo "[session-manager] Starting internal API on port 8001 (as webreel)..."
cd /app/webreel-ai-agent
exec gosu webreel python -c "
import uvicorn
from session_manager.app import app
uvicorn.run(app, host='0.0.0.0', port=8001)
"