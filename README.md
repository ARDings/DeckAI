# DeckAI — Hardware AI Cockpit

Physical control deck for AI-assisted coding. Stream Dock N3/N3e hardware buttons change how the AI behaves inside VS Code via transparent prompt injection.

## How It Works

```
Stream Dock (HTTP)  -->  DeckAI Cockpit (FastAPI :8000)  -->  DeepSeek API
                         |  Prompt Injection
                         |  [Effort + Mode + Status]
                         v
                    VS Code Claude Code
```

1. Hardware buttons on the Stream Dock control **effort level** and **work mode**.
2. The Python proxy stores the current state and injects it into every AI request.
3. Traffic light buttons display the AI's status: green (ready), yellow (processing), red (needs input).
4. The AI adapts its behavior based on your physical hardware settings -- without you typing a word.

## Quick Start

```bash
git clone https://github.com/Cspin/DeckAI.git
cd DeckAI
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
python -m deckai.setup_icons
python -m deckai.image_gen
```

### Configure VS Code

Edit `~/.claude/settings.json` to point at the proxy:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8000",
    "ANTHROPIC_AUTH_TOKEN": "sk-your-deepseek-api-key",
    "ANTHROPIC_MODEL": "deepseek-v4-pro"
  }
}
```

### Run

```bash
run.bat
# or: python -m uvicorn deckai.cockpit:app --host 127.0.0.1 --port 8000
```

Dashboard at **http://127.0.0.1:8000**.

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/messages` | POST | Anthropic Messages API proxy |
| `/v1/chat/completions` | POST | OpenAI Chat Completions proxy |
| `/ws` | WebSocket | Live state + button images for Stream Dock |
| `/dial/effort?dir=up\|down` | GET | Cycle effort level (Low/Medium/High/Max) |
| `/dial/mode?dir=up\|down` | GET | Cycle work mode (Chat/Planning/Agent/Review) |
| `/focus/vscode` | POST | Bring VS Code to foreground |
| `/answer/{text}` | POST | Type text into the active window |
| `/state` | GET | Current cockpit state as JSON |
| `/` | GET | Live dashboard |

## State Model

| Control | Values | Description |
|---------|--------|-------------|
| Effort | Low (Short), Medium, High (Detailed), Max (Deep Reasoning) | Controls response depth and verbosity |
| Mode | Chat, Planning & Architecture, Code Agent, Review & Refactor | Controls AI persona |
| Traffic Light | green, yellow, red | AI status: ready, processing, needs input |

## Prompt Injection

On every request the proxy appends a system instruction to the last message:

```
[SYSTEM OVERRIDE VIA HARDWARE DIALS]
Work Mode: Act strictly as a Code Agent.
Effort Level: High (Detailed). Adjust your verbosity and depth accordingly.
Current Status: The cockpit traffic light is green.
```

The AI changes its behavior based on your physical hardware settings. The injection is invisible to you.

## Traffic Light Logic

| Trigger | Light |
|---------|-------|
| Stream starts | Yellow (processing) |
| `stop_reason: tool_use` in response | Red (needs approval) |
| Direct question detected in text | Red (needs answer) |
| `stop_reason: end_turn`, no question | Green (done) |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPSEEK_ANTHROPIC_URL` | `https://api.deepseek.com/anthropic/messages` | Backend API (Anthropic format) |
| `DEEPSEEK_OPENAI_URL` | `https://api.deepseek.com/v1/chat/completions` | Backend API (OpenAI format) |
| `DECKAI_PORT` | `8000` | Server port |

Default effort level can be changed in `deckai/state.py` by adjusting `effort_idx` (0-3).

## Project Structure

```
├── cockpit.py              # FastAPI server (HTTP, WS, proxy, detection)
├── state.py                # State machine (effort, mode, traffic light)
├── image_gen.py            # Button image generator (80x80 px)
├── setup_icons.py          # Plugin icon generator
├── static/                 # Generated button images
├── com.deckai2.cockpit.sdPlugin/  # Stream Dock plugin
├── run.bat                 # Windows launcher
├── requirements.txt
├── README.md
└── LICENSE
```

## License

MIT
