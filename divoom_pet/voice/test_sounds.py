"""Unit tests for the live-voice layer (phrase slug, render args, cache/gating).

The actual macOS `say` call is monkeypatched out, so these run anywhere.
"""

import tempfile
import unittest
from pathlib import Path

import divoom_pet.voice.sounds as snd
from divoom_pet.voice.sounds import VOCAB, SoundPlayer, _phrase_slug


class PhraseSlugTests(unittest.TestCase):
    def test_normalizes_whitespace_and_case(self):
        self.assertEqual(_phrase_slug("Hello   There"), _phrase_slug("hello there"))

    def test_stable_and_prefixed(self):
        self.assertEqual(_phrase_slug("merged"), _phrase_slug("merged"))
        self.assertTrue(_phrase_slug("x").startswith("saylive_"))

    def test_vocab_phrases_have_distinct_slugs(self):
        slugs = {_phrase_slug(p) for p in VOCAB}
        self.assertEqual(len(slugs), len(VOCAB))


class RenderSayTests(unittest.TestCase):
    def test_builds_say_command_and_reports_success(self):
        calls = []
        inputs = []

        def fake_run(args, **kwargs):
            calls.append(args)
            inputs.append(kwargs.get("input"))
            Path(args[args.index("-o") + 1]).write_bytes(b"RIFF")  # simulate say writing a file
            return None

        orig = snd.subprocess.run
        snd.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as d:
                ok = snd.render_say_to_wav("--dangerous flag", Path(d) / "out.wav", voice="Zoe")
            self.assertTrue(ok)
            self.assertIn("-v", calls[0])
            self.assertIn("Zoe", calls[0])
            # Text goes on stdin, NOT argv — so a leading '-' can't become a say flag.
            self.assertEqual(inputs[0], "--dangerous flag")
            self.assertNotIn("--dangerous flag", calls[0])
        finally:
            snd.subprocess.run = orig


class SayCacheTests(unittest.TestCase):
    def _player(self, enabled=True, spoken_lines=True):
        sp = SoundPlayer.__new__(SoundPlayer)  # skip the heavy __init__
        sp.enabled = enabled
        sp.spoken_lines = spoken_lines
        sp.tts_voice = None
        sp._played = []
        sp._play_file = lambda p: sp._played.append(p)
        return sp

    def test_say_is_noop_when_disabled(self):
        sp = self._player(spoken_lines=False)
        sp.say("anything")
        self.assertEqual(sp._played, [])

    def test_cached_phrase_plays_without_rendering(self):
        sp = self._player()
        with tempfile.TemporaryDirectory() as d:
            orig_dir, orig_render = snd.SOUNDS_DIR, snd.render_say_to_wav
            snd.SOUNDS_DIR = Path(d)
            rendered = []
            snd.render_say_to_wav = lambda *a, **k: rendered.append(a)
            try:
                cached = Path(d) / f"{_phrase_slug('warm one')}.wav"
                cached.write_bytes(b"RIFF")
                sp._say_blocking("warm one")
            finally:
                snd.SOUNDS_DIR, snd.render_say_to_wav = orig_dir, orig_render
        self.assertEqual(sp._played, [cached])
        self.assertEqual(rendered, [])  # warm hit: no render

    def test_set_tts_voice_keeps_active_theme(self):
        # Regression: set_tts_voice must re-render with the player's theme, not 'chip'.
        sp = self._player()
        sp.theme = "marimba"
        sp.tts_voice = "OldVoice"
        sp.paths = {}
        sp._warm_vocab = lambda: None  # no-op the background re-warm
        captured = []
        orig_render, orig_dir = snd.render_all, snd.SOUNDS_DIR
        with tempfile.TemporaryDirectory() as d:
            snd.SOUNDS_DIR = Path(d)
            snd.render_all = lambda *a, **k: captured.append(k) or {}
            try:
                sp.set_tts_voice("NewVoice")
            finally:
                snd.render_all, snd.SOUNDS_DIR = orig_render, orig_dir
        self.assertTrue(captured)
        self.assertEqual(captured[-1].get("theme"), "marimba")

    def test_novel_phrase_renders_then_plays(self):
        sp = self._player()
        with tempfile.TemporaryDirectory() as d:
            orig_dir, orig_render = snd.SOUNDS_DIR, snd.render_say_to_wav
            snd.SOUNDS_DIR = Path(d)

            def fake_render(text, path, voice=None, **k):
                Path(path).write_bytes(b"RIFF")
                return True

            snd.render_say_to_wav = fake_render
            try:
                sp._say_blocking("a brand new phrase")
            finally:
                snd.SOUNDS_DIR, snd.render_say_to_wav = orig_dir, orig_render
        self.assertEqual(len(sp._played), 1)



class ScaledSpeechTests(unittest.TestCase):
    """Spoken lines follow the master volume; chirps are left alone."""

    def test_speech_is_scaled_and_chirps_untouched(self):
        import array
        import wave
        with tempfile.TemporaryDirectory() as d:
            orig_dir, orig_vol = snd.SOUNDS_DIR, snd.MASTER_VOLUME
            snd.SOUNDS_DIR = Path(d)
            try:
                snd.set_master_volume(0.25)
                pcm = array.array("h", [20000, -20000, 8000] * 10).tobytes()
                speech, chirp = Path(d) / "say_hatch_0.wav", Path(d) / "chirp_done_0.wav"
                snd.write_wav(speech, pcm)
                snd.write_wav(chirp, pcm)
                out = snd.scaled_speech(speech)
                self.assertNotEqual(out, speech)
                with wave.open(str(out)) as w:
                    got = array.array("h", w.readframes(w.getnframes()))
                self.assertEqual(list(got[:3]), [5000, -5000, 2000])
                self.assertEqual(snd.scaled_speech(chirp), chirp)
            finally:
                snd.SOUNDS_DIR, snd.MASTER_VOLUME = orig_dir, orig_vol

if __name__ == "__main__":
    unittest.main()
