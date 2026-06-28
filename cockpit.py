"""
DeckAI Cockpit — FastAPI Server
================================
- HTTP endpoints for Stream Dock dial control
- WebSocket server for real-time LCD button updates
- DeepSeek API proxy with hardware-state prompt injection
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from state import CockpitState, TrafficLight, get_state
from image_gen import get_button_png_base64, STATIC_DIR, save_all_to_disk
from eyes import get_eyes, TC001_ENABLED

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DeckAI] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("deckai")

# ---------------------------------------------------------------------------
# DeepSeek API base URL (can be overridden via env)
# ---------------------------------------------------------------------------
# Default: Anthropic-compatible endpoint (used by Claude Code extension)
DEEPSEEK_ANTHROPIC_URL = os.environ.get(
    "DEEPSEEK_ANTHROPIC_URL",
    "https://api.deepseek.com/anthropic/messages",
)
# OpenAI-compatible fallback (used by other extensions)
DEEPSEEK_OPENAI_URL = os.environ.get(
    "DEEPSEEK_OPENAI_URL",
    "https://api.deepseek.com/v1/chat/completions",
)
PROXY_PORT = int(os.environ.get("DECKAI_PORT", "8000"))

# ---------------------------------------------------------------------------
# WebSocket clients (Stream Dock plugin connections)
# ---------------------------------------------------------------------------
ws_clients: set[WebSocket] = set()


# Pre-render static images at import time (never change)
_TRAFFIC_IMAGES = {
    "green_active": get_button_png_base64("traffic_green_active"),
    "yellow_active": get_button_png_base64("traffic_yellow_active"),
    "red_active": get_button_png_base64("traffic_red_active"),
    "green_inactive": get_button_png_base64("traffic_green_inactive"),
    "yellow_inactive": get_button_png_base64("traffic_yellow_inactive"),
    "red_inactive": get_button_png_base64("traffic_red_inactive"),
}
_VSCODE_IMAGE = get_button_png_base64("vscode_focus")

# Cached effort/mode images (change when state changes)
_img_cache: dict = {}
_last_effort: str = ""
_last_mode: str = ""


async def broadcast_state(state: CockpitState):
    """Push current cockpit state to all connected Stream Dock plugins."""
    global _last_effort, _last_mode

    # Traffic images: always regenerate (they depend on traffic_light)
    # Static images: only regenerate when effort/mode changes
    if state.effort != _last_effort:
        _img_cache["btn_effort"] = get_button_png_base64(f"effort_{state.effort}")
        _last_effort = state.effort

    if state.mode != _last_mode:
        _img_cache["btn_mode"] = get_button_png_base64(f"mode_{state.mode}")
        _last_mode = state.mode

    payload = {
        "type": "state_update",
        "traffic_light": state.traffic_light.value,
        "effort": state.effort,
        "effort_idx": state.effort_idx,
        "mode": state.mode,
        "mode_idx": state.mode_idx,
        "error_message": state.error_message,
        "buttons": {
            "btn_traffic_green_active": _TRAFFIC_IMAGES["green_active"],
            "btn_traffic_yellow_active": _TRAFFIC_IMAGES["yellow_active"],
            "btn_traffic_red_active": _TRAFFIC_IMAGES["red_active"],
            "btn_traffic_green_inactive": _TRAFFIC_IMAGES["green_inactive"],
            "btn_traffic_yellow_inactive": _TRAFFIC_IMAGES["yellow_inactive"],
            "btn_traffic_red_inactive": _TRAFFIC_IMAGES["red_inactive"],
            "btn_effort": _img_cache.get("btn_effort", get_button_png_base64("effort_High (Detailed)")),
            "btn_vscode": _VSCODE_IMAGE,
            "btn_mode": _img_cache.get("btn_mode", get_button_png_base64("mode_Code Agent")),
        },
    }
    dead: set[WebSocket] = set()
    for ws in ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


def on_state_change(state: CockpitState):
    """Sync callback → schedules async broadcast + eye update."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_state(state))
        # Update TC001 eyes to match traffic light
        eyes = get_eyes()
        eyes.set_state(state.traffic_light.value)
    except RuntimeError:
        pass  # No event loop yet (e.g. during startup)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown."""
    state = get_state()
    state.on_change(on_state_change)

    # Start TC001 eyes if configured
    eyes = get_eyes()
    await eyes.start()

    log.info(f"DeckAI Cockpit started")
    log.info(f"  Anthropic -> {DEEPSEEK_ANTHROPIC_URL}")
    log.info(f"  OpenAI   -> {DEEPSEEK_OPENAI_URL}")
    if TC001_ENABLED:
        log.info(f"  TC001 Eyes -> {eyes.ip}")
    log.info(f"WebSocket: ws://127.0.0.1:{PROXY_PORT}/ws")
    log.info(f"Dial API:  http://127.0.0.1:{PROXY_PORT}/dial/effort?dir=up")
    log.info(f"Claude Code: http://127.0.0.1:{PROXY_PORT}/messages")
    yield
    await eyes.stop()
    log.info("DeckAI Cockpit shutting down.")


