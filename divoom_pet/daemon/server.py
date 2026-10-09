"""HTTP server for the pet daemon. Plain stdlib — no FastAPI dependency required.

Endpoints (all POST or GET, accept JSON bodies):

  GET  /healthz                 -> {"ok": true, "state": "..."}
  POST /state                   -> {"state": "thinking", "note": "..."}
  POST /touch                   -> {} (resets idle->sleep timer)
  POST /shutdown                -> {} (stops the daemon cleanly)
  POST /say                     -> {"text": "Hello"} (test the voice)
  POST /event                   -> live content: progress bars, count badges,
                                   banner takeovers. See _handle_event for the
                                   accepted shapes; driven by the `clawd notify` CLI.

Designed to be called from Claude Code hooks via `curl --max-time 0.5 ...`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional

from divoom_pet.config import CONFIG_PATH, Config
from divoom_pet.render import COLORS, CountBadge, ProgressBar, SessionBar, banner, compose, parse_color
from divoom_pet.render.assets import MOODS_DIR, AssetLibrary
from divoom_pet.render.clock import clock_takeover
from divoom_pet.render.effects import EFFECTS
from divoom_pet.sprites import IdleOpts, State
from divoom_pet.sprites.coding import SCENES as CODING_SCENES
from divoom_pet.sprites.sports import SCENES as SPORT_SCENES

# In-code scenes playable by name via `notify play` (asset library wins on a clash).
NAMED_SCENES = {**CODING_SCENES, **SPORT_SCENES}

from .sessions import VALID_STATES, SessionRegistry, session_state_for_mood

from .bridge import DitooBridge, find_bundled_bridge
from .ears import Ears, find_ears_binary
from .moods import describe as describe_moods, moods_from_dir
from .state_machine import PetController
from divoom_pet.voice.sounds import SoundPlayer

log = logging.getLogger("server")


# ---------- session fleet bar ----------


def refresh_session_bar(registry: SessionRegistry, controller, now: float) -> None:
    """Prune dead sessions and (re)draw the bottom dot strip — but only touch the
    overlay when the set of states actually changed, to avoid needless repaints."""
    registry.prune(now)
    states = registry.states()
    current = controller.get_overlay("sessions")
    current_states = current.states if isinstance(current, SessionBar) else None
    if states:
        if states != current_states:
            controller.set_overlay("sessions", SessionBar(states=states))
    elif current is not None:
        controller.clear_overlay("sessions")


# ---------- HTTP handler ----------


class PetHandler(BaseHTTPRequestHandler):
    controller: PetController = None  # set by main()
    sounds: SoundPlayer = None
    ears: Optional["Ears"] = None
    config: Config = None
    config_path: Path = CONFIG_PATH
    assets: Optional[AssetLibrary] = None
    sessions: Optional[SessionRegistry] = None

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        log.debug("http: " + fmt, *args)

    # ----- helpers -----

    MAX_BODY = 1 << 20  # 1 MiB — bodies are tiny JSON; cap so a bogus
    #                     Content-Length can't trigger a huge allocation.

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, self.MAX_BODY))
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ----- routes -----

    def do_GET(self) -> None:
        if self.path.startswith("/healthz"):
            return self._reply(200, {
                "ok": True,
                "state": self.controller.current_state().value,
                "bridge_alive": self.controller.bridge.is_alive(),
            })
        if self.path.startswith("/state"):
            return self._reply(200, {"state": self.controller.current_state().value})
        if self.path.startswith("/config"):
            return self._reply(200, self.config.to_dict())
        if self.path.startswith("/sessions"):
            if self.sessions is None:
                return self._reply(200, {"sessions": []})
            self.sessions.prune(time.time())
            return self._reply(200, {
                "sessions": [{"id": sid, "state": st} for sid, st in self.sessions.snapshot()],
            })
        return self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self._read_json()
        if self.path == "/state":
            name = (body.get("state") or "").lower()
            try:
                target = State(name)
            except ValueError:
                return self._reply(400, {"error": f"unknown state: {name}"})
            self.controller.set_state(target, note=body.get("note", ""))
            # A session_id rides along on hook posts: track this session in the fleet.
            session_id = body.get("session_id")
            if session_id and self.sessions is not None:
                self.sessions.update(str(session_id), session_state_for_mood(target.value), time.time())
                refresh_session_bar(self.sessions, self.controller, time.time())
            return self._reply(200, {"ok": True, "state": target.value})
        if self.path == "/session":
            session_id = str(body.get("session_id") or "").strip()
            status = str(body.get("status") or "").strip().lower()
            if not session_id:
                return self._reply(400, {"error": "session needs a 'session_id'"})
            if status not in VALID_STATES:
                return self._reply(400, {"error": f"status must be one of {sorted(VALID_STATES)}"})
            if self.sessions is not None:
                self.sessions.update(session_id, status, time.time())
                refresh_session_bar(self.sessions, self.controller, time.time())
            return self._reply(200, {"ok": True, "session_id": session_id, "status": status})
        if self.path == "/touch":
            self.controller.touch()
            return self._reply(200, {"ok": True})
        if self.path == "/poke":
            self.controller.poke()
            return self._reply(200, {"ok": True})
        if self.path == "/sound":
            name = body.get("chirp")
            spoken = body.get("speak")
            if self.sounds and name:
                self.sounds.chirp(name)
            if self.sounds and spoken:
                self.sounds.speak(spoken)
            return self._reply(200, {"ok": True})
        if self.path == "/say":
            text = (body.get("text") or "").strip()
            if not text:
                return self._reply(400, {"error": "say needs a non-empty 'text'"})
            if self.sounds:
                self.sounds.say(text)
            return self._reply(200, {"ok": True, "text": text})
        if self.path == "/event":
            return self._handle_event(body)
        if self.path == "/config":
            try:
                new_cfg = self.config.merged(body)
            except Exception as e:  # malformed body
                return self._reply(400, {"error": f"bad config: {e}"})
            needs_restart = apply_config(new_cfg, self.config, self.controller, self.sounds, self.ears)
            try:
                new_cfg.save(self.config_path)
            except OSError as e:
                log.warning("could not persist config: %s", e)
            PetHandler.config = new_cfg
            return self._reply(200, {"ok": True, "config": new_cfg.to_dict(), "needs_restart": needs_restart})
        if self.path == "/shutdown":
            threading.Thread(target=self._delayed_shutdown, daemon=True).start()
            return self._reply(200, {"ok": True})
        return self._reply(404, {"error": "not found"})

    def _delayed_shutdown(self) -> None:
        import time as _t
        _t.sleep(0.1)
        os.kill(os.getpid(), signal.SIGTERM)

    # ----- live content -----

    def _handle_event(self, body: dict):
        """Generic ingestion surface. Maps an event dict to overlays / takeovers /
        voice so any source (git hook, GitHub poller, CI, another session) can feed
        Clawd. Shapes (all keys optional unless noted):

          {"kind":"progress","value":0.0..1.0,"color":"green"}   persistent bar
          {"kind":"progress","clear":true}                       remove the bar
          {"kind":"badge","count":3,"corner":"tr","color":"amber"} corner counter
          {"kind":"badge","clear":true}                          remove the badge
          {"kind":"banner","text":"MERGED","color":"green",      one-shot marquee
              "mood":"happy","speak":"done"}                     (+ optional mood/voice)
          {"kind":"play","name":"confetti_gif","mood":"happy"}   a built asset by name
          {"kind":"effect","name":"confetti"}                    a procedural effect
          {"kind":"clock","color":"cyan"}                        show the time (HH over MM)
          {"kind":"agent_done"}                                  tick the agent tally
          {"kind":"agents_reset"}                                zero the tally + badge
          {"kind":"clear","name":"progress"}                     clear one / all
        """
        kind = (body.get("kind") or "").lower()
        c = self.controller

        if kind == "progress":
            if body.get("clear"):
                c.clear_overlay("progress")
                return self._reply(200, {"ok": True, "cleared": "progress"})
            try:
                value = float(body.get("value", 0.0))
            except (TypeError, ValueError):
                return self._reply(400, {"error": "progress needs a numeric 'value' (0..1)"})
            fg = parse_color(body.get("color"), COLORS["green"])
            c.set_overlay("progress", ProgressBar(value=value, fg=fg))
            return self._reply(200, {"ok": True, "kind": "progress", "value": value})

        if kind == "badge":
            if body.get("clear"):
                c.clear_overlay("badge")
                return self._reply(200, {"ok": True, "cleared": "badge"})
            try:
                count = int(body.get("count", 0))
            except (TypeError, ValueError):
                return self._reply(400, {"error": "badge needs an integer 'count'"})
            color = parse_color(body.get("color"), COLORS["yellow"])
            corner = str(body.get("corner", "tr"))
            c.set_overlay("badge", CountBadge(count=count, corner=corner, color=color))
            return self._reply(200, {"ok": True, "kind": "badge", "count": count})

        if kind == "banner":
            text = str(body.get("text", ""))[:64]
            color = parse_color(body.get("color"), COLORS["orange"])
            c.play_takeover(banner(text, color=color))
            self._mood_and_speak(body)
            return self._reply(200, {"ok": True, "kind": "banner", "text": text})

        if kind == "play":
            name = str(body.get("name", ""))
            anim = self.assets.get(name) if self.assets else None
            if anim is None and name in NAMED_SCENES:
                # In-code scene → compose its sprites; loop a few times for a one-shot.
                anim = [(compose(sprite), ms) for sprite, ms in NAMED_SCENES[name]] * 3
            if not anim:
                available = (self.assets.names() if self.assets else []) + list(NAMED_SCENES)
                return self._reply(404, {"error": f"no asset/scene named {name!r}",
                                         "available": available})
            c.play_takeover(anim)
            self._mood_and_speak(body)
            return self._reply(200, {"ok": True, "kind": "play", "name": name,
                                     "frames": len(anim)})

        if kind == "effect":
            name = (body.get("name") or "").lower()
            generator = EFFECTS.get(name)
            if not generator:
                return self._reply(404, {"error": f"unknown effect {name!r}",
                                         "available": sorted(EFFECTS)})
            c.play_takeover(generator())
            self._mood_and_speak(body)
            return self._reply(200, {"ok": True, "kind": "effect", "name": name})

        if kind == "clock":
            color = parse_color(body.get("color"), COLORS["cyan"])
            now = time.localtime()
            c.play_takeover(clock_takeover(now.tm_hour, now.tm_min, color=color))
            return self._reply(200, {"ok": True, "kind": "clock",
                                     "time": f"{now.tm_hour:02d}:{now.tm_min:02d}"})

        if kind == "agent_done":
            count = c.agent_came_home()
            return self._reply(200, {"ok": True, "kind": "agent_done", "count": count})

        if kind == "agents_reset":
            c.reset_agents()
            return self._reply(200, {"ok": True, "kind": "agents_reset"})

        if kind == "clear":
            name = body.get("name")
            c.clear_overlay(name)  # None clears all overlays
            return self._reply(200, {"ok": True, "cleared": name or "all"})

        return self._reply(400, {"error": f"unknown event kind: {kind!r}"})

    def _mood_and_speak(self, body: dict) -> None:
        """Optional extras attached to an event: `mood` (state switch), `speak` (a
        named pre-rendered line), and `say` (arbitrary live-voice text)."""
        mood = body.get("mood")
        if mood:
            try:
                self.controller.set_state(State(str(mood).lower()), note="event")
            except ValueError:
                pass
        if self.sounds:
            spoken = body.get("speak")
            if spoken:
                self.sounds.speak(str(spoken))
            say_text = body.get("say")
            if say_text:
                self.sounds.say(str(say_text))


# ---------- live config application ----------


def _idle_opts_from(cfg: Config) -> IdleOpts:
    return IdleOpts(
        fidgets=cfg.animations.idle_fidgets,
        frequency=cfg.animations.fidget_frequency,
        blink=cfg.animations.blink,
    )


def apply_config(new: Config, old: Config, controller: PetController,
                 sounds: Optional[SoundPlayer], ears: Optional["Ears"]) -> List[str]:
    """Apply a new config to the live daemon, in place where possible. Returns the
    list of dotted setting paths that could NOT be applied live (need a restart)."""
    needs_restart: List[str] = []

    # animations + sleep — all live
    if new.animations.brightness != old.animations.brightness:
        controller.set_brightness(new.animations.brightness)
    controller.idle_to_bored = new.sleep.idle_to_bored_seconds
    controller.idle_to_sleep = new.sleep.idle_to_sleep_seconds
    controller.idle_opts = _idle_opts_from(new)

    # sounds + voice
    if sounds:
        sounds.enabled = new.sounds.enabled and shutil.which("afplay") is not None
        sounds.babble = new.voice.babble
        sounds.spoken_lines = new.voice.spoken_lines
        if new.sounds.volume != old.sounds.volume:
            sounds.set_volume(new.sounds.volume)
        if new.sounds.theme != old.sounds.theme:
            sounds.set_theme(new.sounds.theme)
        if new.voice.tts_voice != old.voice.tts_voice:
            sounds.set_tts_voice(new.voice.tts_voice)
        if new.sounds.audio_device != old.sounds.audio_device:
            needs_restart.append("sounds.audio_device")

    # mic / clap detection
    if ears:
        if new.mic.enabled != old.mic.enabled:
            ears.set_enabled(new.mic.enabled)
        if (new.mic.clap_floor, new.mic.clap_rise, new.mic.double_window) != \
           (old.mic.clap_floor, old.mic.clap_rise, old.mic.double_window):
            ears.reconfigure(new.mic.clap_floor, new.mic.clap_rise, new.mic.double_window)
    elif new.mic.enabled and not old.mic.enabled:
        needs_restart.append("mic.enabled")  # no ears object built this run

    # device — bridge MAC/channel are bound at startup
    if new.device.mac != old.device.mac:
        needs_restart.append("device.mac")
    if new.device.channel != old.device.channel:
        needs_restart.append("device.channel")

    return needs_restart


# ---------- main ----------


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)-7s %(levelname).1s %(message)s",
        datefmt="%H:%M:%S",
    )


def _resolve_mac(arg_mac: Optional[str]) -> str:
    if arg_mac:
        return arg_mac
    env = os.environ.get("DITOO_MAC")
    if env:
        return env
    raise SystemExit("No Ditoo MAC. Pass --mac AA:BB:CC:DD:EE:FF or set DITOO_MAC env var.")


def _overrides_from_args(args) -> dict:
    """CLI flags, when explicitly passed, override the config file. Defaults are
    None so 'not passed' leaves the config value untouched."""
    o: dict = {}
    if args.mac:
        o.setdefault("device", {})["mac"] = args.mac
    if args.channel is not None:
        o.setdefault("device", {})["channel"] = args.channel
    if args.no_sound:
        o.setdefault("sounds", {})["enabled"] = False
    if args.audio_device is not None:
        o.setdefault("sounds", {})["audio_device"] = args.audio_device
    if args.no_ears:
        o.setdefault("mic", {})["enabled"] = False
    if args.clap_floor is not None:
        o.setdefault("mic", {})["clap_floor"] = args.clap_floor
    if args.clap_rise is not None:
        o.setdefault("mic", {})["clap_rise"] = args.clap_rise
    return o


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="clawd-daemon")
    parser.add_argument("--mac", help="Ditoo BT MAC (overrides config)")
    parser.add_argument("--channel", type=int, default=None, help="RFCOMM channel id (Ditoo Pro = 2)")
    parser.add_argument("--port", type=int, default=7878, help="HTTP port")
    parser.add_argument("--bind", default="127.0.0.1", help="HTTP bind addr")
    parser.add_argument("--config", default=None, help="Path to config.json (default ~/.clawd/config.json)")
    parser.add_argument("--simulate", action="store_true", help="Do not connect Bluetooth; log frames only.")
    parser.add_argument("--no-sound", action="store_true", help="Disable all audio")
    parser.add_argument("--no-ears", action="store_true", help="Disable clap detection")
    parser.add_argument("--no-agent-badge", action="store_true",
                        help="Don't show the finished-subagent count badge (top-right corner)")
    parser.add_argument("--moods", default=None,
                        help="Directory of mood manifests (idle.json, happy.json…) that replace the "
                             "built-in animations (default ~/.clawd/moods)")
    parser.add_argument("--no-moods", action="store_true", help="Ignore mood manifests; use built-in animations")
    parser.add_argument("--audio-device", default=None, help="Output device substring for sounds")
    parser.add_argument("--clap-floor", type=float, default=None, help="Clap detector RMS floor")
    parser.add_argument("--clap-rise", type=float, default=None, help="Clap detector rise factor")
    parser.add_argument("--bridge", default=None, help="Path to ditoo-bridge binary (defaults to bundled)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    config_path = Path(args.config) if args.config else CONFIG_PATH
    cfg = Config.load(config_path).merged(_overrides_from_args(args))
    log.info("config: %s", json.dumps(cfg.to_dict()))

    mac = "00:00:00:00:00:00" if args.simulate else _resolve_mac(cfg.device.mac)
    bridge_path = Path(args.bridge) if args.bridge else find_bundled_bridge()
    log.info("bridge binary: %s", bridge_path)

    bridge = DitooBridge(binary=bridge_path, mac=mac, channel=cfg.device.channel, simulate=args.simulate)
    sounds = SoundPlayer(
        enabled=cfg.sounds.enabled, device=cfg.sounds.audio_device,
        volume=cfg.sounds.volume, babble=cfg.voice.babble,
        spoken_lines=cfg.voice.spoken_lines, tts_voice=cfg.voice.tts_voice,
        theme=cfg.sounds.theme,
    )
    controller = PetController(
        bridge=bridge, sounds=sounds,
        brightness=cfg.animations.brightness,
        idle_to_bored=cfg.sleep.idle_to_bored_seconds,
        idle_to_sleep=cfg.sleep.idle_to_sleep_seconds,
        idle_opts=_idle_opts_from(cfg),
        agent_badge=not args.no_agent_badge,
        moods={} if args.no_moods else moods_from_dir(Path(args.moods) if args.moods else MOODS_DIR),
    )
    if controller.moods:
        log.info("mood overrides: %s", describe_moods(controller.moods))

    # Clap detection (optional). Single clap pokes; double clap toggles sleep.
    ears = None
    if cfg.mic.enabled:
        try:
            ears = Ears(
                binary=find_ears_binary(),
                on_clap=controller.poke,
                on_double_clap=controller.toggle_sleep,
                floor=cfg.mic.clap_floor,
                rise=cfg.mic.clap_rise,
                double_window=cfg.mic.double_window,
            )
        except FileNotFoundError as e:
            log.warning("ears unavailable: %s", e)

    PetHandler.controller = controller
    PetHandler.sounds = sounds
    PetHandler.ears = ears
    PetHandler.config = cfg
    PetHandler.config_path = config_path
    PetHandler.assets = AssetLibrary.from_dir()
    log.info("asset library: %d animation(s) %s", len(PetHandler.assets.names()),
             PetHandler.assets.names())
    sessions = SessionRegistry()
    PetHandler.sessions = sessions

    controller.start(initial_state=State.HATCH)

    # Periodically expire stale sessions so the fleet bar clears on its own.
    def _prune_sessions() -> None:
        while True:
            time.sleep(8.0)
            try:
                refresh_session_bar(sessions, controller, time.time())
            except Exception as e:
                log.debug("session prune failed: %s", e)

    threading.Thread(target=_prune_sessions, daemon=True, name="session-prune").start()
    if ears:
        try:
            ears.start()
        except Exception as e:
            log.warning("could not start ears: %s", e)
    log.info("clawd alive. POST http://%s:%d/state {\"state\":\"thinking\"}", args.bind, args.port)

    httpd = ThreadingHTTPServer((args.bind, args.port), PetHandler)

    def _signal_handler(signum, frame):
        log.info("signal %d, shutting down", signum)
        if ears:
            ears.stop()
        controller.stop()
        sounds.stop()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        httpd.serve_forever()
    finally:
        log.info("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
