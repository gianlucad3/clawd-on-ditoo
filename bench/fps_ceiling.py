#!/usr/bin/env python3
"""Find the real frame-rate ceiling for streaming animations to the device.

The daemon streams moods one frame at a time (`push_image` per frame), so the
question is: how fast can we push frames before the device falls behind? The
host can't see the screen, so this measures it from three sides:

  link     Objective, host side. Pushes real frames back-to-back and reports
           achieved FPS, bytes/s and push latency. `writeSync` blocks once the
           Bluetooth buffer is full, so this is the link's ceiling.
  lag      You + Enter key. Streams at a ladder of rates, then flashes the
           screen green; press Enter the moment you see green. If the device
           can't keep up, frames queue and the green arrives late. A 1 FPS run
           first calibrates your reaction time.
  counter  Phone slow-motion video. Shows a big frame counter at each rate;
           film the screen and check for skipped or repeated numbers (dropped
           frames don't show up in the lag test).

Stop the Clawd daemon first — only one process can hold the RFCOMM channel.
Run it in a regular terminal (the Claude Code sandbox blocks Bluetooth).

Usage:
  python3 bench/fps_ceiling.py                 # link + lag (default)
  python3 bench/fps_ceiling.py link
  python3 bench/fps_ceiling.py counter --rates 4,8,12,16
  python3 bench/fps_ceiling.py --frames ~/.clawd/assets --rates 4,6,8,10,12,16,20
  python3 bench/fps_ceiling.py --simulate      # dry run, no device

MAC and channel come from ~/.clawd/config.json unless --mac/--channel is given.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from divoom_pet.config import Config  # noqa: E402
from divoom_pet.daemon.bridge import DitooBridge, find_bundled_bridge  # noqa: E402
from divoom_pet.protocol import build_set_image_from_rgb  # noqa: E402
from divoom_pet.render.assets import ASSETS_DIR, load_manifest  # noqa: E402
from divoom_pet.render.canvas import Canvas  # noqa: E402
from divoom_pet.render.font import draw_text  # noqa: E402

RGB = Tuple[int, int, int]
Frame = List[RGB]

RESULTS_DIR = ROOT / "bench" / "results"
ORANGE = (205, 110, 88)
DARK = (8, 8, 10)
GREEN = (0, 255, 60)
WHITE = (255, 255, 255)
AMBER = (242, 196, 99)

LAG_TOLERANCE_S = 0.15  # extra delay over your reaction time that still counts as "keeping up"


# -------------------- test frames --------------------


def column_frames() -> List[Frame]:
    """Fallback test pattern: an orange column bouncing left-right."""
    frames = []
    for x in list(range(16)) + list(range(14, 0, -1)):
        frames.append([ORANGE if col == x else DARK for _y in range(16) for col in range(16)])
    return frames


def load_frames(directory: Optional[Path]) -> Tuple[List[Frame], str]:
    """All frames from every manifest in `directory`, in order. Real Clawd frames
    give realistic packet sizes; falls back to the column pattern."""
    if directory and directory.is_dir():
        frames: List[Frame] = []
        names = []
        for manifest in sorted(directory.glob("*.json")):
            try:
                name, anim, _loop = load_manifest(manifest)
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
            if anim:
                frames.extend(frame for frame, _ms in anim)
                names.append(name or manifest.stem)
        if frames:
            return frames, f"{len(frames)} frames from {directory} ({', '.join(names)})"
    return column_frames(), "built-in bouncing column (no manifests found)"


def solid(color: RGB) -> Frame:
    return [color] * 256


def counter_frame(n: int, rate: float) -> Frame:
    """Two-digit frame counter (00-99) plus a marker that walks the bottom row,
    so a slow-motion video shows every skipped or repeated frame."""
    c = Canvas(DARK)
    draw_text(c, 1, 1, f"{int(rate):02d}", AMBER)       # rate label, top
    draw_text(c, 1, 8, f"{n % 100:02d}", WHITE)        # frame number
    c.set_pixel(n % 16, 15, GREEN)
    return c.to_frame()


# -------------------- helpers --------------------


def packet_bytes(frame: Frame) -> int:
    return len(build_set_image_from_rgb(frame))


def pct(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def stream(bridge: DitooBridge, frames: List[Frame], fps: float, seconds: float, start: int = 0) -> Dict:
    """Push frames on a fixed schedule (deadline-based, no drift). Returns
    pacing stats: if the host can't hit the schedule, `late` counts it."""
    period = 1.0 / fps
    t0 = time.perf_counter()
    n = late = 0
    push_ms: List[float] = []
    while True:
        due = t0 + n * period
        if due - t0 >= seconds:
            break
        now = time.perf_counter()
        if due > now:
            time.sleep(due - now)
        elif now - due > period:
            late += 1
        a = time.perf_counter()
        if n == 0:
            first = a
        bridge.push_image(frames[(start + n) % len(frames)])
        push_ms.append((time.perf_counter() - a) * 1000)
        last = a
        n += 1
    achieved = (n - 1) / (last - first) if n > 1 and last > first else 0.0
    return {"frames": n, "achieved_fps": achieved, "late": late,
            "push_p50_ms": pct(push_ms, 50), "push_p95_ms": pct(push_ms, 95)}


