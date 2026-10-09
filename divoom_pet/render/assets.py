"""Drop-in PNG/GIF → 16×16 named animations.

Two halves, split so the daemon stays stdlib-only at runtime:
  - **build time** (`image_to_frames`, `build_assets`) uses PIL to decode/resize
    images down to 16×16 and writes compact JSON manifests.
  - **run time** (`load_manifest`, `AssetLibrary`) reads those manifests with
    nothing but stdlib `json`, exactly like the pre-rendered sound cache.

Drop a `foo.gif` in `assets/`, run `clawd assets build`, and Clawd can `play foo`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .canvas import WIDTH, RGB

Frame = List[RGB]
Anim = List[Tuple[Frame, int]]

ASSETS_DIR = Path.home() / ".clawd" / "assets"
# Manifests named after a mood (idle.json, happy.json…) replace that mood's
# built-in sprite animation; <mood>.<variant>.json adds variants. See daemon/moods.py.
MOODS_DIR = Path.home() / ".clawd" / "moods"
IMAGE_SUFFIXES = (".png", ".gif", ".jpg", ".jpeg", ".bmp", ".webp")
DEFAULT_FRAME_MS = 120


# -------------------- build time (PIL) --------------------


def image_to_frames(path, size: int = WIDTH, default_ms: int = DEFAULT_FRAME_MS) -> Anim:
    """Decode a PNG/GIF (animated or static) into 16×16 (frame, duration_ms) pairs.
    Uses a high-quality downscale; the device quantizes colors on send."""
    from PIL import Image, ImageSequence

    img = Image.open(path)
    frames: Anim = []
    for piece in ImageSequence.Iterator(img):
        rgb = piece.convert("RGB").resize((size, size), Image.LANCZOS)
        pixels = [tuple(px) for px in rgb.getdata()]
        ms = int(piece.info.get("duration", default_ms) or default_ms)
        frames.append((pixels, ms))
    if not frames:  # static, single-frame image
        rgb = img.convert("RGB").resize((size, size), Image.LANCZOS)
        frames = [([tuple(px) for px in rgb.getdata()], default_ms)]
    return frames


def save_manifest(name: str, frames: Anim, out_dir=ASSETS_DIR, loop: bool = True) -> Path:
    """Write a compact JSON manifest (flat RGB ints per frame)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "loop": loop,
        "frames": [
            {"ms": ms, "px": [channel for px in frame for channel in px]}
            for frame, ms in frames
        ],
    }
    path = out / f"{name}.json"
    path.write_text(json.dumps(data))
    return path


def build_assets(src_dir, out_dir=ASSETS_DIR, size: int = WIDTH) -> List[Path]:
    """Convert every image in `src_dir` into a manifest in `out_dir`."""
    src = Path(src_dir)
    written: List[Path] = []
    if not src.exists():
        return written
    for image in sorted(src.iterdir()):
        if image.suffix.lower() in IMAGE_SUFFIXES:
            frames = image_to_frames(image, size=size)
            written.append(save_manifest(image.stem, frames, out_dir))
    return written


# -------------------- run time (stdlib only) --------------------


def load_manifest(path) -> Tuple[str, Anim, bool]:
    """Read a manifest back into (name, frames, loop). stdlib only — no PIL."""
    data = json.loads(Path(path).read_text())
    frames: Anim = []
    for entry in data.get("frames", []):
        flat = entry.get("px", [])
        ms = int(entry.get("ms", DEFAULT_FRAME_MS))
        frame = [(flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat) - 2, 3)]
        # Only accept exactly-256-pixel frames; a truncated/corrupt manifest would
        # otherwise hand a wrong-length frame to the bridge (which then raises).
        if len(frame) == WIDTH * WIDTH:
            frames.append((frame, ms))
    return str(data.get("name", "")), frames, bool(data.get("loop", True))


class AssetLibrary:
    """Named animations loaded from a directory of manifests."""

    def __init__(self, anims: Optional[Dict[str, Anim]] = None):
        self._anims: Dict[str, Anim] = anims or {}

    @classmethod
    def from_dir(cls, directory=ASSETS_DIR) -> "AssetLibrary":
        directory = Path(directory)
        anims: Dict[str, Anim] = {}
        if directory.exists():
            for manifest in sorted(directory.glob("*.json")):
                try:
                    name, frames, _loop = load_manifest(manifest)
                except (OSError, json.JSONDecodeError, KeyError, TypeError):
                    continue
                if name and frames:
                    anims[name] = frames
        return cls(anims)

    def get(self, name: str) -> Optional[Anim]:
        return self._anims.get(name)

    def names(self) -> List[str]:
        return sorted(self._anims)


if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else "assets"
    paths = build_assets(src, ASSETS_DIR)
    print(f"built {len(paths)} assets into {ASSETS_DIR}:")
    for p in paths:
        print(f"  {p.stem}")
