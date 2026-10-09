#!/usr/bin/env python3
"""Draw every frame of every mood manifest into one overview PNG.

Usage: python3 assets/moods/overview.py [moods_dir] [out.png]
  moods_dir  default ~/.clawd/moods (what build.sh writes)
  out.png    default ~/.clawd/moods-overview.png

One row per animation, labelled with its name and frame count. Needs Pillow
(the daemon itself doesn't).
"""
import glob
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SCALE, GAP, LABEL_W = 6, 2, 190


def main(argv):
    moods_dir = os.path.expanduser(argv[1] if len(argv) > 1 else "~/.clawd/moods")
    out = os.path.expanduser(argv[2] if len(argv) > 2 else "~/.clawd/moods-overview.png")
    anims = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(moods_dir, "*.json")))]
    if not anims:
        sys.exit(f"no mood manifests in {moods_dir}")
    cell = 16 * SCALE + GAP
    width = LABEL_W + max(len(a["frames"]) for a in anims) * cell + GAP
    img = Image.new("RGB", (width, len(anims) * cell + GAP), (60, 60, 60))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 13)
    except OSError:
        font = ImageFont.load_default()
    for row, anim in enumerate(anims):
        y = GAP + row * cell
        draw.text((6, y + 30), anim["name"], fill=(230, 230, 230), font=font)
        draw.text((6, y + 50), f"{len(anim['frames'])} frames", fill=(160, 160, 160), font=font)
        for col, frame in enumerate(anim["frames"]):
            tile = Image.frombytes("RGB", (16, 16), bytes(frame["px"]))
            img.paste(tile.resize((16 * SCALE, 16 * SCALE), Image.NEAREST), (LABEL_W + col * cell, y))
    img.save(out)
    print(f"{len(anims)} animations -> {out}")


if __name__ == "__main__":
    main(sys.argv)
