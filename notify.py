"""
DeckAI Notify — Push notifications via ntfy.sh (free, open-source).
Sends push to your phone for AI status changes.
Rokid glasses + any Android notification mirror see these automatically.

Usage:
  set NTFY_TOPIC=your-secret-topic
  (optional) set NTFY_SERVER=https://ntfy.sh  (default)
"""

import asyncio
import logging
import os

import httpx

log = logging.getLogger("deckai.notify")

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NOTIFY_ENABLED = bool(NTFY_TOPIC)

# State change notifications — which transitions trigger a push
NOTIFY_TRANSITIONS = {
    "red":    ("Help needed!",          "AI needs you — check the screen.",   "high"),
    "green":  ("AI Ready",              "Task complete, ready to continue.", "min"),
    "yellow": None,
}


async def send_notification(state: str, message: str = ""):
    """Send a push notification via ntfy.sh."""
    if not NOTIFY_ENABLED:
        return

    config = NOTIFY_TRANSITIONS.get(state)
    if config is None:
        return  # no notification for this state

    title, body, priority = config
    full_body = f"{body}\n{message}" if message else body

    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(
                f"{NTFY_SERVER}/{NTFY_TOPIC}",
                data=full_body.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": priority,
                    "Tags": "robot",
                },
            )
            log.info(f"Notify: sent '{title}' (priority={priority})")
    except Exception as e:
        log.debug(f"Notify: failed to send ({e})")


# Track previous state + debounce notifications
_prev_state = "green"
_pending_task: asyncio.Task | None = None


async def _send_delayed(state: str, delay: float, message: str):
    """Wait `delay` seconds, then notify if state hasn't changed."""
    await asyncio.sleep(delay)
    if _prev_state == state:
        await send_notification(state, message)


def on_traffic_change(new_state: str, message: str = ""):
    """Notify only after state has been stable: RED 2s (Help), GREEN 5s."""
    global _prev_state, _pending_task
    if new_state != _prev_state:
        _prev_state = new_state
        try:
            loop = asyncio.get_running_loop()
            # Cancel any pending notification
            if _pending_task and not _pending_task.done():
                _pending_task.cancel()
            _pending_task = None

            if new_state == "red":
                _pending_task = loop.create_task(_send_delayed("red", 8.0, message))
            elif new_state == "green":
                _pending_task = loop.create_task(_send_delayed("green", 4.0, message))
        except RuntimeError:
            pass
