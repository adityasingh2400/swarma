@echo off
setlocal

set PORT_BACKEND=8080
set PORT_FRONTEND=5173

:: ── Kill stale processes on our ports ───────────────────────────────────────
echo   Stopping existing servers...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORT_BACKEND% " 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORT_FRONTEND% " 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: ── Install / sync dependencies ─────────────────────────────────────────────
if not exist .venv (
    echo   Creating virtualenv...
    python -m venv .venv
)
echo   Syncing dependencies...
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt 2>&1 | findstr /v "^$"

:: ── Build frontend ───────────────────────────────────────────────────────────
echo   Building frontend...
pushd frontend\mac
call npm install --silent
call npm run build
popd

:: ── Warm-up ──────────────────────────────────────────────────────────────────
python scripts\warmup.py

:: ── Launch servers ───────────────────────────────────────────────────────────
echo.
echo   Launching backend (:%PORT_BACKEND%) + frontend (:%PORT_FRONTEND%)...
echo.

start "swarma-backend" cmd /k "call .venv\Scripts\activate.bat && python run.py"
timeout /t 2 /nobreak >nul

start "swarma-frontend" cmd /k "cd frontend\mac && npx vite --force --port %PORT_FRONTEND%"
timeout /t 2 /nobreak >nul

echo.
echo   ──────────────────────────────────────
echo   [OK] READY
echo.
echo     App:     http://localhost:%PORT_FRONTEND%/
echo     Backend: http://localhost:%PORT_BACKEND%/
echo     Mock:    http://localhost:%PORT_FRONTEND%/?mock
echo     Preview: http://localhost:%PORT_FRONTEND%/?preview=concierge
echo   ──────────────────────────────────────
echo.
echo   Close the backend and frontend windows to stop all servers.
echo.

endlocal
