"""Unit tests for the live-content plumbing in PetController (overlays, takeovers,
agent tally). These exercise the data plumbing only — no render loop / bridge IO."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from divoom_pet.daemon.bridge import DitooBridge
from divoom_pet.daemon.moods import moods_from_dir
from divoom_pet.daemon.state_machine import PetController
from divoom_pet.render.compositor import CountBadge, ProgressBar, compose
from divoom_pet.sprites import State


def _controller() -> PetController:
    # simulate=True bridge: no subprocess, no Bluetooth; we never start the loop.
    bridge = DitooBridge(Path("nonexistent"), mac="00:00:00:00:00:00", simulate=True)
    return PetController(bridge=bridge)


class OverlayTests(unittest.TestCase):
    def test_set_overlay_is_immutable_swap(self):
        c = _controller()
        before = c._overlays
        c.set_overlay("progress", ProgressBar(value=0.5))
        self.assertIsNot(c._overlays, before)  # new dict, not mutated in place
        self.assertIn("progress", c._overlays)

    def test_clear_one_overlay(self):
        c = _controller()
        c.set_overlay("progress", ProgressBar(value=0.5))
        c.set_overlay("badge", CountBadge(count=1))
        c.clear_overlay("progress")
        self.assertNotIn("progress", c._overlays)
        self.assertIn("badge", c._overlays)

    def test_clear_all_overlays(self):
        c = _controller()
        c.set_overlay("progress", ProgressBar(value=0.5))
        c.set_overlay("badge", CountBadge(count=1))
        c.clear_overlay()
        self.assertEqual(c._overlays, {})


class TakeoverTests(unittest.TestCase):
    def test_queue_and_consume(self):
        c = _controller()
        c.play_takeover([([(0, 0, 0)] * 256, 100)])
        self.assertIsNotNone(c._pop_takeover())
        self.assertIsNone(c._pop_takeover())  # consumed once

    def test_empty_takeover_ignored(self):
        c = _controller()
        c.play_takeover([])
        self.assertIsNone(c._pop_takeover())


class AgentTallyTests(unittest.TestCase):
    def test_increments_and_shows_badge(self):
        c = _controller()
        self.assertEqual(c.agent_came_home(), 1)
        self.assertEqual(c.agent_came_home(), 2)
        badge = c._overlays.get("badge")
        self.assertIsInstance(badge, CountBadge)
        self.assertEqual(badge.count, 2)

    def test_badge_disabled_still_counts_and_pokes(self):
        c = _controller()
        c.agent_badge = False
        self.assertEqual(c.agent_came_home(), 1)
        self.assertEqual(c.agent_came_home(), 2)
        self.assertNotIn("badge", c._overlays)
        self.assertEqual(c._state, State.POKE)

    def test_reset_zeroes_and_drops_badge(self):
        c = _controller()
        c.agent_came_home()
        c.reset_agents()
        self.assertEqual(c._agents_home, 0)
        self.assertNotIn("badge", c._overlays)


class MoodOverrideTests(unittest.TestCase):
    def _write(self, d, name, color=(1, 2, 3), frames=2):
        flat = [c for _ in range(256) for c in color]
        (Path(d) / f"{name}.json").write_text(json.dumps(
            {"name": name, "loop": True, "frames": [{"ms": 125, "px": flat}] * frames}))

    def test_loads_only_mood_names(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "happy")
            self._write(d, "fireworks")  # a regular asset, not a mood
            moods = moods_from_dir(Path(d))
        self.assertEqual(list(moods), [State.HAPPY])
        self.assertEqual(len(moods[State.HAPPY].main), 2)

    def test_missing_dir_is_empty(self):
        self.assertEqual(moods_from_dir(Path("/no/such/moods/dir")), {})

    def test_override_replaces_builtin_and_composes(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "happy", color=(9, 8, 7))
            c = _controller()
            c.moods = moods_from_dir(Path(d))
        anim = c.animation_for(State.HAPPY)
        self.assertEqual(len(anim), 2)
        frame, ms = anim[0]
        self.assertEqual(ms, 125)
        self.assertEqual(compose(frame)[0], (9, 8, 7))
        # states without an override keep the built-in sprites
        self.assertTrue(hasattr(c.animation_for(State.ALERT)[0][0], "rows"))


    def test_tool_use_follows_the_running_tool(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "tool_use", color=(9, 9, 9))
            self._write(d, "tool_use.bash", color=(1, 1, 1))
            c = _controller()
            c.moods = moods_from_dir(Path(d))
        c.set_state(State.TOOL_USE, note="Bash")
        self.assertEqual(compose(c.animation_for(State.TOOL_USE)[0][0])[0], (1, 1, 1))
        c.set_state(State.TOOL_USE, note="Read")  # same state, new tool
        self.assertEqual(compose(c.animation_for(State.TOOL_USE)[0][0])[0], (9, 9, 9))

class TimeoutLoopTests(unittest.TestCase):
    """Timed states end on the loop boundary nearest their timeout."""

    def _hatched(self, seconds_ago: float) -> PetController:
        c = _controller()
        c._state = State.HATCH  # timeout 3.5 s
        c._state_started_at = time.time() - seconds_ago
        return c

    def test_long_loop_plays_once(self):
        c = self._hatched(3.0)
        c._maybe_auto_transition(loop_s=3.0)   # a 2nd loop would end at 6.0 s
        self.assertEqual(c._state, State.IDLE)

    def test_short_loop_repeats_until_timeout(self):
        c = self._hatched(2.2)
        c._maybe_auto_transition(loop_s=2.2)   # 4.4 s overshoots less than 2.2 falls short
        self.assertEqual(c._state, State.HATCH)


class IdleLadderTests(unittest.TestCase):
    """IDLE --(bored)--> SPORTY --(sleep)--> SLEEPING, driven by the idle clock.

    We drive _maybe_auto_transition() directly and fake elapsed time by back-dating
    the timestamps, so no wall-clock waiting and no render loop is needed."""

    def _idle_since(self, seconds_ago: float) -> PetController:
        c = _controller()
        c.idle_to_bored = 60.0
        c.idle_to_sleep = 300.0
        c._state = State.IDLE
        now = time.time()
        c._last_activity_at = now - seconds_ago
        c._state_started_at = now - seconds_ago
        return c

    def test_stays_idle_before_bored(self):
        c = self._idle_since(30)
        c._maybe_auto_transition()
        self.assertEqual(c._state, State.IDLE)

    def test_idle_to_sporty_after_bored(self):
        c = self._idle_since(90)  # past bored (60), before sleep (300)
        c._maybe_auto_transition()
        self.assertEqual(c._state, State.SPORTY)

    def test_sporty_to_sleeping_after_sleep_threshold(self):
        c = self._idle_since(90)
        c._maybe_auto_transition()
        self.assertEqual(c._state, State.SPORTY)
        # Now age it past the sleep threshold and tick again.
        c._last_activity_at = time.time() - 310
        c._maybe_auto_transition()
        self.assertEqual(c._state, State.SLEEPING)

    def test_activity_resumed_mid_workout_returns_to_idle(self):
        c = self._idle_since(90)
        c._maybe_auto_transition()
        self.assertEqual(c._state, State.SPORTY)
        c.touch()  # you came back — resets the idle clock
        c._maybe_auto_transition()
        self.assertEqual(c._state, State.IDLE)

    def test_ladder_does_not_reset_idle_clock(self):
        # Crossing into SPORTY must NOT count as activity, or he'd never reach sleep.
        c = self._idle_since(90)
        before = c._last_activity_at
        c._maybe_auto_transition()
        self.assertEqual(c._last_activity_at, before)

    def test_bored_after_sleep_misconfig_sleeps(self):
        # If bored >= sleep, the sleep check wins so he still naps (never stuck).
        c = self._idle_since(90)
        c.idle_to_bored = 500.0
        c.idle_to_sleep = 60.0
        c._maybe_auto_transition()
        self.assertEqual(c._state, State.SLEEPING)


if __name__ == "__main__":
    unittest.main()
