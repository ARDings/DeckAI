@echo off
REM ============================================================
REM  DeckAI AutoStart — Starts cockpit, waits, then launches VSD Craft
REM  Place shortcut in: shell:startup (Win+R, type shell:startup)
REM ============================================================

cd /d "%~dp0"

echo Starting DeckAI Cockpit...
start "DeckAI Cockpit" /MIN cmd /c "%~dp0run.bat"

REM Wait for cockpit to be ready (max 30 seconds)
echo Waiting for cockpit...
for /L %%i in (1,1,30) do (
    curl -s -o NUL http://127.0.0.1:8000/state 2>NUL && goto :ready
    timeout /t 1 /nobreak >NUL
)
echo WARNING: Cockpit did not start within 30 seconds!

:ready
echo Cockpit is ready!

REM Launch VSD Craft
echo Starting VSD Craft...
start "" "C:\Program Files (x86)\VSD Craft\VSD Craft.exe" --RunInBackground

echo DeckAI AutoStart complete.