app = FastAPI(title="DeckAI Cockpit", version="0.1.0", lifespan=lifespan)

# Mount static directory for button images (served to Stream Dock plugin)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# VS Code Focus endpoint (called by Stream Dock plugin)
# ---------------------------------------------------------------------------


@app.post("/focus/vscode")
async def focus_vscode():
    """Bring VS Code to the foreground using platform-specific commands."""
    log.info("Focusing VS Code...")
    try:
        if sys.platform == "win32":
            script = '''
            Add-Type @"
            using System;
            using System.Runtime.InteropServices;
            using System.Text;
            public class Win32 {
                [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
                [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
                [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
                [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
                [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
                public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
            }
"@
            $ptr = [IntPtr]::Zero

            # 1) Try by process MainWindowHandle
            $procs = Get-Process -Name "code","Code" -ErrorAction SilentlyContinue
            foreach ($p in $procs) {
                if ($p.MainWindowHandle -and $p.MainWindowHandle -ne [IntPtr]::Zero) {
                    $ptr = $p.MainWindowHandle
                    break
                }
            }

            # 2) Fallback: enumerate windows looking for VS Code title
            if ($ptr -eq [IntPtr]::Zero) {
                $cb = [Win32+EnumWindowsProc]{
                    param($h, $l)
                    $sb = New-Object Text.StringBuilder(256)
                    [Win32]::GetWindowText($h, $sb, 256)
                    $t = $sb.ToString()
                    if ($t -like "*Visual Studio Code*" -and $t -ne "") {
                        $script:ptr = $h
                        return $false
                    }
                    return $true
                }
                [Win32]::EnumWindows($cb, [IntPtr]::Zero)
            }

            if ($ptr -ne [IntPtr]::Zero) {
                [Win32]::ShowWindow($ptr, 9)
                [Win32]::SetForegroundWindow($ptr)
                Write-Output "FOCUSED"
            } else {
                Start-Process "code"
                Write-Output "LAUNCHED"
            }
            '''
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10,
            )
            log.info(f"Focus result: {result.stdout.strip()}")
            return {"status": "ok", "result": result.stdout.strip()}

        elif sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e", 'tell application "Visual Studio Code" to activate'],
                timeout=5,
            )
            return {"status": "ok", "result": "activated"}

        else:
            # Linux: try wmctrl
            subprocess.run(["wmctrl", "-a", "Visual Studio Code"], timeout=5)
            return {"status": "ok", "result": "wmctrl"}

    except Exception as e:
        log.error(f"Focus failed: {e}")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Static dashboard (optional — open in browser to monitor state)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    state = get_state()
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><title>DeckAI Cockpit</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:#1a1a2e; color:#eee;
         display:flex; flex-direction:column; align-items:center; justify-content:center;
         min-height:100vh; gap:2rem; }}
  .cockpit {{ display:grid; grid-template-columns:repeat(3,120px); gap:12px; }}
  .btn {{ width:120px; height:120px; border-radius:12px; display:flex;
          flex-direction:column; align-items:center; justify-content:center;
          font-size:11px; text-align:center; padding:8px; gap:4px; }}
  .green {{ background:#0a3; box-shadow:0 0 20px #0a3; }}
  .yellow {{ background:#b80; box-shadow:0 0 20px #b80; }}
  .red {{ background:#c22; box-shadow:0 0 20px #c22; }}
  .off {{ background:#222; }}
  .info {{ font-size:13px; color:#aaa; }}
  .dial {{ display:flex; flex-direction:column; align-items:center; gap:8px; }}
  .dial a {{ color:#0af; text-decoration:none; font-size:13px; }}
  .dial span {{ font-size:10px; color:#888; }}
</style>
<script>
  const ws = new WebSocket(`ws://${{location.host}}/ws`);
  ws.onmessage = e => {{
    const s = JSON.parse(e.data);
    ['green','yellow','red'].forEach(c => {{
      document.getElementById(c).className = 'btn ' + (s.traffic_light===c ? c : 'off');
    }});
    document.getElementById('effort').textContent = s.effort;
    document.getElementById('mode').textContent = s.mode;
  }};
</script>
</head>
<body>
<h2>🎛️ DeckAI Cockpit</h2>
<div class="cockpit">
  <div id="green" class="btn {'green' if state.traffic_light.value == 'green' else 'off'}">🟢<br>BEREIT</div>
  <div id="yellow" class="btn {'yellow' if state.traffic_light.value == 'yellow' else 'off'}">🟡<br>ARBEITET</div>
  <div id="red" class="btn {'red' if state.traffic_light.value == 'red' else 'off'}">🔴<br>FEHLER</div>
  <div id="effort" class="btn off">{state.effort}</div>
  <div class="btn off" style="border:2px solid #0af;">💻<br>VS CODE</div>
  <div id="mode" class="btn off">{state.mode}</div>
</div>
<div class="info">
  <div class="dial">
    <span>Effort:</span>
    <a href="/dial/effort?dir=up">▲</a>
    <span id="effort">{state.effort}</span>
    <a href="/dial/effort?dir=down">▼</a>
  </div>
  <div class="dial">
    <span>Mode:</span>
    <a href="/dial/mode?dir=up">▲</a>
    <span id="mode">{state.mode}</span>
    <a href="/dial/mode?dir=down">▼</a>
  </div>
</div>
<p class="info">Proxy: <code>http://127.0.0.1:{PROXY_PORT}/v1/chat/completions</code></p>
</body>
</html>""")


# ---------------------------------------------------------------------------
# Dial endpoints (called by Stream Dock hardware via VSD Craft)
# ---------------------------------------------------------------------------


@app.get("/dial/effort")
async def dial_effort(dir: str = "up"):
    """Turn the large wheel: adjust effort level."""
    state = get_state()
    old = state.effort
    if dir == "up":
        state.dial_effort_up()
    else:
        state.dial_effort_down()
    log.info(f"🎚️  Effort: {old} → {state.effort}")
    return {"status": "ok", "effort": state.effort, "effort_idx": state.effort_idx}


@app.get("/dial/mode")
async def dial_mode(dir: str = "up"):
    """Turn the small wheel: adjust work mode."""
    state = get_state()
    old = state.mode
    if dir == "up":
        state.dial_mode_up()
    else:
        state.dial_mode_down()
    log.info(f"🔄 Mode:   {old} → {state.mode}")
    return {"status": "ok", "mode": state.mode, "mode_idx": state.mode_idx}


# ---------------------------------------------------------------------------
# State query (for debugging / external tools)
# ---------------------------------------------------------------------------


@app.get("/state")
async def get_full_state():
    """Return current cockpit state as JSON."""
    state = get_state()
    return {
        "traffic_light": state.traffic_light.value,
        "effort": state.effort,
        "effort_idx": state.effort_idx,
        "mode": state.mode,
        "mode_idx": state.mode_idx,
        "error_message": state.error_message,
    }


# ---------------------------------------------------------------------------
# Test endpoint: simulate question detection
# ---------------------------------------------------------------------------


@app.post("/test/traffic")
async def test_traffic(request: Request):
    """Test the traffic light directly. Send {"color": "red|yellow|green"}"""
    body = await request.json()
    color = body.get("color", "green")
    state = get_state()
    state.set_traffic(TrafficLight(color))
    return {"status": "ok", "traffic_light": state.traffic_light.value}


@app.post("/test/question")
async def test_question(request: Request):
    """Simulate streaming completion with a given AI response text. Tests detection."""
    body = await request.json()
    text = body.get("text", "")
    t = text.lower()

    import re as _re
    stops = _re.findall(r'"stop_reason"\s*:\s*"([^"]+)"', text)
    last_stop = stops[-1] if stops else "unknown"

    has_question = False
    if last_stop not in ("end_turn", "tool_use", "max_tokens", "stop_sequence"):
        strict_questions = [
            "soll ich", "möchtest du", "willst du",
            "shall i", "would you like", "do you want me",
            "continue?", "proceed?", "fortfahren?",
            "is that ok?", "does that look right?",
            "confirm?", "bestätigen?",
            "what would you",
        ]
        has_question = any(p in t for p in strict_questions)
        if not has_question:
            has_question = t.rstrip().endswith("?")

    state = get_state()
    if last_stop == "tool_use":
        state.set_traffic(TrafficLight.RED, error_msg="Befehl wartet — genehmigen!")
        result = f"RED (stop_reason=tool_use)"
    elif last_stop in ("end_turn", "max_tokens", "stop_sequence"):
        state.set_traffic(TrafficLight.GREEN)
        result = f"GREEN (stop_reason={last_stop})"
    elif has_question:
        state.set_traffic(TrafficLight.RED, error_msg="Rückfrage!")
        result = "RED (question)"
    else:
        state.set_traffic(TrafficLight.GREEN)
        result = "GREEN"

    return {
        "result": result,
        "last_stop": last_stop,
        "all_stops": stops,
        "has_question": has_question,
        "text_snippet": text[-200:],
    }


# ---------------------------------------------------------------------------
# Debug + Answer endpoints
# ---------------------------------------------------------------------------


@app.post("/log/dial")
async def log_dial(request: Request):
    """Debug: log raw dialRotate event payload."""
    body = await request.json()
    log.info(f"[DIAL DEBUG] {body}")
    return {"ok": True}


@app.post("/answer/{text}")
async def quick_answer(text: str):
    """Type a quick answer via keyboard simulation."""
    log.info(f"Answer: [{text}]")
    try:
        if sys.platform == "win32":
            script = f'Add-Type -AssemblyName System.Windows.Forms;[System.Windows.Forms.SendKeys]::SendWait("{text}")'
            subprocess.run(["powershell","-NoProfile","-Command",script],timeout=5,capture_output=True)
        elif sys.platform == "darwin":
            subprocess.run(["osascript","-e",f'tell app "System Events" to keystroke "{text}"'],timeout=5)
        return {"status":"ok","text":text}
    except Exception as e:
        return {"status":"error","message":str(e)}


# ---------------------------------------------------------------------------
# WebSocket endpoint (Stream Dock plugin connects here)
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    log.info(f"🔌 Stream Dock connected (total: {len(ws_clients)})")

    # Send initial state immediately
    state = get_state()
    await broadcast_state(state)

    try:
        while True:
            # Keep alive — we only push, but accept pings from client
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
            else:
                log.debug(f"WS received: {data}")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning(f"WS error: {e}")
    finally:
        ws_clients.discard(ws)
        log.info(f"🔌 Stream Dock disconnected (total: {len(ws_clients)})")


# ---------------------------------------------------------------------------
# DeepSeek Proxy — the core: injects hardware state into prompts
# Supports both Anthropic Messages API (Claude Code) and OpenAI Chat Completions.
# ---------------------------------------------------------------------------


def _inject_into_body(body: dict, injection: str, format_type: str) -> dict:
    """Inject hardware state into the request body. Modifies in-place."""
    if format_type == "anthropic":
        # Anthropic Messages API: append to system prompt
        if "system" in body and isinstance(body["system"], str):
            body["system"] += injection
        elif "system" in body and isinstance(body["system"], list):
            # Anthropic system can be a list of text blocks
            body["system"].append({"type": "text", "text": injection})
        else:
            body["system"] = injection.strip()
    else:
        # OpenAI Chat Completions: append to last user message
        if "messages" in body and len(body["messages"]) > 0:
            last_msg = body["messages"][-1]
            if isinstance(last_msg.get("content"), str):
                last_msg["content"] += injection
            elif isinstance(last_msg.get("content"), list):
                last_msg["content"].append({"type": "text", "text": injection})
    return body


# ---- Anthropic Messages API (Claude Code extension) ----
# Claude Code sends to both /messages and /v1/messages with ?beta=true


@app.post("/messages")
@app.post("/v1/messages")
async def proxy_anthropic(request: Request):
    """Anthropic Messages API proxy — used by Claude Code with ANTHROPIC_BASE_URL."""
    state = get_state()
    state.set_traffic(TrafficLight.YELLOW)

    # Resolve request BEFORE creating generator (avoids async-generator deadlock)
    try:
        body = await request.json()
    except Exception:
        state.set_traffic(TrafficLight.RED, error_msg="Invalid JSON")
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    injection = state.build_injection()
    log.info(f"Injecting [anthropic]: [{state.mode}] [{state.effort}]")
    body = _inject_into_body(body, injection, "anthropic")

    headers = {}
    for k, v in request.headers.items():
        kl = k.lower()
        if kl not in ("host", "content-length", "transfer-encoding"):
            headers[k] = v

    target_url = DEEPSEEK_ANTHROPIC_URL

    # Streaming generator — resolved data via closure, no awaits needed
    async def stream():
        all_chunks = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                async with client.stream("POST", target_url, json=body, headers=headers) as resp:
                    log.info(f"DeepSeek streaming status={resp.status_code}")
                    async for chunk in resp.aiter_bytes():
                        all_chunks.append(chunk)
                        yield chunk

            # After stream: check if AI needs user input (question, confirmation, etc.)
            full = b"".join(all_chunks).decode("utf-8", errors="ignore")
            tail = full[-2000:] if len(full) > 2000 else full
            t = tail.lower()

            # Find the LAST stop_reason (allow whitespace in JSON)
            import re
            stops = re.findall(r'"stop_reason"\s*:\s*"([^"]+)"', full)
            last_stop = stops[-1] if stops else "unknown"
            log.info(f"Stream done — last_stop={last_stop}")

            # Only check questions if stop_reason is unknown/missing
            has_question = False
            if last_stop not in ("end_turn", "tool_use", "max_tokens", "stop_sequence"):
                # Strict patterns — only clear direct questions
                strict_questions = [
                    "soll ich", "möchtest du", "willst du",
                    "shall i", "would you like", "do you want me",
                    "continue?", "proceed?", "fortfahren?",
                    "is that ok?", "does that look right?",
                    "confirm?", "bestätigen?",
                    "what would you",
                ]
                has_question = any(p in tail.lower() for p in strict_questions)
                # Also check: "?" as last non-whitespace char of the tail
                if not has_question:
                    stripped = tail.rstrip()
                    has_question = stripped.endswith("?")

            # Only finalize if no newer request changed the state
            if state.traffic_light == TrafficLight.YELLOW:
                if last_stop == "tool_use":
                    state.set_traffic(TrafficLight.RED, error_msg="Befehl wartet — genehmigen!")
                    log.info("last_stop=tool_use → RED")
                elif last_stop in ("end_turn", "max_tokens", "stop_sequence"):
                    state.set_traffic(TrafficLight.GREEN)
                    log.info(f"last_stop={last_stop} → GREEN")
                elif has_question:
                    state.set_traffic(TrafficLight.RED, error_msg="Rückfrage — du bist dran!")
                    log.info("Question → RED")
                else:
                    state.set_traffic(TrafficLight.GREEN)
                    log.info("No action needed → GREEN")
            else:
                log.info(f"Stream ended but state already {state.traffic_light.value} — skipping finalize")
        except Exception as e:
            if state.traffic_light == TrafficLight.YELLOW:
                state.set_traffic(TrafficLight.RED, error_msg=str(e))
            log.error(f"Stream error: {e}")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        status_code=200,
        headers={
            "X-DeckAI-Proxy": "1",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.options("/messages")
@app.options("/v1/messages")
async def anthropic_cors():
    return JSONResponse(
        content={},
        headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"},
    )


# ---- OpenAI Chat Completions (Other extensions / direct API) ----


@app.post("/v1/chat/completions")
async def proxy_openai_v1(request: Request):
    """OpenAI Chat Completions proxy."""
    state = get_state()
    state.set_traffic(TrafficLight.YELLOW)

    try:
        body = await request.json()
    except Exception:
        state.set_traffic(TrafficLight.RED, error_msg="Invalid JSON")
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    injection = state.build_injection()
    log.info(f"Injecting [openai]: [{state.mode}] [{state.effort}]")
    body = _inject_into_body(body, injection, "openai")

    headers = {}
    for k, v in request.headers.items():
        kl = k.lower()
        if kl not in ("host", "content-length", "transfer-encoding"):
            headers[k] = v

    target_url = DEEPSEEK_OPENAI_URL

    async def stream():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                async with client.stream("POST", target_url, json=body, headers=headers) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            if state.traffic_light == TrafficLight.YELLOW:
                state.set_traffic(TrafficLight.GREEN)
        except Exception as e:
            if state.traffic_light == TrafficLight.YELLOW:
                state.set_traffic(TrafficLight.RED, error_msg=str(e))
            log.error(f"Stream error: {e}")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        status_code=200,
        headers={
            "X-DeckAI-Proxy": "1",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/chat/completions")
async def proxy_openai(request: Request):
    return await proxy_openai_v1(request)


@app.options("/v1/chat/completions")
@app.options("/chat/completions")
async def openai_cors():
    return JSONResponse(
        content={},
        headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"},
    )


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    # Pre-generate button images
    from image_gen import save_all_to_disk

    save_all_to_disk()

    uvicorn.run(
        "deckai.cockpit:app",
        host="127.0.0.1",
        port=PROXY_PORT,
        reload=False,
        log_level="info",
    )
