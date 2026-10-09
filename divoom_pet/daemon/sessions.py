"""Track the state of every live Claude Code session feeding the daemon.

One pet daemon serves all your sessions (they all POST to :7878), so it's the
natural place to aggregate a fleet view. Each session is keyed by its `session_id`;
its state is mapped from Clawd's mood (or set explicitly) and expires on a TTL so
dead sessions drop off the strip. `snapshot()` returns sessions ordered by age, so
each keeps a stable dot slot on the display.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, List, Tuple

from divoom_pet.render import (
    SESSION_FINISHED,
    SESSION_IDLE,
    SESSION_NEEDS_INPUT,
    SESSION_RUNNING,
)

# Clawd mood (State.value) → session state.
MOOD_TO_SESSION = {
    "hatch": SESSION_RUNNING,
    "thinking": SESSION_RUNNING,
    "typing": SESSION_RUNNING,
    "tool_use": SESSION_RUNNING,
    "coding": SESSION_RUNNING,
    "poke": SESSION_RUNNING,
    "happy": SESSION_FINISHED,
    "alert": SESSION_NEEDS_INPUT,
    "sleeping": SESSION_IDLE,
    "idle": SESSION_IDLE,
}

VALID_STATES = {SESSION_RUNNING, SESSION_FINISHED, SESSION_NEEDS_INPUT, SESSION_IDLE}

# Per-state time-to-live (seconds) since last update.
TTL = {
    SESSION_RUNNING: 300.0,       # a working session gone quiet for 5 min → drop
    SESSION_FINISHED: 90.0,       # show the green "done" dot briefly, then clear
    SESSION_NEEDS_INPUT: 1800.0,  # keep nagging for up to 30 min
    SESSION_IDLE: 120.0,
}


def session_state_for_mood(mood: str) -> str:
    return MOOD_TO_SESSION.get(mood, SESSION_RUNNING)


@dataclass(frozen=True)
class SessionInfo:
    state: str
    updated_at: float
    first_seen: float


class SessionRegistry:
    """Thread-safe map of session_id → SessionInfo. Immutable SessionInfo values are
    replaced wholesale on update (never mutated in place)."""

    def __init__(self):
        self._sessions: Dict[str, SessionInfo] = {}
        self._lock = threading.Lock()

    def update(self, session_id: str, state: str, now: float) -> None:
        if not session_id or state not in VALID_STATES:
            return
        with self._lock:
            prev = self._sessions.get(session_id)
            first_seen = prev.first_seen if prev else now
            self._sessions[session_id] = SessionInfo(state, now, first_seen)

    def remove(self, session_id: str) -> None:
        """Drop a session that has ended, so its dot leaves the strip at once."""
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items() if k != session_id}

    def prune(self, now: float) -> None:
        with self._lock:
            self._sessions = {
                sid: info
                for sid, info in self._sessions.items()
                if now - info.updated_at < TTL.get(info.state, 300.0)
            }

    def snapshot(self) -> List[Tuple[str, str]]:
        """(session_id, state) pairs, oldest first (stable dot slots)."""
        with self._lock:
            ordered = sorted(self._sessions.items(), key=lambda kv: kv[1].first_seen)
            return [(sid, info.state) for sid, info in ordered]

    def states(self) -> Tuple[str, ...]:
        """Just the states, in slot order — ready for a SessionBar."""
        return tuple(state for _, state in self.snapshot())
