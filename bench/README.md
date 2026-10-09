# Ditoo measurement bench

A measurement-first harness for the Divoom Ditoo: figure out what the four
channels (display, audio, mic, buttons) can actually do, with real numbers,
before we build any creative layer on top.

```
bench/
  probe.py           static detection — no Bluetooth permission needed
  display_bench.py   per-frame latency, FPS, ACK errors over 100+ pushes
  fps_ceiling.py     max streaming FPS: link throughput, on-screen lag, dropped frames
  audio_bench.py     `say` and `afplay` startup latency
  buttons_listen.py  capture inbound RFCOMM packets when you press buttons
  results/           CSV / JSONL / markdown logs from runs
```

## How to use this

### 0. Pair the Light half of the Ditoo

`probe.py` only sees the **Audio** half on your machine right now. The
**Light** half is a separate Bluetooth device that drives the pixel display.
Hold the Ditoo's power button to put it in pairing mode and connect
`Divoom Ditoo-*-Light` from System Settings → Bluetooth.

### 1. Run `probe.py`

```bash
python3 bench/probe.py
```

This needs no Bluetooth permission. It tells you:

- Is the Swift bridge present and signed?
- Which Divoom devices are paired (Audio / Light)?
- Is the Ditoo currently the system audio output?
- Which TTS voices are installed?

If the verdict says you're ready, it prints the exact command for the next step.

### 2. Run `display_bench.py` with your Light MAC

```bash
python3 bench/display_bench.py --mac <LIGHT_MAC>
```

**First run will pop a macOS dialog: "Terminal wants to use Bluetooth". Click Allow.**

Pushes 5 × 40 = 200 frames over RFCOMM at five different palette sizes (solid,
4-color, 16-color, 64-color, 256-color noise) and reports per-frame latency
percentiles plus sustained FPS. Writes a per-frame CSV under `results/`.

**What numbers tell you what:**

- p50 < 100 ms — display will feel snappy; arbitrary animation works.
- p50 100–250 ms — fine for state changes; full-frame loops at 4 fps or less.
- p50 > 250 ms — something is wrong (BT interference, wrong channel, bad pair).

The "noise" profile produces the largest packets (max palette = 256 colors) so
it's the slowest. If even "solid" is slow, the BT connection itself is the bottleneck.

### 3. Run `audio_bench.py`

```bash
python3 bench/audio_bench.py
```

Measures `say` and `afplay` wall time over N trials. Reports mean / p50 / p95 / σ.

**Important: this measures whatever audio device is *currently* the system default.**
To measure the Ditoo specifically, set System Settings → Sound → Output to the
Divoom Ditoo first, then run.

**What numbers tell you what:**

- `afplay` < 300 ms for a short clip — speakers wake fast; chimes feel instant.
- `afplay` 300–1000 ms — typical for Bluetooth speakers waking from sleep.
- `say` < 800 ms — pet voice will feel responsive.
- `say` > 1500 ms — pre-render phrases to WAVs and `afplay` them instead.

### 4. Run `buttons_listen.py` to reverse-engineer the input

```bash
# Free mode: poke around for 60 seconds, watch packets
python3 bench/buttons_listen.py --mac <LIGHT_MAC>

# Guided mode: I walk you through each button
python3 bench/buttons_listen.py --mac <LIGHT_MAC> --guided
```

The Ditoo's keyboard / play buttons *might* send inbound RFCOMM packets that we
can use as triggers. **No one in the open-source reverse-engineering community
has documented this** — that's why we measure rather than assume. The script
captures everything that comes in on the channel and tells you whether any
button press produced bytes.

Three outcomes:

1. **Bytes flow when you press buttons** — we win. Output: a signature map
   you can wire to Claude Code actions.
2. **No bytes** — try `--channel 2`, then conclude buttons aren't on this channel.
3. **Bytes flow but they're meaningless** — they exist but are heartbeats or
   power notifications. The signature map will make this obvious.

### 5. Run `fps_ceiling.py` to find the animation frame-rate budget

`writeSync` returns when a packet is queued, not when it's on screen, so the
display bench can't tell you how fast the device actually redraws. This one
attacks it from three sides:

```bash
python3 bench/fps_ceiling.py                          # link + lag
python3 bench/fps_ceiling.py counter --rates 4,8,12,16  # slow-motion video check
python3 bench/fps_ceiling.py --frames ~/.clawd/assets   # stream real Clawd frames
```

- **link** pushes frames back-to-back. If pushes start blocking, that's the
  Bluetooth ceiling; if they never block, the link isn't the limit.
- **lag** streams at each rate, then flashes green; press Enter when you see
  it. A 1 FPS run calibrates your reaction time. More than 150 ms over that
  means frames are queueing: the rate is too high.
- **counter** shows a frame number at each rate. Film it in slow motion and
  look for skipped numbers (dropped frames don't show up as lag).

Stop the Clawd daemon first (it holds the RFCOMM channel). MAC and channel come
from `~/.clawd/config.json`. Results go to `results/fps_<timestamp>.json`.

### What's deliberately not here

- **Mic capture.** The Ditoo's mic uses Bluetooth HFP, which kicks the speaker
  into 8 kHz call quality. That's a creative-direction tradeoff (do we want a
  pet that listens? at the cost of music quality?), not a measurement question.
  We'll address it in the "fun stuff" phase.

## Cleanup

Every run writes to `bench/results/` with a timestamp. Safe to delete the
directory at any time — nothing else reads from it.
