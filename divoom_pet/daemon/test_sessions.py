"""Unit tests for the multi-session registry + mood→session mapping."""

import unittest

from divoom_pet.daemon.sessions import (
    TTL,
    SessionRegistry,
    session_state_for_mood,
)
from divoom_pet.render import (
    SESSION_FINISHED,
    SESSION_IDLE,
    SESSION_NEEDS_INPUT,
    SESSION_RUNNING,
)


class MoodMapTests(unittest.TestCase):
    def test_working_moods_map_to_running(self):
        for mood in ("thinking", "tool_use", "typing", "hatch", "poke"):
            self.assertEqual(session_state_for_mood(mood), SESSION_RUNNING)

    def test_happy_is_finished(self):
        self.assertEqual(session_state_for_mood("happy"), SESSION_FINISHED)

    def test_alert_is_needs_input(self):
        self.assertEqual(session_state_for_mood("alert"), SESSION_NEEDS_INPUT)

    def test_sleeping_is_idle(self):
        self.assertEqual(session_state_for_mood("sleeping"), SESSION_IDLE)

    def test_unknown_defaults_to_running(self):
        self.assertEqual(session_state_for_mood("nonsense"), SESSION_RUNNING)


class RegistryTests(unittest.TestCase):
    def test_snapshot_ordered_oldest_first(self):
        r = SessionRegistry()
        r.update("a", SESSION_RUNNING, 100.0)
        r.update("b", SESSION_FINISHED, 101.0)
        self.assertEqual(r.snapshot(), [("a", SESSION_RUNNING), ("b", SESSION_FINISHED)])
        self.assertEqual(r.states(), (SESSION_RUNNING, SESSION_FINISHED))

    def test_update_keeps_original_slot(self):
        r = SessionRegistry()
        r.update("a", SESSION_RUNNING, 100.0)
        r.update("b", SESSION_RUNNING, 101.0)
        r.update("a", SESSION_FINISHED, 102.0)  # 'a' changes state but keeps slot 0
        self.assertEqual([sid for sid, _ in r.snapshot()], ["a", "b"])

    def test_invalid_inputs_ignored(self):
        r = SessionRegistry()
        r.update("a", "bogus", 100.0)
        r.update("", SESSION_RUNNING, 100.0)
        self.assertEqual(r.snapshot(), [])

    def test_prune_expires_finished_before_running(self):
        r = SessionRegistry()
        r.update("done", SESSION_FINISHED, 0.0)
        r.update("live", SESSION_RUNNING, 0.0)
        r.prune(TTL[SESSION_FINISHED] + 1.0)  # past finished TTL, well within running TTL
        ids = [sid for sid, _ in r.snapshot()]
        self.assertEqual(ids, ["live"])

    def test_needs_input_lingers(self):
        r = SessionRegistry()
        r.update("wait", SESSION_NEEDS_INPUT, 0.0)
        r.prune(TTL[SESSION_FINISHED] + 1.0)
        self.assertIn("wait", [sid for sid, _ in r.snapshot()])

    def test_remove_drops_an_ended_session(self):
        r = SessionRegistry()
        r.update("gone", SESSION_NEEDS_INPUT, 0.0)
        r.update("live", SESSION_RUNNING, 0.0)
        r.remove("gone")
        r.remove("never-seen")
        self.assertEqual([sid for sid, _ in r.snapshot()], ["live"])


if __name__ == "__main__":
    unittest.main()