def flush_stdin() -> None:
    """Drop keys pressed before the flash, so an early Enter can't count."""
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (ImportError, OSError, ValueError):
        pass


# -------------------- tests --------------------


def test_link(bridge: DitooBridge, frames: List[Frame], seconds: float) -> Dict:
    print("\n\033[1m[link]\033[0m pushing frames back-to-back for %.0fs..." % seconds)
    sizes = [packet_bytes(f) for f in frames]
    push_ms: List[float] = []
    t0 = time.perf_counter()
    n = 0
    while time.perf_counter() - t0 < seconds:
        a = time.perf_counter()
        bridge.push_image(frames[n % len(frames)])
        push_ms.append((time.perf_counter() - a) * 1000)
        n += 1
    elapsed = time.perf_counter() - t0
    sent = sum(sizes[i % len(sizes)] for i in range(n))
    res = {"frames": n, "seconds": elapsed, "achieved_fps": n / elapsed,
           "bytes_per_s": sent / elapsed, "packet_bytes_avg": statistics.mean(sizes),
           "packet_bytes_max": max(sizes), "push_p50_ms": pct(push_ms, 50),
           "push_p95_ms": pct(push_ms, 95), "push_max_ms": max(push_ms)}
    print(f"  {n} frames in {elapsed:.1f}s = \033[1m{res['achieved_fps']:.0f} fps\033[0m "
          f"({res['bytes_per_s'] / 1024:.1f} KB/s, packets avg {res['packet_bytes_avg']:.0f} B)")
    print(f"  push latency p50 {res['push_p50_ms']:.1f} ms, p95 {res['push_p95_ms']:.1f} ms, "
          f"max {res['push_max_ms']:.1f} ms")
    if res["push_p50_ms"] < 2:
        print("  (pushes never blocked: the link is faster than this — the device's own"
              " redraw rate is the real limit; see the lag test)")
    return res


def reaction_trial(bridge: DitooBridge, frames: List[Frame], fps: float, seconds: float) -> Optional[float]:
    """Stream, then flash green; return seconds from flash-sent to Enter."""
    stream(bridge, frames, fps, seconds, start=random.randrange(len(frames)))
    flush_stdin()
    bridge.push_image(solid(GREEN))
    t_sent = time.perf_counter()
    try:
        input()
    except EOFError:
        return None
    latency = time.perf_counter() - t_sent
    bridge.push_image(solid(DARK))
    return latency


def test_lag(bridge: DitooBridge, frames: List[Frame], rates: List[float], seconds: float,
             trials: int, simulate: bool) -> Dict:
    print("\n\033[1m[lag]\033[0m Watch the DEVICE, not this terminal. It plays an animation;")
    print("  the moment the screen turns \033[32mGREEN\033[0m, press Enter.")
    if simulate or not sys.stdin.isatty():
        print("  (skipped: needs a real screen and an interactive terminal)")
        return {}
    input("  Press Enter to start the 1 fps calibration (3 rounds)... ")

    def run(fps: float, n: int, base_seconds: float) -> List[float]:
        out = []
        while len(out) < n:
            # random length so you can't anticipate the flash
            lat = reaction_trial(bridge, frames, fps, base_seconds + random.uniform(0, 2.0))
            if lat is None:
                break
            if lat < 0.1:
                print("    too fast (pressed before green?) — repeating")
                time.sleep(1.0)
                continue
            out.append(lat)
            time.sleep(0.8)
        return out

    base = run(1.0, 3, 2.0)
    if not base:
        return {}
    baseline = statistics.median(base)
    print(f"  your reaction time: \033[1m{baseline * 1000:.0f} ms\033[0m "
          f"({', '.join(f'{b * 1000:.0f}' for b in base)})")

    rows = []
    for fps in rates:
        print(f"  >>> {fps:g} fps ({trials} round{'s' if trials > 1 else ''})...", flush=True)
        lats = run(fps, trials, seconds)
        if not lats:
            break
        # A backlog makes *every* round late, while a missed flash or a Bluetooth
        # hiccup only spoils one — so judge each rate by its fastest round.
        lag = min(lats) - baseline
        ok = lag <= LAG_TOLERANCE_S
        rows.append({"fps": fps, "latencies_s": lats, "excess_lag_s": lag, "keeps_up": ok})
        mark = "\033[32mkeeps up\033[0m" if ok else "\033[31mfalling behind\033[0m"
        print(f"      +{lag * 1000:.0f} ms over reaction time -> {mark}")

    ok_rates = [r["fps"] for r in rows if r["keeps_up"]]
    failed = [r["fps"] for r in rows if not r["keeps_up"]]
    ceiling = max(ok_rates) if ok_rates else None
    print(f"\n  highest rate that kept up: \033[1m{ceiling if ceiling else 'none'} fps\033[0m")
    if failed:
        print(f"  fell behind at: {failed} — if these sit below the ceiling, rerun them"
              " (--rates) to rule out a one-off")
    return {"baseline_s": baseline, "baseline_trials_s": base, "rates": rows, "ceiling_fps": ceiling}


