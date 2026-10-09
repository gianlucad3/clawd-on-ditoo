"""Top-level user CLI: clawd start|stop|state|demo|install-hooks|doctor."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

DEFAULT_URL = os.environ.get("CLAWD_DAEMON_URL", "http://127.0.0.1:7878")
ROOT = Path(__file__).resolve().parent.parent


def _post(url: str, body: dict, timeout: float = 1.0) -> Optional[dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib_request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib_error.URLError, urllib_error.HTTPError, ConnectionError, OSError) as e:
        print(f"daemon error: {e}", file=sys.stderr)
        return None


def _get(url: str, timeout: float = 1.0) -> Optional[dict]:
    try:
        with urllib_request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib_error.URLError, urllib_error.HTTPError, ConnectionError, OSError) as e:
        return None


# ---------- subcommands ----------


def cmd_start(args) -> int:
    server_args = [sys.executable, "-m", "divoom_pet.daemon.server"]
    if args.simulate:
        server_args.append("--simulate")
    else:
        if args.mac:
            server_args += ["--mac", args.mac]
        if args.channel is not None:
            server_args += ["--channel", str(args.channel)]
    if args.no_sound:
        server_args.append("--no-sound")
    if args.no_ears:
        server_args.append("--no-ears")
    if args.no_agent_badge:
        server_args.append("--no-agent-badge")
    if args.moods:
        server_args += ["--moods", args.moods]
    if args.no_moods:
        server_args.append("--no-moods")
    if args.audio_device:
        server_args += ["--audio-device", args.audio_device]
    if args.verbose:
        server_args.append("-v")
    if args.foreground:
        os.execv(sys.executable, server_args)
        return 0  # unreachable

    log_path = Path.home() / ".clawd" / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab", buffering=0) as fh:
        proc = subprocess.Popen(
            server_args,
            stdout=fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    pid_path = Path.home() / ".clawd" / "daemon.pid"
    pid_path.write_text(str(proc.pid))
    print(f"clawd started (pid={proc.pid}). logs: {log_path}")
    return 0


def cmd_stop(args) -> int:
    pid_path = Path.home() / ".clawd" / "daemon.pid"
    if not pid_path.exists():
        # Try HTTP shutdown anyway
        if _post(f"{DEFAULT_URL}/shutdown", {}):
            print("daemon told to shut down via http.")
            return 0
        print("no pidfile and daemon is not responding.")
        return 1
    pid = int(pid_path.read_text().strip())
    _post(f"{DEFAULT_URL}/shutdown", {})  # request graceful first
    time.sleep(0.5)
    try:
        os.kill(pid, 0)
        os.kill(pid, 15)  # SIGTERM
        print(f"sent SIGTERM to {pid}")
    except ProcessLookupError:
        print(f"daemon (pid={pid}) already gone.")
    pid_path.unlink(missing_ok=True)
    return 0


def cmd_state(args) -> int:
    if args.set:
        out = _post(f"{DEFAULT_URL}/state", {"state": args.set, "note": args.note or ""})
        if not out:
            return 2
        print(json.dumps(out))
        return 0
    out = _get(f"{DEFAULT_URL}/healthz")
    if not out:
        print("daemon not responding")
        return 2
    print(json.dumps(out, indent=2))
    return 0


DEMO_SEQUENCE = [
    ("hatch", 3.5, "Hello! I'm Clawd."),
    ("thinking", 3.0, "Working on something."),
    ("typing", 2.0, ""),
    ("tool_use", 3.5, "Edit"),
    ("happy", 2.6, "Done!"),
    ("alert", 2.8, "Uh oh."),
    ("sleeping", 4.0, ""),
    ("idle", 2.0, ""),
]


def _run_demo_show() -> int:
    """Guided presentation: one act per keypress, narration printed as a
    teleprompter, each act's cues fired straight at the daemon. See DEMO.md."""
    url = DEFAULT_URL
    if not _get(f"{url}/healthz"):
        print("daemon not running — Start Clawd first (or: clawd start --simulate)")
        return 2

    def st(s):       _post(f"{url}/state", {"state": s}, timeout=2)
    def ev(body):    _post(f"{url}/event", body, timeout=2)
    def say(t):      _post(f"{url}/say", {"text": t}, timeout=2)
    def ses(i, s):   _post(f"{url}/session", {"session_id": i, "status": s}, timeout=2)
    def cfg(sec, k, v): _post(f"{url}/config", {sec: {k: v}}, timeout=3)

    def coding_fallback():
        st("coding"); time.sleep(1.5)
        ev({"kind": "progress", "value": 0.3}); st("tool_use"); time.sleep(1.2)
        st("coding"); ev({"kind": "progress", "value": 0.7}); time.sleep(1.2)
        ev({"kind": "progress", "value": 1.0}); st("happy")
        time.sleep(0.6); ev({"kind": "progress", "clear": True})

    def act3_fleet():
        ses("web", "running"); ses("api", "running"); ses("infra", "finished")
        time.sleep(2.5)
        ses("web", "needs_input"); say("web needs your input")

    def act4_ship():
        ev({"kind": "banner", "text": "MERGED", "color": "green",
            "mood": "happy", "say": "Pull request merged!"})
        ev({"kind": "effect", "name": "confetti"})

    def act5_platform():
        ev({"kind": "effect", "name": "fireworks"}); time.sleep(2.5)
        cfg("sounds", "theme", "music_box"); time.sleep(0.5)
        ev({"kind": "play", "name": "laptop"}); time.sleep(2.0)
        ev({"kind": "clock"})

    def reset():
        ev({"kind": "clear"}); st("idle")

    acts = [
        ("Meet Clawd", "\"This is Clawd — he lives on a $40 retro speaker and reacts\n"
         "   to your code in real time. Clap once to poke him, twice to nap him.\"",
         "Let him idle. CLAP once (heart), then twice (sleep).", lambda: st("hatch")),
        ("He IS your coding session  [LIVE]",
         "\"Everything you'll see is Claude Code hooks -> a 16x16 display, live.\n"
         "   He types when Claude types, gear on every tool, the bar is his todo list.\"",
         "Run your real task in terminal B now.  Press [f] for the scripted fallback.", None),
        ("The fleet",
         "\"You don't run one session, you run five. One daemon serves them all -\n"
         "   amber working, green done, red needs you - and it says which one.\"",
         None, act3_fleet),
        ("Ship it",
         "\"When a session ships: confetti, and he says it out loud.\"",
         None, act4_ship),
        ("It's a platform, not a toy",
         "\"All one endpoint - `clawd notify`. Any agent, CI, or git hook drives him.\n"
         "   fireworks ... swap his whole voice live ... a drop-in animation ... a clock.\"",
         None, act5_platform),
        ("Architecture: mood vs content",
         "compositor.py - compose(base, overlays). Mood = state machine; content =\n"
         "   ProgressBar/CountBadge/SessionBar overlays flattened to one frame.",
         "Open render/compositor.py.", lambda: ev({"kind": "progress", "value": 0.5})),
        ("Architecture: the event surface",
         "server.py _handle_event + hooks/clawd-hook. Claude fires a hook -> curl\n"
         "   localhost:7878 -> one generic /event. Fire-and-forget, never blocks Claude.",
         "Open hooks/clawd-hook.", lambda: ev({"kind": "banner", "text": "HELLO DEVS", "color": "amber"})),
        ("Architecture: multi-session + the Bluetooth catch",
         "sessions.py - one daemon, keyed by session_id. And the catch: Ditoo is\n"
         "   Bluetooth-only; pixel control rides RFCOMM channel 2. Measurement-first (FINDINGS.md).",
         "Open sessions.py / FINDINGS.md.", lambda: ses("demo", "running")),
        ("Close",
         "\"He blinks, he ships, he judges your code, and he's open source.\"",
         None, lambda: ev({"kind": "effect", "name": "confetti"})),
    ]

    print("\n" + "=" * 64)
    print("  🦀  CLAWD DEMO — guided show")
    print("  [Enter] fire this act's cue + advance   [f] Act-2 fallback")
    print("  [r] re-fire last cue   [q] quit + reset")
    print("=" * 64)
    last = None
    for idx, (title, narration, stage, run) in enumerate(acts, 1):
        print(f"\n──[ {idx}/{len(acts)} ]── {title} " + "─" * max(2, 40 - len(title)))
        print(f"   {narration}")
        if stage:
            print(f"   ▸ {stage}")
        while True:
            try:
                choice = input("   > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                reset(); print("\n   demo ended, reset to idle.")
                return 0
            if choice == "q":
                reset(); print("   demo ended, reset to idle.")
                return 0
            if choice == "f":
                coding_fallback(); continue
            if choice == "r":
                (last or (lambda: None))(); continue
            if run:
                run(); last = run
            break
    reset()
    print("\n  🦀  demo complete — reset to idle.\n")
    return 0


def cmd_demo(args) -> int:
    if getattr(args, "show", False):
        return _run_demo_show()
    out = _get(f"{DEFAULT_URL}/healthz")
    if not out:
        print("daemon not running. start it first: clawd start --simulate (or with --mac)")
        return 2
    print("running demo sequence...")
    for state, hold, note in DEMO_SEQUENCE:
        r = _post(f"{DEFAULT_URL}/state", {"state": state, "note": note})
        print(f"  -> {state}  ({note})" if note else f"  -> {state}")
        time.sleep(hold)
    print("demo complete. clawd is back in idle.")
    return 0


def cmd_poke(args) -> int:
    r = _post(f"{DEFAULT_URL}/poke", {})
    if not r:
        return 2
    print(json.dumps(r))
    return 0


def cmd_chirp(args) -> int:
    body = {"chirp": args.name} if args.name else {}
    if args.speak:
        body["speak"] = args.speak
    r = _post(f"{DEFAULT_URL}/sound", body)
    if not r:
        return 2
    print(json.dumps(r))
    return 0


def cmd_notify(args) -> int:
    """Push live content to Clawd: a progress bar, a corner count badge, or a
    one-shot banner takeover. Thin wrapper over POST /event."""
    kind = args.kind
    body = {"kind": kind}

    if kind == "progress":
        if args.clear:
            body["clear"] = True
        elif args.value is not None:
            body["value"] = _coerce(args.value)
        else:
            print("usage: clawd notify progress <0..1> | --clear", file=sys.stderr)
            return 2
        if args.color:
            body["color"] = args.color
    elif kind == "badge":
        if args.clear:
            body["clear"] = True
        elif args.value is not None:
            try:
                body["count"] = int(float(args.value))
            except ValueError:
                print("badge count must be a number", file=sys.stderr)
                return 2
        else:
            print("usage: clawd notify badge <count> | --clear", file=sys.stderr)
            return 2
        if args.corner:
            body["corner"] = args.corner
        if args.color:
            body["color"] = args.color
    elif kind == "banner":
        if not args.value:
            print('usage: clawd notify banner "TEXT" [--color C] [--mood M] [--speak S]', file=sys.stderr)
            return 2
        body["text"] = args.value
        for flag in ("color", "mood", "speak", "say"):
            val = getattr(args, flag)
            if val:
                body[flag] = val
    elif kind in ("play", "effect"):
        if not args.value:
            print(f"usage: clawd notify {kind} <name> [--mood M] [--say TEXT]", file=sys.stderr)
            return 2
        body["name"] = args.value
        for flag in ("mood", "speak", "say"):
            val = getattr(args, flag)
            if val:
                body[flag] = val
    elif kind == "clock":
        if args.color:
            body["color"] = args.color
    elif kind == "clear":
        if args.value:
            body["name"] = args.value

    out = _post(f"{DEFAULT_URL}/event", body)
    if not out:
        return 2
    print(json.dumps(out))
    return 0


def cmd_assets(args) -> int:
    """Build drop-in PNG/GIF assets into 16x16 animation manifests, or list them."""
    from divoom_pet.render import assets as A

    if args.action == "build":
        src = args.src or str(ROOT / "assets")
        try:
            written = A.build_assets(src, A.ASSETS_DIR)
        except ImportError:
            print("Pillow (PIL) is required to build assets: pip install Pillow", file=sys.stderr)
            return 2
        if not written:
            print(f"no images found in {src}/ (looked for {', '.join(A.IMAGE_SUFFIXES)})")
            return 0
        print(f"built {len(written)} asset(s) into {A.ASSETS_DIR}:")
        for p in written:
            print(f"  {p.stem}")
        print("\nplay one:  clawd notify play <name>")
        return 0

    # list
    lib = A.AssetLibrary.from_dir()
    names = lib.names()
    print(f"{len(names)} asset(s) in {A.ASSETS_DIR}:")
    for n in names:
        print(f"  {n}")
    return 0


def cmd_say(args) -> int:
    """Speak arbitrary text through Clawd (live voice; warm after first use)."""
    out = _post(f"{DEFAULT_URL}/say", {"text": args.text})
    if not out:
        return 2
    print(json.dumps(out))
    return 0


def cmd_session(args) -> int:
    """Report a session's state to the fleet bar (running/finished/needs_input/idle)."""
    out = _post(f"{DEFAULT_URL}/session", {"session_id": args.id, "status": args.status})
    if not out:
        return 2
    print(json.dumps(out))
    return 0


def cmd_sessions(args) -> int:
    """List the live sessions currently on the fleet bar."""
    out = _get(f"{DEFAULT_URL}/sessions")
    if out is None:
        print("daemon not responding", file=sys.stderr)
        return 2
    sessions = out.get("sessions", [])
    if not sessions:
        print("no active sessions")
        return 0
    for s in sessions:
        print(f"  {s.get('state', '?'):12} {s.get('id', '')}")
    return 0


def cmd_watch(args) -> int:
    """Run the GitHub PR/CI watcher, feeding transitions to Clawd's event surface."""
    from divoom_pet import watch as watcher
    try:
        watcher.watch(repo=args.repo, interval=args.interval, url=DEFAULT_URL, once=args.once)
    except KeyboardInterrupt:
        print("\nstopped watching.")
    return 0


def _active_theme() -> str:
    """The configured theme (live daemon if up, else the config file)."""
    out = _get(f"{DEFAULT_URL}/config")
    if out:
        return (out.get("sounds") or {}).get("theme", "bubbly")
    from divoom_pet.config import Config
    return Config.load().sounds.theme


def cmd_sounds(args) -> int:
    import subprocess
    import tempfile
    import time as _t
    from pathlib import Path as _Path
    from divoom_pet.voice import sounds as snd, themes

    if args.action == "themes":
        active = _active_theme()
        print("sound themes:")
        for name in themes.BUILTIN_THEMES:
            mark = " (active)" if name == active else ""
            print(f"  {name}{mark}")
        print("\n  preview:  clawd sounds preview --theme music_box")
        print("  switch:   clawd config set sounds.theme music_box")
        return 0

    theme = args.theme or _active_theme()

    if args.action == "render":
        paths = snd.render_all(force=True, theme=theme)
        print(f"rendered {len(paths)} sounds ({theme}) into {snd.SOUNDS_DIR}")
        return 0

    # preview — render this theme's chirps to a temp dir (don't clobber the live cache)
    if not __import__("shutil").which("afplay"):
        print("afplay not available")
        return 2
    chirps = themes.get_theme(theme)
    print(f"Previewing the '{theme}' theme (plays on your system default output).")
    print("Set System Settings -> Sound -> Output -> Divoom Ditoo to hear it on the speaker.\n")
    order = ["wake", "think", "tool", "done", "error", "sleep", "poke"]
    with tempfile.TemporaryDirectory() as d:
        for name in order:
            fns = chirps.get(name)
            if not fns:
                continue
            p = _Path(d) / f"{name}.wav"
            snd.write_wav(p, fns[0]())
            print(f"  {name}")
            subprocess.run(["afplay", str(p)])
            _t.sleep(0.2)
    print(f"\n  That's the '{theme}' theme. Try others: clawd sounds themes")
    return 0


def cmd_doctor(args) -> int:
    ok = True

    def check(label, value, want):
        global ok
        s = "OK " if value == want else "FAIL"
        print(f"  [{s}] {label}: {value}")

    print("clawd doctor:")

    # Swift bridge present?
    bridge_app = ROOT / "ditoo_bridge" / "DitooBridge.app" / "Contents" / "MacOS" / "DitooBridge"
    bridge_bin = ROOT / "ditoo_bridge" / "ditoo-bridge"
    print(f"  bridge app exists:  {bridge_app.exists()}")
    print(f"  bridge bin exists:  {bridge_bin.exists()}")

    # macOS say available?
    say_path = subprocess.check_output(["which", "say"], text=True, stderr=subprocess.DEVNULL).strip() if subprocess.run(["which", "say"], capture_output=True).returncode == 0 else ""
    print(f"  macOS say:          {say_path or 'NOT FOUND'}")

    # Bluetooth — see paired Divoom devices
    try:
        out = subprocess.check_output(["system_profiler", "SPBluetoothDataType"], text=True, stderr=subprocess.DEVNULL)
        divoom_lines = [l.strip() for l in out.splitlines() if ("Divoom" in l or "Ditoo" in l or "Pixoo" in l) and ":" in l and "Address" not in l]
        if divoom_lines:
            print(f"  paired Divoom devices ({len(divoom_lines)}):")
            for l in divoom_lines:
                print(f"    {l}")
        else:
            print("  paired Divoom devices: none found")
    except Exception as e:
        print(f"  bluetooth scan failed: {e}")

    # Daemon
    out = _get(f"{DEFAULT_URL}/healthz")
    print(f"  daemon @ {DEFAULT_URL}: {'OK ' + json.dumps(out) if out else 'not responding'}")

    return 0


def cmd_install_hooks(args) -> int:
    """Install the clawd-hook references into ~/.claude/settings.json."""
    hook_path = ROOT / "divoom_pet" / "hooks" / "clawd-hook"
    if not hook_path.exists():
        print(f"hook script missing: {hook_path}")
        return 1
    settings_dir = Path.home() / ".claude"
    settings_path = settings_dir / "settings.json"
    settings_dir.mkdir(parents=True, exist_ok=True)

    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError as e:
            print(f"existing settings.json is not valid JSON: {e}")
            return 1
        backup = settings_path.with_suffix(".json.bak")
        backup.write_text(settings_path.read_text())
        print(f"backed up existing settings to {backup}")
    else:
        existing = {}

    hooks = existing.setdefault("hooks", {})

    HOOK_EVENTS = {
        "UserPromptSubmit": "prompt",
        "PreToolUse": "pre-tool",
        "PostToolUse": "post-tool",
        "Notification": "alert",
        "Stop": "stop",
        "SubagentStop": "subagent",
        "SessionStart": "session-start",
        "SessionEnd": "session-end",
        "PreCompact": "compact",
    }

    for event, verb in HOOK_EVENTS.items():
        cmd = f'"{hook_path}" {verb}'
        bucket = hooks.setdefault(event, [])
        # Don't double-add: skip if any entry's command already references clawd-hook.
        already = any(
            "clawd-hook" in (h.get("command", "") or "")
            for group in bucket
            for h in group.get("hooks", [])
        )
        if already:
            continue
        bucket.append({"hooks": [{"type": "command", "command": cmd}]})

    settings_path.write_text(json.dumps(existing, indent=2) + "\n")
    print(f"installed hooks into {settings_path}")
    print("clawd will now react to UserPromptSubmit / PreToolUse / PostToolUse / Notification / Stop")
    print("  + SubagentStop (agents-home tally), SessionStart (reset), SessionEnd (goodbye) and")
    print("  PreCompact (compact); TodoWrite drives a progress bar and test runs show pass/fail.")
    print()
    print("To start the daemon (in another terminal):")
    print(f"  {ROOT}/bin/clawd start --mac <DITOO_LIGHT_MAC>")
    print("  (or --simulate to test without hardware)")
    return 0


def _coerce(s: str):
    """Turn a CLI string into a bool/int/float/None where it clearly is one,
    otherwise leave it a string (so MACs and device names stay intact)."""
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def cmd_config(args) -> int:
    from divoom_pet.config import CONFIG_PATH, Config

    if args.action == "set":
        if not args.path or args.value is None:
            print("usage: clawd config set <section.key> <value>", file=sys.stderr)
            print("  e.g. clawd config set sounds.volume 0.4", file=sys.stderr)
            return 2
        section, _, key = args.path.partition(".")
        if not key:
            print("path must be section.key (e.g. animations.brightness)", file=sys.stderr)
            return 2
        partial = {section: {key: _coerce(args.value)}}
        # Prefer the live daemon (applies immediately + persists); fall back to file.
        out = _post(f"{DEFAULT_URL}/config", partial)
        if out:
            nr = out.get("needs_restart", [])
            print(f"set {args.path} = {partial[section][key]!r}")
            if nr:
                print(f"  (restart needed to apply: {', '.join(nr)})")
            return 0
        cfg = Config.load().merged(partial)
        cfg.save()
        print(f"daemon not running — wrote {CONFIG_PATH} (applies on next start)")
        return 0

    # show
    out = _get(f"{DEFAULT_URL}/config")
    if not out:
        out = Config.load().to_dict()
        print("# daemon not running — showing config file:")
    print(json.dumps(out, indent=2))
    return 0


# ---------- argparse ----------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="clawd", description="Anthropic pet on your Divoom Ditoo.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Start the pet daemon")
    p_start.add_argument("--mac", help="Ditoo BT MAC (pixel control)")
    p_start.add_argument("--channel", type=int, default=None,
                         help="RFCOMM channel (default: device.channel in ~/.clawd/config.json; Ditoo Pro = 2)")
    p_start.add_argument("--simulate", action="store_true", help="Skip Bluetooth; log frames only.")
    p_start.add_argument("--no-sound", action="store_true", help="Disable audio")
    p_start.add_argument("--no-ears", action="store_true", help="Disable clap detection")
    p_start.add_argument("--no-agent-badge", action="store_true",
                         help="Don't show the finished-subagent count badge (top-right corner)")
    p_start.add_argument("--moods", default=None,
                         help="Directory of mood manifests (idle.json, happy.json…) that replace the "
                              "built-in animations (default ~/.clawd/moods)")
    p_start.add_argument("--no-moods", action="store_true", help="Ignore mood manifests; use built-in animations")
    p_start.add_argument("--audio-device", default=None, help="Output device for sounds (default: sounds.audio_device in ~/.clawd/config.json)")
    p_start.add_argument("--foreground", action="store_true", help="Run in foreground (default: background)")
    p_start.add_argument("-v", "--verbose", action="store_true")
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="Stop the daemon")
    p_stop.set_defaults(func=cmd_stop)

    p_state = sub.add_parser("state", help="Get or set the current state")
    p_state.add_argument("--set", help="state to set (idle/thinking/typing/tool_use/happy/alert/sleeping/hatch)")
    p_state.add_argument("--note", help="optional note string")
    p_state.set_defaults(func=cmd_state)

    p_demo = sub.add_parser("demo", help="Cycle through states, or --show for the guided presentation")
    p_demo.add_argument("--show", action="store_true",
                        help="Guided demo: one act per keypress with narration (see DEMO.md)")
    p_demo.set_defaults(func=cmd_demo)

    p_poke = sub.add_parser("poke", help="Poke Clawd (startle + delight reaction)")
    p_poke.set_defaults(func=cmd_poke)

    p_chirp = sub.add_parser("chirp", help="Play a chirp / spoken line through Clawd")
    p_chirp.add_argument("name", nargs="?", help="chirp name: wake/think/tool/done/error/sleep/poke")
    p_chirp.add_argument("--speak", help="pre-rendered spoken line: hatch/done/error/poke")
    p_chirp.set_defaults(func=cmd_chirp)

    p_notify = sub.add_parser("notify", help="Push live content (progress bar / badge / banner)")
    p_notify.add_argument("kind",
                          choices=["progress", "badge", "banner", "play", "effect", "clock", "clear"])
    p_notify.add_argument("value", nargs="?",
                          help="progress 0..1 / badge count / banner text / asset|effect name / overlay to clear")
    p_notify.add_argument("--clear", action="store_true", help="clear this overlay (progress/badge)")
    p_notify.add_argument("--color", help="named color or #hex (e.g. green, amber, #d97757)")
    p_notify.add_argument("--corner", choices=["tl", "tr", "bl", "br"], help="badge corner (default tr)")
    p_notify.add_argument("--mood", help="optional state to switch to (e.g. happy) with banner/play/effect")
    p_notify.add_argument("--speak", help="optional pre-rendered line (hatch/done/error/poke)")
    p_notify.add_argument("--say", help="optional arbitrary spoken text (live voice)")
    p_notify.set_defaults(func=cmd_notify)

    p_say = sub.add_parser("say", help="Speak arbitrary text through Clawd (live voice)")
    p_say.add_argument("text", help="what Clawd should say")
    p_say.set_defaults(func=cmd_say)

    p_session = sub.add_parser("session", help="Report a session's state to the fleet bar")
    p_session.add_argument("id", help="session id")
    p_session.add_argument("status", choices=["running", "finished", "needs_input", "idle"])
    p_session.set_defaults(func=cmd_session)

    p_sessions = sub.add_parser("sessions", help="List live sessions on the fleet bar")
    p_sessions.set_defaults(func=cmd_sessions)

    p_assets = sub.add_parser("assets", help="Build drop-in PNG/GIF assets, or list them")
    p_assets.add_argument("action", nargs="?", default="list", choices=["build", "list"])
    p_assets.add_argument("--src", help="source dir of PNG/GIF (default: ./assets)")
    p_assets.set_defaults(func=cmd_assets)

    p_watch = sub.add_parser("watch", help="Watch a GitHub repo's PRs/CI and react (needs gh)")
    p_watch.add_argument("--repo", help="owner/name (default: the repo in the current dir)")
    p_watch.add_argument("--interval", type=float, default=30.0, help="poll seconds (default 30)")
    p_watch.add_argument("--once", action="store_true", help="poll once and exit (seeds baseline)")
    p_watch.set_defaults(func=cmd_watch)

    p_sounds = sub.add_parser("sounds", help="Preview/render Clawd's voice, or list themes")
    p_sounds.add_argument("action", nargs="?", default="preview",
                          choices=["preview", "render", "themes"])
    p_sounds.add_argument("--theme", help="theme to preview/render (default: active)")
    p_sounds.set_defaults(func=cmd_sounds)

    p_doctor = sub.add_parser("doctor", help="Diagnose setup")
    p_doctor.set_defaults(func=cmd_doctor)

    p_install = sub.add_parser("install-hooks", help="Install Claude Code hooks for Clawd")
    p_install.set_defaults(func=cmd_install_hooks)

    p_config = sub.add_parser("config", help="Show or change settings (sounds/voice/mic/animations/sleep)")
    p_config.add_argument("action", nargs="?", default="show", choices=["show", "set"])
    p_config.add_argument("path", nargs="?", help="section.key, e.g. sounds.volume")
    p_config.add_argument("value", nargs="?", help="new value (for set)")
    p_config.set_defaults(func=cmd_config)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
