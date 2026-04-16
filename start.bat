@echo off
echo ==============================================
echo student_copilot - Sovereign AI Tutor Boot Sequence
echo ==============================================

echo [1] Reminder: Ensure Redis is running locally (Port 6379) or remote REDIS_URL is configured.
echo.

REM --- TEARDOWN: Kill any stale processes on ports 8000 and 5173 ---
echo [*] Cleaning up stale processes on ports 8000 and 5173...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo     Killing stale backend PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    echo     Killing stale frontend PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)
echo.

REM --- BOOT BACKEND ---
echo [2] Booting Backend (Uvicorn) in background...
start /B python main.py
echo.

REM --- BOOT FRONTEND (foreground - Ctrl+C will break here) ---
echo [3] Booting Frontend (Vite) in foreground...
cd frontend
npm run dev
cd ..

REM --- SHUTDOWN: When Vite exits (Ctrl+C), tear down everything ---
echo.
echo [*] Frontend stopped. Tearing down all services...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo     Killing backend on port 8000 (PID: %%a)
    taskkill /F /PID %%a >nul 2>&1
)
echo [*] All services terminated. Sovereign shutdown complete.