def test_counter(bridge: DitooBridge, rates: List[float], seconds: float, simulate: bool) -> Dict:
    print("\n\033[1m[counter]\033[0m Film the device in slow motion (240 fps if your phone can).")
    if simulate:
        print("  (simulate: skipped, needs a real screen)")
        return {}
    print("  Each segment shows the rate (top, amber) and a frame number (white) that")
    print("  must go up by exactly 1 each frame; a skipped number = a dropped frame.")
    input("  Start recording, then press Enter... ")
    segments = []
    for fps in rates:
        frames = [counter_frame(n, fps) for n in range(int(fps * seconds) + 1)]
        res = stream(bridge, frames, fps, seconds)
        segments.append({"fps": fps, **res})
        print(f"  {fps:g} fps: sent {res['frames']} frames (00-{(res['frames'] - 1) % 100:02d}), "
              f"host late {res['late']}")
        bridge.push_image(solid(DARK))
        time.sleep(1.0)
    print("  Stop recording. In the video, find the first rate where numbers skip.")
    return {"segments": segments}


# -------------------- main --------------------


def parse_rates(s: str) -> List[float]:
    return [float(x) for x in s.split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tests", nargs="*", default=["link", "lag"], choices=["link", "lag", "counter"])
    ap.add_argument("--mac", help="device MAC (default: ~/.clawd/config.json)")
    ap.add_argument("--channel", type=int, help="RFCOMM channel (default: ~/.clawd/config.json)")
    ap.add_argument("--frames", type=Path, default=ASSETS_DIR,
                    help="directory of Clawd manifests to stream (default: %(default)s)")
    ap.add_argument("--rates", type=parse_rates, default=parse_rates("4,6,8,10,12,16,20,30"),
                    help="comma-separated FPS ladder (default: 4,6,8,10,12,16,20,30)")
    ap.add_argument("--seconds", type=float, default=5.0, help="seconds streamed per rate")
    ap.add_argument("--trials", type=int, default=3, help="lag rounds per rate")
    ap.add_argument("--brightness", type=int, default=70)
    ap.add_argument("--simulate", action="store_true", help="no device: exercise the tool only")
    args = ap.parse_args()

    cfg = Config.load()
    mac = args.mac or cfg.device.mac
    channel = args.channel if args.channel is not None else cfg.device.channel
    if not mac and not args.simulate:
        print("no device MAC: pass --mac or set device.mac in ~/.clawd/config.json")
        return 2

    frames, source = load_frames(args.frames)
    print(f"\033[1mFPS ceiling test\033[0m  mac={mac} channel={channel}")
    print(f"  frames: {source}")

    bridge = DitooBridge(binary=find_bundled_bridge(), mac=mac or "00:00:00:00:00:00",
                         channel=channel, simulate=args.simulate)
    try:
        bridge.start()
        bridge.set_brightness(args.brightness)
    except Exception as e:
        print(f"  \033[31mconnect failed:\033[0m {e}")
        print("  Is the Clawd daemon running? Stop it first; it holds the channel.")
        return 2

    results: Dict = {"timestamp": datetime.now().isoformat(timespec="seconds"),
                     "mac": mac, "channel": channel, "frames_source": source,
                     "simulate": args.simulate}
    try:
        if "link" in args.tests:
            results["link"] = test_link(bridge, frames, args.seconds)
        if "lag" in args.tests:
            results["lag"] = test_lag(bridge, frames, args.rates, args.seconds, args.trials, args.simulate)
        if "counter" in args.tests:
            results["counter"] = test_counter(bridge, args.rates, args.seconds, args.simulate)
    except KeyboardInterrupt:
        print("\n  interrupted — saving what we have")
    finally:
        try:
            bridge.push_image(solid(DARK))
        except Exception:
            pass
        bridge.stop()

    if args.simulate:
        return 0
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"fps_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\n  results -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
