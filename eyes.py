"""
DeckAI Eyes — ULANZI TC001 via AWTRIX3.
GREEN/YELLOW = animated eyes, RED = eyes for 2s then "Help!".
State resets immediately when leaving RED.
"""

import asyncio
import logging
import os
import time
import httpx

log = logging.getLogger("deckai.eyes")

TC001_IP = os.environ.get("TC001_IP", "")
TC001_ENABLED = bool(TC001_IP)

ANIMATIONS = {
    "green_idle": [
        # Friendly messages during long idle — green, centered
        (" Coding? ",  [0, 255, 100], 2500),
        ("  Work?  ",  [0, 230, 80],  2500),
        ("   Hi!   ",  [0, 255, 100], 2000),
        ("You Rock!",  [0, 230, 80],  3000),
    ],
    "green": [
        ("   0   0   ", [0, 255, 100], 3000),
        ("  0   0    ", [0, 240, 90], 2200),
        ("     0   0 ", [0, 240, 90], 2200),
        ("  0   0    ", [0, 255, 100], 3000),
        ("   -   -    ", [0, 150, 60], 450),
        ("  0   0    ", [0, 255, 100], 3000),
        ("0   0      ", [0, 240, 90], 2200),
        ("  0   0    ", [0, 255, 100], 3000),
        ("      0   0", [0, 240, 90], 2200),
    ],
    "yellow": [
        ("   0   0  ", [255, 200, 0], 800),
        ("  0   0   ", [255, 180, 0], 600),
        (" 0   0    ", [255, 200, 0], 700),
        ("  0   0   ", [255, 180, 0], 800),
        ("   -   -  ", [200, 150, 0], 200),
        ("   0   0  ", [255, 200, 0], 700),
        ("     0   0", [255, 180, 0], 600),
    ],
    "red_eyes": [
        ("   0   0  ", [255, 40, 40], 500),
        ("  0   0   ", [255, 60, 60], 400),
        ("   0   0  ", [255, 40, 40], 500),
        ("   -   -  ", [200, 20, 20], 150),
        ("   0   0  ", [255, 40, 40], 450),
        (" 0   0    ", [255, 60, 60], 400),
    ],
    "red_help": [
        (" Help! ", [255, 40, 40], 700),
        (" Help! ", [255, 60, 60], 600),
        (" Help! ", [255, 40, 40], 700),
        (" Help! ", [255, 50, 50], 600),
    ],
}


class TC001Eyes:
    def __init__(self, ip: str = TC001_IP):
        self.ip = ip
        self._state = "green"
        self._running = False
        self._task: asyncio.Task | None = None
        self._state_since = 0.0

    async def start(self):
        if not TC001_ENABLED:
            log.info("Eyes: TC001 not configured (set TC001_IP env var)")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(f"Eyes: started -> {self.ip}")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                await c.post(f"http://{self.ip}/api/custom",
                    json={"text":"","color":[0,0,0],"background":[0,0,0],"lifetime":100,"icon":-1})
        except Exception:
            pass

    def set_state(self, state: str):
        if state != self._state:
            self._state_since = time.monotonic()
        self._state = state

    def _choose_key(self):
        if self._state == "red":
            elapsed = time.monotonic() - self._state_since
            return "red_help" if elapsed > 2.0 else "red_eyes"
        return self._state

    async def _run(self):
        key = "green"
        frame = 0
        _idle_since = 0.0
        _idle_message_shown = False
        async with httpx.AsyncClient(timeout=3) as client:
            while self._running:
                new_key = self._choose_key()
                prev_key = key
                if new_key != key:
                    key = new_key
                    frame = 0
                    if key == "green" and not _idle_since:
                        _idle_since = time.monotonic()

                # Idle messages: if green for ~2.5 min, show a friendly message
                if key == "green" and prev_key == "green_idle":
                    # Just returned from idle message — reset timer
                    _idle_since = time.monotonic()
                    _idle_message_shown = False
                elif key == "green":
                    if time.monotonic() - _idle_since > 150 and not _idle_message_shown:
                        key = "green_idle"
                        frame = 0
                        _idle_message_shown = True
                elif key != "green_idle":
                    _idle_since = time.monotonic()
                    _idle_message_shown = False

                seq = ANIMATIONS.get(key, ANIMATIONS["green"])
                if frame >= len(seq):
                    frame = 0

                text, color, lifetime = seq[frame]
                try:
                    await client.post(f"http://{self.ip}/api/custom", json={
                        "text": text, "color": color,
                        "background": [0, 0, 0], "lifetime": lifetime + 200,
                        "textCase": 0, "icon": -1,
                        "hold": True,
                    })
                except Exception:
                    pass

                # Sleep in 50ms chunks for faster state change detection
                state_at_start = self._state
                remaining = lifetime / 1000.0
                while remaining > 0 and self._running:
                    chunk = min(0.05, remaining)
                    await asyncio.sleep(chunk)
                    remaining -= chunk
                    if self._state != state_at_start:
                        break
                if self._state == state_at_start:
                    frame += 1


_eyes: TC001Eyes | None = None

def get_eyes() -> TC001Eyes:
    global _eyes
    if _eyes is None:
        _eyes = TC001Eyes()
    return _eyes
