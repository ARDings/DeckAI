@echo off
REM ============================================================
REM  DeckAI Cockpit — Startup Script
REM  Starts the Python proxy + generates button images.
REM  Run this BEFORE opening VS Code.
REM ============================================================

REM ---- Configuration ----
set TC001_IP=192.168.178.51
REM Phone notifications (ntfy.sh)
set NTFY_TOPIC=DeckAI-xrchris

cd /d "%~dp0"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║        🎛️  DeckAI Cockpit v0.1.0             ║
echo ║   Stream Dock N3  +  VS Code  +  DeepSeek   ║
echo ╚══════════════════════════════════════════════╝
echo.

REM ---- Check for Python ----
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Python not found! Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM ---- Install dependencies (if needed) ----
if not exist "venv\" (
    echo 🐍 Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo 📦 Checking dependencies...
pip install -q -r requirements.txt

REM ---- Generate plugin icons (first run) ----
echo 🎨 Generating button icons...
python setup_icons.py
python image_gen.py

REM ---- Start cockpit ----
echo.
echo TC001: %TC001_IP%
echo Starting DeckAI Cockpit on http://127.0.0.1:8000
echo WebSocket: ws://127.0.0.1:8000/ws
echo Proxy:     http://127.0.0.1:8000/v1/messages
echo Dashboard: http://127.0.0.1:8000
echo.
echo Keep this window open while using VS Code!
echo =======================================================
echo.

python -m uvicorn cockpit:app --host 127.0.0.1 --port 8000 --log-level info

pause
