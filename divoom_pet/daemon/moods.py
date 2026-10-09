"""Mood overrides: manifest animations that replace a state's built-in sprites.

Files in the moods directory (default ~/.clawd/moods) are named after a mood:

  happy.json               the mood's animation
  sporty.jumprope.json     a variant; a mood with only variants rotates through
  sporty.tea.json          them, one per loop, in shuffled order (like SPORTY)
  coding.json + coding.whiteboard.json
                           a main loop plus variants: the main loop plays, and
                           about once a minute a variant leads it (like CODING's
                           rubber-duck / whiteboard / reading specials)

Valid mood names are the State values (idle, thinking, happy, …).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from divoom_pet.render.assets import AssetLibrary
from divoom_pet.sprites import State
from divoom_pet.sprites.rotation import ShuffleBag

log = logging.getLogger("moods")

# How often a variant leads a mood that also has a main loop.
VARIANT_EVERY_S = 60.0


@dataclass
class MoodSet:
    """One mood's override: an optional main loop plus named variants."""

    main: Optional[List] = None
    variants: Dict[str, List] = field(default_factory=dict)
    _bag: Optional[ShuffleBag] = None
    _last_variant_at: Optional[float] = None

    def next_loop(self, now: Optional[float] = None) -> List:
        """The (frame, duration_ms) list to play for one loop of this mood."""
        if not self.variants:
            return self.main or []
        if self._bag is None:
            self._bag = ShuffleBag(sorted(self.variants))
        if self.main is None:
            return self.variants[self._bag.draw()]
        now = time.time() if now is None else now
        if self._last_variant_at is None:          # first loop: start the clock
            self._last_variant_at = now
            return self.main
        if now - self._last_variant_at >= VARIANT_EVERY_S:
            self._last_variant_at = now
            return self.variants[self._bag.draw()] + self.main
        return self.main


def moods_from_dir(directory: Path) -> Dict[State, MoodSet]:
    """Load every mood manifest in `directory`, grouped by mood. Manifests whose
    name isn't `<mood>` or `<mood>.<variant>` are ignored with a warning."""
    lib = AssetLibrary.from_dir(directory)
    moods: Dict[State, MoodSet] = {}
    for name in lib.names():
        mood, _, variant = name.partition(".")
        try:
            state = State(mood)
        except ValueError:
            log.warning("moods: %s/%s.json is not a mood name (%s); ignored", directory, name,
                        ", ".join(s.value for s in State))
            continue
        entry = moods.setdefault(state, MoodSet())
        if variant:
            entry.variants[variant] = lib.get(name)
        else:
            entry.main = lib.get(name)
    return moods


def describe(moods: Dict[State, MoodSet]) -> str:
    """One-line summary for the startup log, e.g. 'happy, sporty(jumprope, tea)'."""
    parts = []
    for state in sorted(moods, key=lambda s: s.value):
        m = moods[state]
        parts.append(f"{state.value}({', '.join(sorted(m.variants))})" if m.variants else state.value)
    return ", ".join(parts)
