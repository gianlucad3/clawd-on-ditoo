# Measured findings — Divoom Ditoo Pro

Real numbers measured on the user's hardware. Updated as tests run.
Device: **DitooPro-Audio** `AA:BB:CC:DD:EE:FF`, macOS 26.5, M-series.

## Audio channel (out) — MEASURED 2026-05-28

Output device set to `DitooPro-Audio` (so these are real device numbers).

| Test | mean | p50 | p95 | σ | notes |
|---|---|---|---|---|---|
| `say "Hello."` (live TTS) | 1778 ms | 1738 ms | 1966 ms | 121 ms | very consistent |
| `afplay` 150ms beep | 916 ms | 910 ms | 1196 ms | 270 ms | **bimodal** ~650 / ~1180 |

**Key insight — the speaker radio sleeps between sounds.**
- Cold (idle >~3s): ~1180 ms to first audio.
- Warm (recent playback): ~650 ms.

**Design consequences:**
1. Pre-render Clawd's phrases to WAV; `afplay` them. Live `say` adds ~1.1 s.
2. Optionally emit a silent/near-silent keep-alive tone to pin the radio awake →
   consistent ~650 ms instead of random ~1.2 s stalls.
3. Audio is for *ambient character*, not tight sync. Don't expect <500 ms reactions.

## Display channel (out) — CHANNEL FOUND 2026-05-28

SDP query on `AA:BB:CC:DD:EE:FF` returned 7 service records:

| Service | RFCOMM ch |
|---|---|
| Hands-Free unit (HFP) | 1 |
| Advanced Audio (A2DP) | — |
| **(unnamed) ← pixel control** | **2** |

**Pixel-control serial channel = RFCOMM channel 2.** Channel 1 is HFP (mic/call).

**CONFIRMED WORKING 2026-05-28** — `firstlight.py` pushed real Clawd sprites and
they rendered on the physical Ditoo Pro. Pixel control = `AA:BB:CC:DD:EE:FF`
channel 2.

Measured:
- Cold-channel first command (brightness): **591 ms** (BT wake cost, matches audio).
- Per-frame `writeSync` return: **~1 ms** (min 0 / max 4 over 8 frames).
  CAVEAT: this is *queue time* — `writeSync` returns when the packet is handed to
  the BT controller buffer, not when the device renders. Tiny 129-byte sprite
  packets slot into the buffer instantly. True on-screen latency is hidden by
  buffering (~30-100 ms typical for small BT Classic packets).

Practical takeaway: the daemon can fire frames without blocking. The true visual
refresh ceiling (when the buffer saturates and motion stutters) must be judged
by eye — see `bench/fps_visual.py`.

## Buttons (in) — RESOLVED 2026-05-29

Two guided runs on channel 2: **0 inbound bytes** from every control tested
(menu/`m`, volume±, lever, play/pause, next/prev, keyboard keys, power tap).

**Key discovery:** the lever (and the transport buttons) are standard
**Bluetooth AVRCP media keys** — pressing the lever PAUSED the user's YouTube in
the browser. macOS intercepts these as system media controls; they never reach
our RFCOMM channel.

Final classification:
| Control | Identity | Host-readable by us? |
|---|---|---|
| lever, play/pause, next/prev | AVRCP media keys | No — macOS routes to media apps |
| volume ± | HFP / system volume | No |
| `m` menu, lighting, keyboard keys | Divoom firmware-local | No — silent on serial |

**Conclusion: buttons are NOT a usable input path.**
- We *could* tap AVRCP media keys via a CGEventTap (needs Accessibility perm), but
  that would hijack play/pause from real music/video. Rejected as bad UX.
- **The microphone is the clean input channel** (HFP input, amplitude/clap detection).

Measurement phase complete. Usable channels: **display (out), audio (out), mic (in)**.

## Mic (in) — RESOLVED 2026-05-29 (use the Mac mic, not the Ditoo)

The Ditoo *does* enumerate as an HFP input, but using it would drop A2DP to
call quality. So clap detection taps the **MacBook Pro Microphone** instead —
same claps, zero impact on the Ditoo's audio.

Calibration (measured via `ditoo-ears meter`):
- Background RMS ≈ 0.0016
- Talking/desk noise peak ≈ 0.05
- **Clap peak ≈ 0.63** (10× louder than anything else)
- Defaults floor=0.06, rise=4.0 → claps detected cleanly, no false triggers from talking.

## Audio routing — SOLVED

`ditoo-play` (CoreAudio) plays sounds to a *named* output device, so Clawd's
voice goes to the Ditoo while the user's music stays on their chosen default.
A persistent `--serve` engine keeps the A2DP link warm → instant chirps instead
of the ~1.2 s cold-start.

## FINAL STATUS — full pet live on hardware 2026-05-29

All three usable channels working together on the real Ditoo Pro:
- pixels (ch 2) + chiptune/spoken voice (routed) + clap-to-poke (Mac mic)
- single clap → poke; double clap → sleep/wake; 90 s idle → sleep
- verified end-to-end via `clawd start --foreground`.

## Device topology — CONFIRMED

- The Ditoo **Pro exposes only one Bluetooth device** (`DitooPro-Audio`); there is
  **no separate `-Light` device**. Pixel control runs over a serial (SPP/RFCOMM)
  channel on the *same* device as the audio. This matches the andreas-mausch
  reverse-engineered controller.
- User also owns a Ditoo 5M (`Divoom Ditoo-5M-Audio`); using
  the Pro for now.

## Streaming frame rate — MEASURED 2026-10-08 (Timebox Evo)

Measured with `bench/fps_ceiling.py` on a Divoom Timebox Evo (RFCOMM channel 1),
streaming real 16×16 Clawd mood frames (~135 bytes per `push_image` packet):

- **Link:** 498 fps back-to-back, 65.6 KB/s; push p50 0.2 ms, p95 7.8 ms, one
  313 ms stall. Bluetooth is not the limit at animation rates.
- **On-screen lag:** no backlog at any tested rate (4–30 fps). Flash-to-Enter
  latency stayed within reaction-time spread (baseline median 393 ms); one 10 fps
  round at 2.4 s was a one-off (the other round at 10 fps was 365 ms).
- **Dropped frames:** none at 4, 8, 12 or 16 fps (slow-motion video of the frame
  counter). Not checked above 16 fps.

Practical takeaway: 8 fps (125 ms frames) used by the 16×16 animation skills has
plenty of headroom; up to 16 fps is verified drop-free.
