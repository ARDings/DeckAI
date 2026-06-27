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

from .state import CockpitState, TrafficLight, get_state
from .image_gen import get_button_png_base64, STATIC_DIR, save_all_to_disk

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


async def broadcast_state(state: CockpitState):
    """Push current cockpit state to all connected Stream Dock plugins."""
    payload = {
        "type": "state_update",
        "traffic_light": state.traffic_light.value,
        "effort": state.effort,
        "effort_idx": state.effort_idx,
        "mode": state.mode,
        "mode_idx": state.mode_idx,
        "error_message": state.error_message,
        "buttons": {
            "btn_traffic_green_active": get_button_png_base64("traffic_green_active"),
            "btn_traffic_yellow_active": get_button_png_base64("traffic_yellow_active"),
            "btn_traffic_red_active": get_button_png_base64("traffic_red_active"),
            "btn_traffic_green_inactive": get_button_png_base64("traffic_green_inactive"),
            "btn_traffic_yellow_inactive": get_button_png_base64("traffic_yellow_inactive"),
            "btn_traffic_red_inactive": get_button_png_base64("traffic_red_inactive"),
            "btn_effort": get_button_png_base64(f"effort_{state.effort}"),
            "btn_vscode": get_button_png_base64("vscode_focus"),
            "btn_mode": get_button_png_base64(f"mode_{state.mode}"),
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
    """Sync callback → schedules async broadcast."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_state(state))
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
    log.info(f"DeckAI Cockpit started")
    log.info(f"  Anthropic -> {DEEPSEEK_ANTHROPIC_URL}")
    log.info(f"  OpenAI   -> {DEEPSEEK_OPENAI_URL}")
    log.info(f"WebSocket: ws://127.0.0.1:{PROXY_PORT}/ws")
    log.info(f"Dial API:  http://127.0.0.1:{PROXY_PORT}/dial/effort?dir=up")
    log.info(f"Claude Code: http://127.0.0.1:{PROXY_PORT}/messages")
    yield
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


async def _proxy_stream(request: Request, target_url: str, format_type: str):
    """
    Intercept request, inject cockpit state, forward to DeepSeek,
    and manage the traffic light.
    """
    state = get_state()

    # Set traffic light to YELLOW (working)
    state.set_traffic(TrafficLight.YELLOW)

    try:
        body = await request.json()
    except Exception:
        state.set_traffic(TrafficLight.RED, error_msg="Invalid JSON in request body")
        yield 'data: {"error": "Invalid JSON body"}\n\n'
        return

    # 💥 THE MAGIC: inject hardware dial state into the prompt
    injection = state.build_injection()
    log.info(f"Injecting [{format_type}]: [{state.mode}] [{state.effort}]")
    body = _inject_into_body(body, injection, format_type)

    # Prepare headers — strip host/content-length, forward auth
    headers = {}
    for k, v in request.headers.items():
        kl = k.lower()
        if kl not in ("host", "content-length", "transfer-encoding"):
            headers[k] = v

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            log.info(f"Forwarding to: {target_url}")
            async with client.stream(
                "POST",
                target_url,
                json=body,
                headers=headers,
            ) as response:
                log.info(f"DeepSeek status={response.status_code}, content-type={response.headers.get('content-type')}")
                # Read entire body first to debug, then yield
                content = await response.aread()
                log.info(f"DeepSeek body length: {len(content)} bytes, first 300: {content[:300]}")
                yield content

        # Success → GREEN
        state.set_traffic(TrafficLight.GREEN)
        log.info("Stream complete — GREEN")

        # Success → GREEN
        state.set_traffic(TrafficLight.GREEN)
        log.info("Stream complete — GREEN")

    except httpx.ConnectError as e:
        state.set_traffic(TrafficLight.RED, error_msg=f"Connection to DeepSeek failed: {e}")
        log.error(f"Connection error: {e}")
        yield f'data: {{"error": "Proxy connection failed: {e}"}}\n\n'

    except httpx.ReadTimeout as e:
        state.set_traffic(TrafficLight.RED, error_msg=f"DeepSeek timeout: {e}")
        log.error(f"Timeout: {e}")
        yield f'data: {{"error": "DeepSeek timeout: {e}"}}\n\n'

    except Exception as e:
        state.set_traffic(TrafficLight.RED, error_msg=str(e))
        log.error(f"Unexpected error: {e}")
        yield f'data: {{"error": "{e}"}}\n\n'


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

            # After stream: check if AI asked a question
            full = b"".join(all_chunks).decode("utf-8", errors="ignore")
            # Count question marks in the last portion (the AI's final response)
            last_portion = full[-3000:] if len(full) > 3000 else full
            question_count = last_portion.count("?")
            if question_count > 0:
                state.set_traffic(TrafficLight.RED, error_msg=f"Rückfrage? ({question_count} Fragen)")
                log.info(f"Question detected — RED ({question_count} '?' found)")
            else:
                state.set_traffic(TrafficLight.GREEN)
        except Exception as e:
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
            state.set_traffic(TrafficLight.GREEN)
        except Exception as e:
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
    from .image_gen import save_all_to_disk

    save_all_to_disk()

    uvicorn.run(
        "deckai.cockpit:app",
        host="127.0.0.1",
        port=PROXY_PORT,
        reload=False,
        log_level="info",
    )
