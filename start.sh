#!/bin/bash
echo "=============================================="
echo "🛡️ student_copilot - Sovereign AI Tutor Startup"
echo "=============================================="

echo "[1] Checking for Redis..."
echo "Reminder: Please ensure Redis is running remotely or locally."
echo ""

# ─── TEARDOWN: Kill any stale processes on ports 8000 and 5173 ──────────
cleanup_ports() {
    echo "[*] Cleaning up stale processes on ports 8000 and 5173..."
    for port in 8000 5173; do
        pids=$(lsof -ti ":$port" 2>/dev/null)
        if [ -n "$pids" ]; then
            echo "    Killing stale process(es) on port $port: $pids"
            echo "$pids" | xargs kill -9 2>/dev/null
        fi
    done
}
cleanup_ports

# ─── FULL SHUTDOWN HANDLER ──────────────────────────────────────────────
shutdown() {
    echo ""
    echo "[*] Shutting down all services..."

    # Kill tracked PIDs
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null && echo "    Backend (PID $BACKEND_PID) terminated."
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && echo "    Frontend (PID $FRONTEND_PID) terminated."

    # Fallback: kill anything still on our ports
    cleanup_ports

    echo "[*] Sovereign shutdown complete."
    exit 0
}
trap shutdown INT TERM EXIT

# ─── ACTIVATE VENV ──────────────────────────────────────────────────────
if [ -d "venv" ]; then
    source venv/Scripts/activate 2>/dev/null || source venv/bin/activate
fi

# ─── BOOT BACKEND ──────────────────────────────────────────────────────
echo "[2] Starting Backend (uvicorn via root main.py)..."
python main.py &
BACKEND_PID=$!

# ─── BOOT FRONTEND ─────────────────────────────────────────────────────
echo "[3] Starting Frontend (React/Vite)..."
cd frontend || exit
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "=============================================="
echo "✅ Both services are booting up in the background."
echo "🌐 Backend API: http://localhost:8000 (PID: $BACKEND_PID)"
echo "🌐 Frontend UI: http://localhost:5173 (PID: $FRONTEND_PID)"
echo "=============================================="
echo "Press Ctrl+C to shut down both services."

wait
