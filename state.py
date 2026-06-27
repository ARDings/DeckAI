"""
DeckAI State Management
Centralized state for the AI Cockpit — one source of truth for all hardware dials and status.
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List

# --- Enums ---

class TrafficLight(str, Enum):
    GREEN = "green"       # Bereit / idle
    YELLOW = "yellow"     # Arbeitet / processing
    RED = "red"           # Error / problem

class EffortLevel(str, Enum):
    LOW = "Low (Short)"
    MEDIUM = "Medium"
    HIGH = "High (Detailed)"
    MAX = "Max (Deep Reasoning)"

class WorkMode(str, Enum):
    CHAT = "Chat"
    PLANNING = "Planning & Architecture"
    AGENT = "Code Agent"
    REVIEW = "Review & Refactor"

# --- Ordered lists for dial rotation ---

EFFORT_LEVELS = [e.value for e in EffortLevel]
WORK_MODES = [m.value for m in WorkMode]


@dataclass
class CockpitState:
    """Mutable singleton holding all hardware-cockpit state."""

    traffic_light: TrafficLight = TrafficLight.GREEN
    effort_idx: int = 2          # Start at High (Detailed)
    mode_idx: int = 2            # Start at Code Agent
    error_message: str = ""

    # Callback-based observers: called on any state change
    _listeners: List[Callable] = field(default_factory=list, repr=False)

    # --- Properties ---

    @property
    def effort(self) -> str:
        return EFFORT_LEVELS[self.effort_idx]

    @property
    def mode(self) -> str:
        return WORK_MODES[self.mode_idx]

    # --- Dial mutations ---

    def dial_effort_up(self):
        self.effort_idx = (self.effort_idx + 1) % len(EFFORT_LEVELS)
        self._notify()

    def dial_effort_down(self):
        self.effort_idx = (self.effort_idx - 1) % len(EFFORT_LEVELS)
        self._notify()

    def dial_mode_up(self):
        self.mode_idx = (self.mode_idx + 1) % len(WORK_MODES)
        self._notify()

    def dial_mode_down(self):
        self.mode_idx = (self.mode_idx - 1) % len(WORK_MODES)
        self._notify()

    # --- Traffic light ---

    def set_traffic(self, light: TrafficLight, error_msg: str = ""):
        self.traffic_light = light
        self.error_message = error_msg
        self._notify()

    # --- Prompt injection ---

    def build_injection(self) -> str:
        """Returns the system-level prompt override to inject into the next request."""
        return (
            f"\n\n[SYSTEM OVERRIDE VIA HARDWARE DIALS]\n"
            f"Work Mode: Act strictly as a {self.mode}.\n"
            f"Effort Level: {self.effort}. Adjust your verbosity and depth accordingly.\n"
            f"Current Status: The cockpit traffic light is {self.traffic_light.value}."
        )

    # --- Observer pattern (sync for simplicity) ---

    def on_change(self, callback: Callable):
        """Register a callback(current_state) to be called on every state change."""
        self._listeners.append(callback)

    def _notify(self):
        for cb in self._listeners:
            try:
                cb(self)
            except Exception:
                pass  # Never let a listener crash the state


# --- Global singleton ---

_state: CockpitState | None = None


def get_state() -> CockpitState:
    global _state
    if _state is None:
        _state = CockpitState()
    return _state
