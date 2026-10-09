"""Chiptune sound engine for Clawd — zero dependencies.

Synthesizes 8-bit-style chirps with square/triangle/pulse waves + simple
envelopes, writes them to WAV, and plays them via macOS `afplay`. Also handles:

  - Pre-rendering spoken "big moment" lines via `say` into WAV (faster than
    live TTS at playback time; ~650ms warm vs ~1.7s live).
  - A keep-alive tone played periodically to keep the Bluetooth speaker awake,
    so reaction sounds stay in the ~650ms "warm" regime instead of ~1.2s cold.

Sounds are rendered once into ~/.clawd/sounds/ and reused.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import random
import shutil
import struct
import subprocess
import threading
import time
import wave
from array import array
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("sounds")

SAMPLE_RATE = 22050
SOUNDS_DIR = Path.home() / ".clawd" / "sounds"

# Global loudness scale applied to every synthesized tone. Lower = softer/gentler.
# Tuned down from the original after the chirps felt too loud/harsh on the Ditoo.
MASTER_VOLUME = 0.6


def set_master_volume(v: float) -> None:
    """Set the synth loudness scale (0..1). Re-render chirps to hear the change."""
    global MASTER_VOLUME
    MASTER_VOLUME = max(0.0, min(1.0, float(v)))

# ---- note → frequency (equal temperament, A4 = 440) ----

_NOTE_SEMITONES = {
    "C": -9, "C#": -8, "Db": -8, "D": -7, "D#": -6, "Eb": -6, "E": -5,
    "F": -4, "F#": -3, "Gb": -3, "G": -2, "G#": -1, "Ab": -1, "A": 0,
    "A#": 1, "Bb": 1, "B": 2,
}


def note(name: str) -> float:
    """'C4' / 'A#5' -> frequency in Hz. Rest = 'R'."""
    if name == "R":
        return 0.0
    # split letter(s) + octave
    octave = int(name[-1])
    pitch = name[:-1]
    semis = _NOTE_SEMITONES[pitch] + (octave - 4) * 12
    return 440.0 * (2 ** (semis / 12))


# ---- waveform generators ----


def _square(phase: float, duty: float = 0.5) -> float:
    return 1.0 if (phase % 1.0) < duty else -1.0


def _triangle(phase: float) -> float:
    p = phase % 1.0
    return 4.0 * abs(p - 0.5) - 1.0


def _sine(phase: float) -> float:
    return math.sin(2 * math.pi * phase)


_WAVES = {"square": _square, "triangle": _triangle, "sine": _sine}


def _env(i: int, total: int, attack: float = 0.02, decay: float = 0.6) -> float:
    """Simple attack + exponential decay envelope, 0..1."""
    t = i / total
    a = min(1.0, t / attack) if attack > 0 else 1.0
    # exponential decay over the remaining portion
    d = math.exp(-3.0 * max(0.0, (t - attack)) / max(1e-6, decay))
    return a * d


def render_tone(freq: float, dur_s: float, wave: str = "square",
                duty: float = 0.5, volume: float = 0.4,
                attack: float = 0.025, decay: float = 0.5,
                vibrato_hz: float = 0.0, vibrato_depth: float = 0.0,
                detune_cents: float = 0.0) -> bytes:
    """Render a single tone to raw little-endian 16-bit mono PCM bytes.

    A softer default attack (0.025) takes the percussive 'click' edge off each
    note; MASTER_VOLUME scales overall loudness down so chirps aren't harsh.
    `detune_cents` mixes in a second oscillator a few cents sharp for a warmer,
    fuller tone (classic chiptune "supersaw"-lite trick).
    """
    n = int(SAMPLE_RATE * dur_s)
    wavef = _WAVES[wave]
    out = bytearray()
    phase = 0.0
    phase2 = 0.0
    f2_ratio = 2 ** (detune_cents / 1200.0) if detune_cents else 0.0
    for i in range(n):
        f = freq
        if vibrato_hz > 0 and freq > 0:
            f = freq * (1.0 + vibrato_depth * math.sin(2 * math.pi * vibrato_hz * (i / SAMPLE_RATE)))
        phase += f / SAMPLE_RATE
        if freq == 0:
            sample = 0.0
        else:
            sample = wavef(phase, duty) if wave == "square" else wavef(phase)
            if detune_cents:
                phase2 += (f * f2_ratio) / SAMPLE_RATE
                s2 = wavef(phase2, duty) if wave == "square" else wavef(phase2)
                sample = 0.5 * (sample + s2)
        s = sample * volume * MASTER_VOLUME * _env(i, n, attack, decay)
        out.extend(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)))
    return bytes(out)


def render_sequence(notes: List[Tuple[str, float]], wave: str = "square",
                    duty: float = 0.5, volume: float = 0.4,
                    decay: float = 0.5, vibrato_hz: float = 0.0,
                    vibrato_depth: float = 0.0, gap_s: float = 0.0,
                    detune_cents: float = 0.0) -> bytes:
    """Render a melody: list of (note_name, duration_s)."""
    pcm = bytearray()
    for name, dur in notes:
        pcm.extend(render_tone(note(name), dur, wave=wave, duty=duty, volume=volume,
                               decay=decay, vibrato_hz=vibrato_hz, vibrato_depth=vibrato_depth,
                               detune_cents=detune_cents))
        if gap_s > 0:
            pcm.extend(render_tone(0, gap_s))
    return bytes(pcm)


# Major-pentatonic semitone offsets — every blip lands on a pleasant note.
_PENTA = (0, 2, 4, 7, 9)


def render_babble(text: str, base: str = "A4", blip_s: float = 0.07,
                  gap_s: float = 0.045, wave: str = "square",
                  volume: float = 0.3) -> bytes:
    """'Animalese'-style speech: one short pitched blip per letter, snapped to a
    pentatonic scale (so it's musical, not random noise) with a little jitter for
    life. Cute, fast, and zero-TTS — Clawd mutters in chiptune."""
    base_f = note(base)
    pcm = bytearray()
    for ch in text:
        low = ch.lower()
        if not low.isalpha():
            pcm.extend(render_tone(0, gap_s * 1.8))  # pause on space/punctuation
            continue
        idx = ord(low) - ord("a")
        semis = _PENTA[idx % len(_PENTA)] + 12 * (idx % 2) + random.uniform(-0.35, 0.35)
        f = base_f * (2 ** (semis / 12.0))
        pcm.extend(render_tone(f, blip_s, wave=wave, duty=0.5, volume=volume,
                               attack=0.008, decay=0.22))
        pcm.extend(render_tone(0, gap_s))
    return bytes(pcm)


def write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data_size = len(pcm)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))            # PCM
        f.write(struct.pack("<H", 1))            # mono
        f.write(struct.pack("<I", SAMPLE_RATE))
        f.write(struct.pack("<I", SAMPLE_RATE * 2))
        f.write(struct.pack("<H", 2))
        f.write(struct.pack("<H", 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm)


# ---- Clawd's sound vocabulary ----
# Each entry: a renderer function returning PCM bytes. Designed to be short and characterful.

def _s_wake() -> bytes:
    # cheerful rising arpeggio: boop-beep-beep!
    return render_sequence([("C5", 0.09), ("E5", 0.09), ("G5", 0.14)],
                           wave="square", duty=0.5, volume=0.42, decay=0.5)

def _s_wake2() -> bytes:
    # warmer detuned hatch flourish
    return render_sequence([("E5", 0.08), ("G5", 0.08), ("C6", 0.16)],
                           wave="square", duty=0.5, volume=0.4, decay=0.5, detune_cents=8)

def _s_think() -> bytes:
    # gentle pondering: two soft low pulses, triangle
    return render_sequence([("E4", 0.12), ("R", 0.06), ("D4", 0.16)],
                           wave="triangle", volume=0.3, decay=0.7)

def _s_think2() -> bytes:
    # curious little rise with a touch of vibrato
    return render_sequence([("D4", 0.10), ("F4", 0.10), ("E4", 0.16)],
                           wave="triangle", volume=0.28, decay=0.7,
                           vibrato_hz=6, vibrato_depth=0.02)

def _s_think3() -> bytes:
    # Clawd mutters to himself while working
    return render_babble("hmm", base="A4", volume=0.26)

def _s_tool() -> bytes:
    # soft mechanical tick — fires on every tool call, so keep it unobtrusive
    return render_sequence([("A5", 0.045), ("R", 0.02), ("E5", 0.05)],
                           wave="triangle", volume=0.34, decay=0.3)

def _s_tool2() -> bytes:
    # lower-pitched twin tick for variety
    return render_sequence([("G5", 0.04), ("R", 0.015), ("D5", 0.05)],
                           wave="triangle", volume=0.32, decay=0.3)

def _s_done() -> bytes:
    # triumphant major arpeggio ta-da!
    return render_sequence([("C5", 0.08), ("E5", 0.08), ("G5", 0.08), ("C6", 0.20)],
                           wave="square", duty=0.5, volume=0.45, decay=0.55)

def _s_done2() -> bytes:
    # warmer detuned fanfare, a third higher
    return render_sequence([("E5", 0.07), ("G5", 0.07), ("C6", 0.08), ("E6", 0.20)],
                           wave="square", duty=0.5, volume=0.42, decay=0.55, detune_cents=7)

def _s_error() -> bytes:
    # worried descending bwomp-bwomp
    return render_sequence([("G4", 0.14), ("R", 0.04), ("Db4", 0.22)],
                           wave="square", duty=0.5, volume=0.42, decay=0.5,
                           vibrato_hz=14, vibrato_depth=0.03)

def _s_sleep() -> bytes:
    # slow descending yawn glide (triangle, long decay)
    return render_sequence([("G4", 0.18), ("E4", 0.18), ("C4", 0.30)],
                           wave="triangle", volume=0.3, decay=0.9)

def _s_poke() -> bytes:
    # surprised high bip!
    return render_sequence([("E6", 0.05), ("B6", 0.10)],
                           wave="square", duty=0.5, volume=0.45, decay=0.35)

def _s_poke2() -> bytes:
    # delighted little giggle-triad
    return render_sequence([("G6", 0.045), ("E6", 0.045), ("B6", 0.09)],
                           wave="square", duty=0.5, volume=0.43, decay=0.35)

def _s_keepalive() -> bytes:
    # ~0.4s near-silent low tone to keep the BT speaker awake (sub-perceptual volume)
    return render_tone(note("C2"), 0.4, wave="sine", volume=0.015, attack=0.05, decay=0.95)


# Each entry is a list of variant renderers; one is picked at random per play so
# repeated reactions don't sound identical.
CHIRPS: Dict[str, List[callable]] = {
    "wake": [_s_wake, _s_wake2],
    "think": [_s_think, _s_think2, _s_think3],
    "tool": [_s_tool, _s_tool2],
    "done": [_s_done, _s_done2],
    "error": [_s_error],
    "sleep": [_s_sleep],
    "poke": [_s_poke, _s_poke2],
    "keepalive": [_s_keepalive],
}

# Variant indices that are "babble" (Clawd muttering to himself). Filtered out
# when the voice.babble setting is off.
BABBLE_VARIANTS: Dict[str, set] = {"think": {2}}

# Spoken "big moment" lines pre-rendered via `say`. One is chosen at random.
SPOKEN: Dict[str, List[str]] = {
    "hatch": ["Hi! I'm Clawd.", "Clawd, reporting in!", "Hello there! Let's build."],
    "done": ["All done!", "Nailed it!", "Done and done.", "Ta-da!"],
    "error": ["Uh oh.", "Hmm, that's not right.", "Yikes."],
    "poke": ["Hey!", "Oh, hi!", "Boop!"],
}

# Warm vocabulary: full announcement phrases pre-rendered shortly after startup so
# live content (PR merged, CI status, agent tallies) speaks instantly (~650ms warm)
# instead of paying ~1.7s for a cold `say`. Anything outside this set falls back to
# a live render that's cached on first use — so it's warm the next time too.
VOCAB: List[str] = [
    "All done!", "Nice work.", "Shipping it.",
    "Pull request merged!", "New pull request.", "Pull request closed.",
    "Tests passed.", "Tests are failing.", "C I is red.",
    "One agent done.", "Two agents done.", "Three agents done.",
    "Four agents done.", "Five agents done.",
]


def _phrase_slug(text: str) -> str:
    """Stable cache key (filename stem) for an arbitrary spoken phrase."""
    norm = " ".join(text.lower().split())
    return "saylive_" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


# ---- rendering / caching ----


def render_say_to_wav(text: str, path: Path, voice: Optional[str] = None,
                      timeout: float = 12.0) -> bool:
    """Render `text` to a Ditoo-format WAV (22050 Hz mono Int16 LE) via macOS `say`.
    Returns True if the file was produced. Shared by the warm-vocab pre-render and
    the live `say()` fallback."""
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["say", "-o", str(path), "--data-format=LEI16@22050", "--file-format=WAVE"]
    if voice:
        args += ["-v", voice]
    # Feed the text on stdin (not as an argv operand) so text starting with '-'
    # can never be misread as a `say` flag (e.g. --output-file=…).
    try:
        subprocess.run(args, input=text, text=True, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        return path.exists()
    except Exception as e:
        log.warning("say render failed for %r: %s", text[:40], e)
        return False


def scaled_speech(path: Path) -> Path:
    """A copy of a spoken-line WAV scaled by MASTER_VOLUME. Chirps are rendered
    at the master volume already, but `say` output is always full scale, so
    without this the voice ignores the volume setting. Copies are cached per
    volume in SOUNDS_DIR/scaled/; returns `path` unchanged on any problem."""
    if path.name.startswith("chirp_") or MASTER_VOLUME >= 1.0:
        return path
    pct = int(round(MASTER_VOLUME * 100))
    out = SOUNDS_DIR / "scaled" / f"{pct:03d}_{path.name}"
    try:
        if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
            return out
        with wave.open(str(path), "rb") as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                return path
            rate = w.getframerate()
            samples = array("h", w.readframes(w.getnframes()))
        samples = array("h", (int(x * MASTER_VOLUME) for x in samples))
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(samples.tobytes())
        os.replace(tmp, out)
        return out
    except (OSError, wave.Error, EOFError) as e:
        log.warning("could not scale %s: %s", path.name, e)
        return path


def render_all(force: bool = False, voice: Optional[str] = None,
               chirps_only: bool = False, theme: str = "chip") -> Dict[str, Path]:
    """Render every chirp variant (and spoken line if `say` exists) into SOUNDS_DIR.

    Chirps come from the active `theme` (see voice/themes.py); 'chip' is the legacy
    CHIRPS. Each chirp/spoken name has N variants written as ``chirp_<name>_<i>.wav``
    / ``say_<name>_<i>.wav``, with a ``chirp_<name>`` / ``say_<name>`` alias to
    variant 0.

    `voice` overrides the TTS voice (None = auto-pick). `chirps_only` skips the
    (slow) `say` re-render — used for live volume / theme changes."""
    from .themes import get_theme  # lazy import to avoid a module cycle

    chirps = get_theme(theme)
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    if force:
        # Clear stale chirp variants (e.g. a previous theme had more) before re-render.
        for old in SOUNDS_DIR.glob("chirp_*.wav"):
            try:
                old.unlink()
            except OSError:
                pass
    paths: Dict[str, Path] = {}
    for name, fns in chirps.items():
        for i, fn in enumerate(fns):
            p = SOUNDS_DIR / f"chirp_{name}_{i}.wav"
            if force or not p.exists():
                write_wav(p, fn())
            paths[f"chirp_{name}_{i}"] = p
        paths[f"chirp_{name}"] = paths[f"chirp_{name}_0"]  # alias -> variant 0
    # Spoken lines via `say`, rendered to WAV in the SAME format as the chirps
    # (22050 Hz mono Int16 little-endian) so they play through the routed serve
    # engine identically. (AIFF from `say` is big-endian and was failing there.)
    if not chirps_only and shutil.which("say"):
        voice = voice if voice is not None else _pick_voice()
        # clean up any stale AIFFs from older versions
        for old in SOUNDS_DIR.glob("say_*.aiff"):
            try:
                old.unlink()
            except OSError:
                pass
        for name, texts in SPOKEN.items():
            for i, text in enumerate(texts):
                p = SOUNDS_DIR / f"say_{name}_{i}.wav"
                if force or not p.exists():
                    render_say_to_wav(text, p, voice)
                if p.exists():
                    paths[f"say_{name}_{i}"] = p
            if f"say_{name}_0" in paths:
                paths[f"say_{name}"] = paths[f"say_{name}_0"]  # alias -> variant 0
    return paths


def _pick_voice() -> Optional[str]:
    try:
        out = subprocess.check_output(["say", "-v", "?"], text=True, timeout=2.0)
    except Exception:
        return None
    for cand in ["Zoe (Premium)", "Zoe", "Samantha (Enhanced)", "Samantha", "Karen"]:
        if cand in out:
            return cand
    return None


# ---- playback ----


def find_play_binary() -> Optional[Path]:
    """Locate the ditoo-play output-routing binary, if present."""
    here = Path(__file__).resolve().parent.parent.parent
    for c in [here / "ditoo_audio" / "ditoo-play"]:
        if c.exists() and os.access(c, os.X_OK):
            return c
    return None


class SoundPlayer:
    """Plays cached sounds, routed to a specific output device (the Ditoo) via a
    persistent `ditoo-play --serve` engine, so the user's music stays on their
    own default output. Falls back to `afplay` (system default) if routing is
    unavailable.
    """

    def __init__(self, enabled: bool = True, min_interval: float = 0.25,
                 device: Optional[str] = None, volume: Optional[float] = None,
                 babble: bool = True, spoken_lines: bool = True,
                 tts_voice: Optional[str] = None, theme: str = "chip"):
        self.enabled = enabled and shutil.which("afplay") is not None
        self.min_interval = min_interval
        self.device = device or os.environ.get("CLAWD_AUDIO_DEVICE", "DitooPro")
        self.babble = babble
        self.spoken_lines = spoken_lines
        self.tts_voice = tts_voice
        self.theme = theme
        if volume is not None:
            set_master_volume(volume)
        self._last = 0.0
        self._lock = threading.Lock()
        self.paths = render_all(voice=tts_voice, theme=theme) if self.enabled else {}
        self._play_bin = find_play_binary()
        self._serve: Optional[subprocess.Popen] = None
        self._serve_lock = threading.Lock()
        if self.enabled and self._play_bin and self.device:
            self._start_serve()
        # Pre-warm the announcement vocabulary in the background (don't slow boot).
        if self.enabled:
            threading.Thread(target=self._warm_vocab, daemon=True, name="vocab-warm").start()
        log.info("sound player enabled=%s routed=%s device=%s, %d sounds in %s",
                 self.enabled, self.routed, self.device, len(self.paths), SOUNDS_DIR)

    @property
    def routed(self) -> bool:
        return self._serve is not None and self._serve.poll() is None

    def _start_serve(self) -> None:
        try:
            self._serve = subprocess.Popen(
                [str(self._play_bin), "--device", self.device, "--serve"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
            time.sleep(0.3)
            if self._serve.poll() is not None:
                self._serve = None
        except Exception as e:
            log.warning("could not start routed audio (ditoo-play --serve): %s", e)
            self._serve = None

    def _play_file(self, path: Optional[Path]) -> None:
        if not self.enabled or not path or not path.exists():
            return
        path = scaled_speech(path)
        # Prefer routed playback to the Ditoo so music on the default output is untouched.
        with self._serve_lock:
            if self.routed and self._serve and self._serve.stdin:
                try:
                    self._serve.stdin.write(str(path) + "\n")
                    self._serve.stdin.flush()
                    return
                except Exception as e:
                    log.warning("routed play failed (%s); falling back to afplay", e)
                    self._serve = None
        # Fallback: system default output.
        try:
            subprocess.Popen(["afplay", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log.warning("afplay failed: %s", e)

    def _variants(self, prefix: str, name: str) -> List[Path]:
        """All variant files for a base name, e.g. prefix='chirp_', name='think'
        -> [chirp_think_0.wav, chirp_think_1.wav, ...]. Babble variants are dropped
        when babble is off. Falls back to the alias."""
        stem = f"{prefix}{name}_"
        skip = set() if self.babble or prefix != "chirp_" else BABBLE_VARIANTS.get(name, set())
        out = []
        for k, v in self.paths.items():
            if k.startswith(stem) and k[len(stem):].isdigit():
                if int(k[len(stem):]) in skip:
                    continue
                out.append(v)
        if out:
            return out
        alias = self.paths.get(f"{prefix}{name}")
        return [alias] if alias else []

    def chirp(self, name: str) -> None:
        now = time.time()
        with self._lock:
            if now - self._last < self.min_interval:
                return
            self._last = now
        variants = self._variants("chirp_", name)
        if variants:
            self._play_file(random.choice(variants))

    def speak(self, name: str) -> None:
        """Play a pre-rendered spoken line (no throttle — these are 'big moments')."""
        if not self.spoken_lines:
            return
        variants = self._variants("say_", name)
        if variants:
            self._play_file(random.choice(variants))

    def say(self, text: str) -> None:
        """Speak arbitrary text — the *live voice*. Warm phrases (pre-rendered vocab
        or something said before) play instantly; a novel phrase renders once via
        `say` (~1.7s) and is cached so it's warm next time. Non-blocking: the render
        + playback happen on a background thread so callers (HTTP handlers) return
        immediately."""
        if not self.enabled or not self.spoken_lines:
            return
        text = (text or "").strip()
        if not text:
            return
        threading.Thread(target=self._say_blocking, args=(text,), daemon=True,
                         name="say").start()

    def _say_blocking(self, text: str) -> None:
        path = SOUNDS_DIR / f"{_phrase_slug(text)}.wav"
        if not path.exists():
            render_say_to_wav(text, path, self.tts_voice)
        if path.exists():
            self._play_file(path)

    def _warm_vocab(self) -> None:
        """Pre-render the warm VOCAB in the background so the first real announcement
        is already cached. Idempotent — skips phrases already on disk."""
        for phrase in VOCAB:
            path = SOUNDS_DIR / f"{_phrase_slug(phrase)}.wav"
            if not path.exists():
                render_say_to_wav(phrase, path, self.tts_voice)

    def set_volume(self, v: float) -> None:
        """Apply a new loudness and re-render the chirps (fast; skips TTS)."""
        set_master_volume(v)
        if self.enabled:
            self.paths.update(render_all(force=True, voice=self.tts_voice,
                                         chirps_only=True, theme=self.theme))

    def set_theme(self, theme: str) -> None:
        """Switch the chirp theme and re-render the chirps (skips TTS). Drops the
        old theme's chirp cache entries so stale variants don't linger."""
        if theme == self.theme:
            return
        self.theme = theme
        if not self.enabled:
            return
        self.paths = {k: v for k, v in self.paths.items() if not k.startswith("chirp_")}
        self.paths.update(render_all(force=True, voice=self.tts_voice,
                                     chirps_only=True, theme=theme))

    def set_tts_voice(self, voice: Optional[str]) -> None:
        """Switch the spoken-line voice and re-render the `say` lines. Keeps the
        active chirp theme, and clears the cached live-voice phrases so they
        re-render in the new voice (they're keyed only on text)."""
        if voice == self.tts_voice:
            return
        self.tts_voice = voice
        if not self.enabled:
            return
        for old in SOUNDS_DIR.glob("saylive_*.wav"):
            try:
                old.unlink()
            except OSError:
                pass
        self.paths.update(render_all(force=True, voice=voice, theme=self.theme))
        threading.Thread(target=self._warm_vocab, daemon=True, name="vocab-rewarm").start()

    def keepalive_tick(self) -> None:
        # With routed serve mode the engine already keeps the link warm; only the
        # afplay-fallback path needs an explicit keepalive tone.
        if not self.routed:
            self._play_file(self.paths.get("chirp_keepalive"))

    def stop(self) -> None:
        with self._serve_lock:
            if self._serve and self._serve.poll() is None:
                try:
                    if self._serve.stdin:
                        self._serve.stdin.write("__quit__\n")
                        self._serve.stdin.flush()
                    self._serve.wait(timeout=1.0)
                except Exception:
                    try:
                        self._serve.terminate()
                    except Exception:
                        pass
            self._serve = None


class KeepAlive:
    """Background thread that plays a near-silent tone every `interval` seconds
    to keep the Bluetooth speaker from sleeping (avoids ~1.2s cold-start stalls)."""

    def __init__(self, player: SoundPlayer, interval: float = 18.0):
        self.player = player
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not self.player.enabled:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="keepalive")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.player.keepalive_tick()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)


