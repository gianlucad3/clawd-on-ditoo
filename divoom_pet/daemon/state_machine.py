"""Pet state machine + animation loop.

The state machine has one current State. A background thread renders the
animation loop for the current state, pushing frames over the bridge.

Switching states is atomic: we cancel the current frame loop and restart with
the new animation. A state may auto-transition (e.g. ALERT -> IDLE after 4s).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from divoom_pet.render import COLORS, CountBadge, compose
from divoom_pet.sprites import DEFAULT_IDLE, IdleOpts, State, animation_for_state
from divoom_pet.voice.sounds import STATE_CHIRP, STATE_SPEAK, SoundPlayer

from .bridge import DitooBridge
from .moods import KEYED_STATES, MoodSet, variant_for

log = logging.getLogger("state")


# Auto-transition table: after T seconds in this state, fall back to fallback.
AUTO_TIMEOUTS = {
    State.ALERT: (3.0, State.IDLE),
    State.HAPPY: (2.6, State.IDLE),
    State.HATCH: (3.5, State.IDLE),
    State.TOOL_USE: (4.0, State.IDLE),
    State.TYPING: (8.0, State.IDLE),
    State.THINKING: (60.0, State.IDLE),  # safety net
    State.CODING: (60.0, State.IDLE),    # safety net; refreshed while actively coding
    State.POKE: (1.6, State.IDLE),
}

# Idle -> Sporty after N seconds: he gets restless and works out before napping.
IDLE_TO_BORED_AFTER = 60.0

# Idle -> Sleeping after N seconds with no activity. Generous so Clawd stays
# awake through normal reading/thinking pauses and only naps when you've left.
# Between BORED and SLEEP he's in the SPORTY state (jump rope, push-ups, …).
IDLE_TO_SLEEP_AFTER = 300.0


@dataclass
class PetController:
    bridge: DitooBridge
    sounds: Optional[SoundPlayer] = None
    brightness: int = 70
    idle_to_bored: float = IDLE_TO_BORED_AFTER
    idle_to_sleep: float = IDLE_TO_SLEEP_AFTER
    idle_opts: IdleOpts = field(default_factory=lambda: DEFAULT_IDLE)
    agent_badge: bool = True  # show the finished-subagent tally as a corner badge
    # Per-mood manifest animations (flat 16×16 frames) that replace the built-in
    # sprite animation for that state; see moods.py. Empty = all built-in.
    moods: Dict[State, MoodSet] = field(default_factory=dict)
    _state: State = State.IDLE
    _state_started_at: float = field(default_factory=time.time)
    _note: str = ""  # note of the last set_state (tool name, alert message…)
    _last_activity_at: float = field(default_factory=time.time)
    # Persistent data overlays (progress bar, count badge…), keyed by name and
    # swapped immutably. A one-shot `_takeover` animation, when queued, plays
    # before the mood loop resumes.
    _overlays: Dict[str, object] = field(default_factory=dict)
    _takeover: Optional[List] = None
    _takeover_queued: threading.Event = field(default_factory=threading.Event)
    _agents_home: int = 0  # running tally of finished subagents this session
    _stop: threading.Event = field(default_factory=threading.Event)
    _state_changed: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _loop_thread: Optional[threading.Thread] = None

    def start(self, initial_state: State = State.HATCH) -> None:
        # Tolerate an initial connection failure — the loop will keep retrying via
        # ensure_alive() so the daemon recovers when the Ditoo/channel comes back.
        try:
            self.bridge.start()
            self.bridge.set_brightness(self.brightness)
        except Exception as e:
            log.warning("bridge start failed (%s); will keep retrying in background", e)
        self._loop_thread = threading.Thread(target=self._run, daemon=True, name="pet-loop")
        self._loop_thread.start()
        self.set_state(initial_state, note="boot")

    def stop(self) -> None:
        self._stop.set()
        self._state_changed.set()
        self._takeover_queued.set()
        if self._loop_thread:
            self._loop_thread.join(timeout=1.5)
        self.bridge.stop()

    # ---------- public api ----------

    def set_state(self, state: State, note: str = "") -> None:
        with self._lock:
            self._note = note
            if state == self._state and state != State.HAPPY and state != State.ALERT:
                # Already in this state; ignore noisy re-entries (but allow re-triggers
                # for one-shot reactions like HAPPY / ALERT).
                self._last_activity_at = time.time()
                return
            log.info("state: %s -> %s  (%s)", self._state.value, state.value, note)
            self._state = state
            self._state_started_at = time.time()
            self._last_activity_at = time.time()
            self._state_changed.set()
        self._play_sounds_for(state)

    def _play_sounds_for(self, state: State) -> None:
        if not self.sounds:
            return
        chirp = STATE_CHIRP.get(state.value)
        if chirp:
            self.sounds.chirp(chirp)
        spoken = STATE_SPEAK.get(state.value)
        if spoken:
            self.sounds.speak(spoken)

    def current_state(self) -> State:
        with self._lock:
            return self._state

    def touch(self) -> None:
        """Mark recent activity; resets idle->sleep timer."""
        self._last_activity_at = time.time()

    def set_brightness(self, value: int) -> None:
        """Update display brightness now (best-effort; survives a dead bridge)."""
        self.brightness = value
        try:
            if self.bridge.is_alive():
                self.bridge.set_brightness(value)
        except Exception as e:
            log.debug("set_brightness failed: %s", e)

    def poke(self) -> None:
        """React to a clap: startle + delight, then settle back to idle."""
        self.set_state(State.POKE, note="clap")

    def toggle_sleep(self) -> None:
        """Double-clap: wake a sleeping crab, or send an awake one to nap."""
        if self.current_state() == State.SLEEPING:
            self.set_state(State.POKE, note="double-clap wake")
        else:
            self.set_state(State.SLEEPING, note="double-clap sleep")

    # ---------- live content (overlays + takeovers) ----------

    def set_overlay(self, key: str, overlay: object) -> None:
        """Add or replace a named persistent overlay (e.g. a progress bar). The
        overlay must have a `draw(canvas)` method. Immutable swap — we build a new
        dict so the render loop never sees a half-mutated structure."""
        with self._lock:
            self._overlays = {**self._overlays, key: overlay}
        self._state_changed.set()  # nudge the loop to repaint promptly

    def clear_overlay(self, key: Optional[str] = None) -> None:
        """Remove one overlay by key, or all overlays when key is None."""
        with self._lock:
            if key is None:
                self._overlays = {}
            else:
                self._overlays = {k: v for k, v in self._overlays.items() if k != key}
        self._state_changed.set()

    def get_overlay(self, key: str) -> Optional[object]:
        """Return the overlay registered under `key`, or None."""
        with self._lock:
            return self._overlays.get(key)

    def play_takeover(self, frames: List) -> None:
        """Queue a one-shot animation — a list of (frame, duration_ms) pairs — to
        play as soon as possible, after which the current mood resumes."""
        if not frames:
            return
        with self._lock:
            self._takeover = list(frames)
        self._takeover_queued.set()
        self._state_changed.set()

    def _pop_takeover(self) -> Optional[List]:
        with self._lock:
            pending = self._takeover
            self._takeover = None
            self._takeover_queued.clear()
            return pending

    def agent_came_home(self) -> int:
        """A subagent finished: tick the tally, show it as a corner badge, and play
        the delight (poke) reaction. Returns the new count."""
        with self._lock:
            self._agents_home += 1
            count = self._agents_home
        if self.agent_badge:
            self.set_overlay("badge", CountBadge(count=count, corner="tr", color=COLORS["yellow"]))
        self.set_state(State.POKE, note="agent home")
        return count

    def reset_agents(self) -> None:
        """New session / done: zero the tally and drop the badge."""
        with self._lock:
            self._agents_home = 0
        self.clear_overlay("badge")

    # ---------- internal loop ----------

    def _run(self) -> None:
        while not self._stop.is_set():
            # A queued one-shot takeover (e.g. a "MERGED" banner) wins this cycle.
            takeover = self._pop_takeover()
            if takeover is not None:
                self._play_frames(takeover)
                continue

            with self._lock:
                current = self._state
                idle_opts = self.idle_opts
            anim = self.animation_for(current, idle_opts)
            # Render the animation once, compositing live overlays per frame. After
            # it loops (uninterrupted) we re-check auto-transitions.
            interrupted = False
            for sprite, duration_ms in anim:
                if self._stop.is_set():
                    return
                with self._lock:
                    overlays = list(self._overlays.values())
                frame = compose(sprite, overlays)
                # Only push when connected; ensure_alive() reconnects (throttled)
                # without spamming, so a dropped link recovers on its own.
                if self.bridge.ensure_alive():
                    try:
                        self.bridge.push_image(frame)
                    except Exception as e:
                        log.debug("push_image failed: %s", e)
                # Wait the duration, but break early if state/overlay/takeover changed.
                if self._state_changed.wait(timeout=max(0.04, duration_ms / 1000.0)):
                    self._state_changed.clear()
                    interrupted = True
                    break
            if not interrupted:
                self._maybe_auto_transition(sum(ms for _, ms in anim) / 1000.0)

    def animation_for(self, state: State, idle_opts: IdleOpts = DEFAULT_IDLE) -> List:
        """One loop of (frame-or-sprite, duration_ms) for `state`: the mood
        override when there is one, else the built-in sprites."""
        override = self.moods.get(state)
        if override and state in KEYED_STATES:
            loop = override.keyed(variant_for(state, self._note))
        else:
            loop = override.next_loop() if override else None
        return loop or animation_for_state(state, idle_opts)

    def _play_frames(self, frames: List) -> None:
        """Push a raw (frame, duration_ms) animation once. Used for one-shot
        takeovers: a state or overlay change does not cut it short (the mood loop
        picks those up when it ends), only a newer takeover or stop() does."""
        for frame, duration_ms in frames:
            if self._stop.is_set():
                return
            if self.bridge.ensure_alive():
                try:
                    self.bridge.push_image(frame)
                except Exception as e:
                    log.debug("push_image failed: %s", e)
            if self._takeover_queued.wait(timeout=max(0.04, duration_ms / 1000.0)):
                return  # a newer takeover (or stop) replaces the rest of this one

    def _maybe_auto_transition(self, loop_s: float = 0.0) -> None:
        """Check timeouts after a full loop. `loop_s` is that loop's length: a
        timed state also ends early when one more loop would overshoot its timeout
        by more than it currently falls short, so a long one-shot mood (a 3 s
        hatch against a 3.5 s timeout) plays once instead of twice."""
        with self._lock:
            now = time.time()
            current = self._state
            elapsed = now - self._state_started_at
            idle_for = now - self._last_activity_at

            if current in AUTO_TIMEOUTS:
                timeout, fallback = AUTO_TIMEOUTS[current]
                if elapsed >= timeout or elapsed + loop_s - timeout > timeout - elapsed:
                    log.info("auto-transition: %s -> %s after %.1fs", current.value, fallback.value, elapsed)
                    self._state = fallback
                    self._state_started_at = now
                    self._state_changed.set()
                    return

            # Idle-life ladder: IDLE --(bored)--> SPORTY --(sleep)--> SLEEPING.
            # We mutate _state directly (not set_state) so _last_activity_at is left
            # untouched and the idle clock keeps counting toward the next rung.
            def _go(state: State) -> None:
                self._state = state
                self._state_started_at = now
                self._state_changed.set()

            if current == State.IDLE:
                if idle_for >= self.idle_to_sleep:  # sleep threshold first (handles bored>=sleep)
                    log.info("idle for %.0fs -> sleeping", idle_for)
                    _go(State.SLEEPING)
                elif idle_for >= self.idle_to_bored:
                    log.info("idle for %.0fs -> sporty (bored, working out)", idle_for)
                    _go(State.SPORTY)
            elif current == State.SPORTY:
                if idle_for >= self.idle_to_sleep:
                    log.info("worked out until %.0fs idle -> sleeping", idle_for)
                    _go(State.SLEEPING)
                elif idle_for < self.idle_to_bored:
                    log.info("activity resumed mid-workout -> idle")
                    _go(State.IDLE)
