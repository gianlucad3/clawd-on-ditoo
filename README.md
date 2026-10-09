<div align="center">

```
        \,/                     \,/
      ___)(_____________________)(___
     /                              \
    |    (o)                  (o)    |
    |              ____              |
     \            / vv \            /
      \__________/      \__________/
        /   \              /   \
       /     \            /     \
```

# 🦀 Clawd on Ditoo

**A tiny orange crab who lives on your Divoom Ditoo Pro, judges your code, and naps when you walk away.**

*He blinks. He thinks when Claude thinks. He throws a gear when you call a tool, a heart when you ship, and a tiny existential crisis when you don't. Clap once to poke him. Clap twice to put him to bed. He speaks fluent chiptune.*

### 🖥️ [Get the Mac app →](clawd_app/)

</div>

---

## Wait, what is this

Clawd is a pixel pet for the **Divoom Ditoo Pro** (that little 16×16 retro speaker-with-a-screen). He reacts to your [Claude Code](https://claude.com/claude-code) sessions in real time — idle, thinking, tool-use, celebration, panic, sleep — and chirps about it out of the Ditoo's own speaker while your music keeps playing wherever you like. He is, frankly, the most emotionally available coworker you'll have.

> 📊 Built measurement-first, because we have *standards*. The real latency/throughput numbers are in **[FINDINGS.md](FINDINGS.md)**.

## The catch (it's a fun one)

The Ditoo line is **Bluetooth-only** — no Wi-Fi — so every "just use the Pixoo HTTP API" tutorial on the internet is, for our purposes, a beautiful lie. And despite what the write-ups claim, the Ditoo **Pro shows up as a single Bluetooth device** (`DitooPro-Audio`). There is no separate `-Light` device. That was a red herring and we fell for it so you don't have to. Pixel control rides a serial channel **on that same device — RFCOMM channel 2.**

```
Claude Code hooks ─POST localhost:7878─► Pet daemon (Python, stdlib only)
                                          │
   ┌──────────────────────────────────────┼───────────────────────────────┐
   │ state machine → 16×16 sprites         │ chiptune + spoken sounds       │  clap events
   ▼                                       ▼                                ▲
 ditoo-bridge (Swift/IOBluetooth)     ditoo-play (Swift/CoreAudio)     ditoo-ears (Swift/AVFoundation)
   │ RFCOMM ch 2                        │ routes audio to the Ditoo        │ taps the MacBook mic
   ▼                                    ▼                                  │ (keeps the Ditoo's
 Divoom Ditoo Pro — pixels           Divoom Ditoo Pro — speaker            │  audio full-quality)
```

Three tiny Swift helpers because each macOS audio/Bluetooth API is native-only and refuses to be reasoned with. Everything else is Python, so the crab stays hackable.

## The easy way: just give me the crab 🦀

Build the **[menu-bar app](clawd_app/)** once and never touch a terminal again:

```bash
./clawd_app/build.sh        # produces clawd_app/Clawd.app
open clawd_app/Clawd.app     # a little crab appears in your menu bar
```

First launch, the app will ask for **Bluetooth** and **Microphone** — say yes, that's how he sees the Ditoo and hears your claps. Then from the menu bar:

1. **Settings…** → pop in your Ditoo's MAC (find it with `./bench/discover.sh`), tweak anything you like.
2. **Start Clawd** → he hatches with a wake chirp.
3. **✓ Launch at Login** → and now he just *exists*, forever, like a good crab.

> 🔐 Why a menu-bar app and not a daemon you `sudo` into oblivion? macOS pins Bluetooth/Mic permission to whatever *launches* the thing. The app owns the daemon, so you grant permission **once** and it sticks. You're welcome.

## The terminal way (for the brave / the headless)

```bash
# 1. Find your Ditoo's MAC + confirm the pixel channel is RFCOMM 2
./bench/discover.sh

# 2. Bring him to life (he hatches with a chirp + "Hi! I'm Clawd")
./bin/clawd start --foreground --mac AA:BB:CC:DD:EE:FF -v

# 3. Wire him into your coding (reacts to your real Claude Code sessions)
./bin/clawd install-hooks
```

Replace `AA:BB:CC:DD:EE:FF` with *your* MAC. We're not putting ours on the internet again. 🙃

## How to play

- 👏 **clap once** → poke him (startle + heart + bip)
- 👏👏 **clap twice fast** → tuck him in / wake him up
- 🚶 **wander off ~1 min** → he gets restless and finds something to do: a workout (jump rope, push-ups, dumbbell press, jumping jacks, shadowboxing 🥊) or a wind-down (meditation, a cup of tea 🍵, some yoga). He rolls the dice each time.
- 😴 **…and ~5 min** → he's had enough, yawns and naps
- ⌨️ **while you're coding** → he types at the keyboard, and about once a minute gets up for a change of scene: whiteboard, rubber-duck debugging 🦆, or nose-in-the-docs (rotating, never the same one twice)

## Settings: he's high-maintenance (lovingly)

Every knob lives in `~/.clawd/config.json` — **sounds, voice, mic, animations, sleep**. The daemon applies most changes **live** (no restart): volume, brightness, nap timer, fidget frequency, clap sensitivity, the works.

Change them three ways: the **Settings window** in the menu-bar app, by hand, or via CLI:

```bash
clawd config                                    # show everything
clawd config set animations.brightness 40       # dim the mood lighting
clawd config set voice.babble false             # tell him to stop muttering
clawd config set sleep.idle_to_bored_seconds 30   # start his workout sooner
clawd config set sleep.idle_to_sleep_seconds 600  # night owl mode
```

Want to see a specific bit on demand? `clawd notify play jumprope` (also `pushups`, `weights`, `jumpingjacks`, `boxing`, `meditate`, `tea`, `yoga`) or a working look like `clawd notify play rubberduck` (also `whiteboard`, `reading`).

A few settings (`device.mac`, `device.channel`, `sounds.audio_device`) need a restart — the CLI will tell you which.

## Make him yours

- **Sprites** — `divoom_pet/sprites/clawd.py` (16-row strings, one char per pixel). Regenerate the gallery: `python3 -m divoom_pet.sprites.clawd previews/`.
- **Voice** — switchable **sound themes** in `divoom_pet/voice/themes.py`: `bubbly`
  (pitch-glide bloops, default), `marimba` (warm mallet), `music_box` (bell + echo),
  and `chip` (the original 8-bit). Shared melodies (`GESTURES`) rendered through
  per-theme voices built on a small pure-Python synth (`voice/synth.py`). Switch in
  the menu-bar app's Settings, or `clawd config set sounds.theme music_box`. Audition
  any: `clawd sounds preview --theme bubbly`. Plus `SPOKEN` TTS one-liners + live `say`.
- **Vibes** — `AUTO_TIMEOUTS` / idle behavior in `divoom_pet/daemon/state_machine.py` and the idle fidget weights in `clawd.py`.

## The full CLI

```
clawd start [--mac MAC] [--channel N] [--simulate] [--foreground] [-v]
            [--no-sound] [--audio-device NAME] [--no-ears]
            [--no-agent-badge]                 hide the finished-subagent count
            [--moods DIR | --no-moods]         mood overrides (default ~/.clawd/moods)
clawd stop
clawd state [--set STATE]              poke the state machine directly
clawd poke / chirp / demo              mess with him
clawd notify progress|badge|banner     push live content (see below)
clawd notify play|effect <name>        play a drop-in asset / procedural effect
clawd say "text"                       speak arbitrary text (live voice)
clawd sessions                         list live Claude Code sessions (fleet bar)
clawd assets [build|list]              turn assets/*.png|gif into animations
clawd watch [--repo R] [--interval S]  react to GitHub PRs / CI (needs gh)
clawd sounds [preview|render|themes]   audition the voice / list sound themes
clawd config [show | set K V]          read / change settings
clawd doctor                           "is the crab okay??"
clawd install-hooks                    wire into Claude Code
```

States: `idle thinking typing tool_use happy alert sleeping hatch poke coding`.

## Live content: Clawd shows you what's happening 📊

On top of his moods, Clawd can overlay **data** — a progress bar, a counter, a
big-moment banner — flattened onto the same 16×16 by a little compositor. Anything
can drive it through one generic surface (`POST /event` / the `clawd notify` CLI),
so it's not just Claude Code:

```bash
clawd notify progress 0.6              # a bar fills under him (0..1)
clawd notify badge 3 --color amber     # a count in the corner
clawd notify banner "MERGED" --mood happy --speak done   # a scrolling takeover
clawd notify progress --clear          # take the bar away
```

Wired into Claude Code (via `install-hooks`) he does this automatically:

- **TodoWrite → a real progress bar** (completed / total todos).
- **Subagent finishes → an "agents home" tally badge** + a delighted poke;
  `SessionStart` zeroes it. Hide the badge with `clawd start --no-agent-badge`.
- **Per-event animations** (with the mood overrides from `assets/moods/`): a
  different `tool_use` loop per tool (Bash, Edit, Read, web, subagents), its own
  `alert` for a permission prompt or a wait for input, `happy` / `alert` variants
  when a test run passes or fails, and one-shot scenes on `PreCompact` (compact)
  and `SessionEnd` (goodbye).
- **`clawd watch`** polls a repo with `gh`: a **new PR**, **CI red/green**, or a
  **merge** triggers a banner (+ mood + voice). Run it inside your repo, or point
  it anywhere with `--repo owner/name`.
- **Session fleet bar** — one pet daemon serves *all* your Claude Code sessions, so
  a strip of dots along the bottom shows each one's state at a glance: 🟠 running,
  🔴 needs-input, 🟢 finished (dropping off as they go idle). It lights up
  automatically once hooks are installed; inspect it with `clawd sessions`.

### Animations: procedural *and* drop-in

Two ways to give Clawd new moves:

```bash
clawd notify effect confetti     # procedural, "live-created" from math, no art files:
                                 #   confetti fireworks plasma pulse
                                 #   starfield matrix spinner rainbow
clawd notify clock               # show the time (HH stacked over MM)
clawd notify play laptop         # coding scenes: laptop / terminal / compile
                                 #   (the crab peeking over a laptop, claws tapping)

cp my_cute_loop.gif assets/      # drop-in: any PNG/GIF
clawd assets build               # → downscaled to 16×16, palette-snapped, named
clawd notify play my_cute_loop   # → Clawd plays it
```

Built assets are cached as plain JSON in `~/.clawd/assets/` (so the daemon loads
them with stdlib only — Pillow is needed just at `build` time, like the sounds).

### Live voice

Beyond his canned chirps, Clawd can speak *anything*:

```bash
clawd say "Pull request merged!"
clawd notify banner "MERGED" --mood happy --say "Pull request merged!"
```

A **warm vocabulary** of common announcements (PR merged, CI status, "N agents
done"…) is pre-rendered shortly after startup, so those speak instantly (~650 ms).
Anything novel renders once via `say` (~1.7 s) and is cached, so it's warm next
time. `clawd watch` uses these phrases, so a merge actually *says* "Pull request
merged!" while the banner scrolls.

### Hands-free

Let Clawd run himself — git-hook recipes (react to commits/merges), an always-on
launchd PR watcher, and a test-result wrapper all live in [`examples/`](examples/).
Copy, tweak the paths, done.

## Under the shell

```
ditoo_bridge/   Swift — Bluetooth pixel bridge (RFCOMM ch 2)
ditoo_audio/    Swift — ditoo-play, device-routed audio (+ warm-engine serve)
ditoo_ears/     Swift — ditoo-ears, clap detection on the Mac mic
clawd_app/      Swift — the menu-bar app (status, settings, tray crab)
divoom_pet/
  protocol/     Divoom packet builder (byte-identical to hass-divoom; unit-tested)
  sprites/      16×16 Clawd + states + the lively idle loop
  voice/        chiptune synth + routed player
  daemon/       HTTP server, state machine, bridge/ears drivers, live config
  hooks/        Claude Code hook dispatcher
bench/          the measurement harness that earned FINDINGS.md its receipts
previews/       PNGs + GIFs of every mood
```

## Credits & gratitude

- Protocol reverse-engineering: [hass-divoom](https://github.com/d03n3rfr1tz3/hass-divoom), [node-divoom-timebox-evo](https://github.com/RomRider/node-divoom-timebox-evo/blob/0.3.0/PROTOCOL.md), and [andreas-mausch's Ditoo Pro writeup](https://andreas-mausch.de/blog/2023-08-14-divoom-ditoo-pro/).
- Anthropic orange `#d97757`. Clawd is the community Claude Code mascot, now slightly more crab-shaped.

<div align="center">

*Be nice to Clawd. He's doing his best.* 🦀

</div>