# ---- state -> sound mapping ----

STATE_CHIRP = {
    "hatch": "wake",
    "thinking": "think",
    "coding": "think",    # same gentle pondering chirp as thinking
    "typing": None,       # silent — typing is continuous
    "tool_use": "tool",
    "happy": "done",
    "alert": "error",
    "sleeping": "sleep",
    "idle": None,
    "poke": "poke",
}

# Which states also get a *fixed* spoken line. Kept minimal: just a hello when he
# wakes. Alert keeps its error chirp as an attention ping, but the spoken line is
# left to the live-voice layer (e.g. the hook's "<project> needs your input", or
# the watcher's "Tests are failing.") so they don't talk over each other.
STATE_SPEAK = {
    "hatch": "hatch",
}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    paths = render_all(force="--force" in sys.argv)
    print(f"rendered {len(paths)} sounds into {SOUNDS_DIR}")
    if "--play" in sys.argv and shutil.which("afplay"):
        for name in ["wake", "think", "tool", "done", "error", "sleep", "poke"]:
            for i in range(len(CHIRPS[name])):
                p = paths.get(f"chirp_{name}_{i}")
                if p:
                    print(f"  playing chirp: {name} (variant {i})")
                    subprocess.run(["afplay", str(p)])
                    time.sleep(0.2)
