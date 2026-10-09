import json
import tempfile
import unittest
from pathlib import Path

from divoom_pet.daemon.moods import VARIANT_EVERY_S, MoodSet, describe, moods_from_dir, variant_for
from divoom_pet.sprites import State


def _write(d, name, color=(1, 2, 3), frames=1):
    flat = [c for _ in range(256) for c in color]
    (Path(d) / f"{name}.json").write_text(json.dumps(
        {"name": name, "loop": True, "frames": [{"ms": 125, "px": flat}] * frames}))


def _color(loop):
    return [frame[0] for frame, _ms in loop]


class MoodSetTests(unittest.TestCase):
    def test_groups_main_and_variants(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "coding")
            _write(d, "coding.whiteboard")
            _write(d, "sporty.tea")
            _write(d, "sporty.yoga")
            _write(d, "nope.thing")  # not a mood
            moods = moods_from_dir(Path(d))
        self.assertEqual(set(moods), {State.CODING, State.SPORTY})
        self.assertIsNotNone(moods[State.CODING].main)
        self.assertEqual(list(moods[State.CODING].variants), ["whiteboard"])
        self.assertIsNone(moods[State.SPORTY].main)
        self.assertEqual(describe(moods), "coding(whiteboard), sporty(tea, yoga)")

    def test_variants_only_rotate_without_repeats(self):
        a, b = [((1, 1, 1), 125)], [((2, 2, 2), 125)]
        m = MoodSet(variants={"a": [([(1, 1, 1)] * 256, 125)], "b": [([(2, 2, 2)] * 256, 125)]})
        picks = [_color(m.next_loop())[0] for _ in range(6)]
        for prev, cur in zip(picks, picks[1:]):
            self.assertNotEqual(prev, cur)

    def test_main_with_variants_leads_with_a_variant_every_minute(self):
        main = [([(9, 9, 9)] * 256, 125)]
        var = [([(5, 5, 5)] * 256, 125)]
        m = MoodSet(main=main, variants={"duck": var})
        self.assertEqual(_color(m.next_loop(now=0.0)), [(9, 9, 9)])          # clock starts
        self.assertEqual(_color(m.next_loop(now=30.0)), [(9, 9, 9)])         # not yet
        self.assertEqual(_color(m.next_loop(now=VARIANT_EVERY_S)), [(5, 5, 5), (9, 9, 9)])
        self.assertEqual(_color(m.next_loop(now=VARIANT_EVERY_S + 1)), [(9, 9, 9)])


    def test_keyed_variant_falls_back_to_main(self):
        main = [([(9, 9, 9)] * 256, 125)]
        bash = [([(1, 1, 1)] * 256, 125)]
        m = MoodSet(main=main, variants={"bash": bash})
        self.assertEqual(_color(m.keyed("bash")), [(1, 1, 1)])
        self.assertEqual(_color(m.keyed("read")), [(9, 9, 9)])   # no read variant
        self.assertEqual(_color(m.keyed("")), [(9, 9, 9)])

    def test_keyed_without_main_rotates_variants(self):
        a = [([(1, 1, 1)] * 256, 125)]
        b = [([(2, 2, 2)] * 256, 125)]
        m = MoodSet(variants={"dance": a, "spin": b})
        seen = {_color(m.keyed(""))[0] for _ in range(2)}
        self.assertEqual(seen, {(1, 1, 1), (2, 2, 2)})

    def test_variant_for_notes(self):
        self.assertEqual(variant_for(State.TOOL_USE, "Grep"), "read")
        self.assertEqual(variant_for(State.TOOL_USE, "mcp__x"), "")
        self.assertEqual(variant_for(State.ALERT, "Claude needs your permission to use Bash"), "permission")
        self.assertEqual(variant_for(State.ALERT, "Claude is waiting for your input"), "waiting")
        self.assertEqual(variant_for(State.HAPPY, "done"), "")

if __name__ == "__main__":
    unittest.main()
