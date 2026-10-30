"""Child entry for the replay harness: runs ONE turn through the real
pipeline with HOME/XDG already pointed at a temp tree by the parent.

Usage: python _child.py <spec.json>   (spawned by runner.run_turn)
"""
import json
import pathlib
import shutil
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))           # tests/ -> harness pkg
sys.path.insert(0, str(HERE.parent.parent))    # repo root -> wisp pkg

from harness.runner import NetworkGuard  # noqa: E402


def main(spec_path: str) -> int:
    spec = json.loads(pathlib.Path(spec_path).read_text())
    guard = NetworkGuard()
    guard.install()
    out = {"events": [], "launch_calls": [], "notifications": [],
           "interrupt_fired": False, "violations": [], "final": {}}
    result_path = pathlib.Path(spec["result"])
    try:
        from wisp import config, pipeline, state as state_mod, \
            tools, trace as trace_mod
        urls = spec["urls"]
        config.JEV_ENDPOINT = urls["jev"] + "/api/alpha/decisions"

        cfg = config.load_config()
        cfg.setdefault("agent", {}).update({"screenshots": "false"})
        cfg.setdefault("voice", {})["enabled"] = "false"
        # Groq talk-back only for a fixture that declares the fake Groq
        # endpoint; every other fixture keeps its espeak / [voice] cmd
        cfg["voice"]["provider"] = "espeak"
        if "groq_tts" in urls:
            from wisp import tts_groq
            cfg["voice"].update(provider="groq", tts_base_url=urls["groq_tts"]
                                + "/openai/v1")
            # no desktop here: a child that sleeps the WAV's real length
            _play = ("import sys, time, wave; w = wave.open(sys.argv[1]); "
                     "time.sleep(w.getnframes() / w.getframerate())")
            tts_groq.player_argv = lambda path: [sys.executable, "-c",
                                                 _play, path]
        cfg["stt"] = {"provider": "openai", "base_url": urls["whisper"],
                      "model": "fake", "key_env": "WISP_FAKE_STT_KEY",
                      "prompt": "static", "vocab_dynamic": "false"}
        cfg.setdefault("brain", {}).update({
            "default": "openai_compat:fake-model"})
        cfg["brain.openai_compat"] = {
            "base_url": urls["brain_base"], "key_env": "",
            "vision": "false", "tools": "true"}
        if "brain2_base" in urls:
            cfg["brain.fallback_fake"] = {
                "base_url": urls["brain2_base"], "key_env": "",
                "vision": "false", "tools": "true"}
        for section, vals in spec.get("config", {}).items():
            cfg.setdefault(section, {}).update(vals)
        if "trace" in spec.get("config", {}).get("debug", {}):
            # the trace reads its own flag from the config file, which a
            # fixture does not write: pin it for this turn
            trace_mod._enabled = str(spec["config"]["debug"]["trace"]
                                     ).lower() not in (
                "false", "0", "no", "off")

        # -- seams: no desktop, no notifications, no real launches ----
        # a fixture that declares the notify / hypr fakes gets the REAL
        # code path (notify-send on PATH / the Hyprland socket)
        if not spec.get("real_notify"):
            # notify() takes keyword args (level, cfg, turn, code,
            # actions, spoken, stale); the stub accepts and ignores them
            pipeline.notify = lambda msg, *a, **k: \
                out["notifications"].append(msg)
        if spec.get("notify_now"):
            # fixed wall clock for the quiet-hours check ("YYYY-MM-DDTHH:MM")
            from datetime import datetime as _dt
            from wisp import notify as _notify
            _fixed = _dt.fromisoformat(spec["notify_now"])
            _notify._default._now = lambda: _fixed
        if not spec.get("real_hypr"):
            pipeline.active_window = lambda: {}

        if spec.get("second_start"):
            # this child plays the first daemon (B29): it holds the
            # instance lock, and a second `wispd daemon` is started while
            # the turn is in flight
            from wisp import instance
            instance.acquire()

        def second_start():
            import os
            import subprocess
            root = HERE.parent.parent
            p = subprocess.run(
                [sys.executable, str(root / "wispd"), "daemon", "run"],
                capture_output=True, text=True, timeout=60,
                env=dict(os.environ), cwd=str(root))
            out["second_start"] = {
                "rc": p.returncode, "stderr": p.stderr,
                "holder": os.getpid(),
                "sock_exists": config.SOCK_FILE.exists()}

        def fake_record(secs, state=None):
            if spec.get("second_start") and "second_start" not in out:
                second_start()
            dst = config.CFG_DIR / "utterance.wav"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(spec["wav"], dst)
            return dst
        pipeline.record = fake_record

        if spec.get("catalog"):
            from wisp.tools import adapters
            adapters.best_catalog = lambda: spec["catalog"]

        def fake_launch(arg):
            out["launch_calls"].append(arg)
            return (spec.get("launch_results") or {}).get(
                arg, f"LAUNCHED {arg} (replay stub)")
        desc = tools.REGISTRY["launch"][2]
        tools.REGISTRY["launch"] = (fake_launch, "safe", desc)

        # `tab` stub: no browser or CDP port in replay
        def fake_tab(arg):
            return (spec.get("tab_results") or {}).get(
                arg, f"SWITCHED tab {arg!r} (replay stub)")
        tab_entry = tools.REGISTRY["tab"]
        tools.REGISTRY["tab"] = (fake_tab,) + tuple(tab_entry[1:])

        # -- observe the StateBus (U2) ---------------------------------
        # Events come from a bus subscription: every write, once, in seq
        # order. Wrappers record whether anything wrote state.json
        # outside the bus, and every publish with its turn id / fate.
        import os
        t0 = time.monotonic()
        out["t0"] = t0
        bus_obs = {"publishes": [], "turn_ids": [], "dropped": 0,
                   "file_replaces": 0, "bus_writes": 0,
                   "boot_writes": 0, "outside_writes": 0,
                   "event_seqs": []}
        out["bus"] = bus_obs
        in_bus = threading.local()
        real_write = state_mod.StateBus._write_locked
        real_publish = state_mod.StateBus.publish
        real_replace = os.replace
        state_file = str(config.STATE_FILE)

        def write_locked(self):
            in_bus.on = True
            try:
                bus_obs["bus_writes"] += 1
                return real_write(self)
            finally:
                in_bus.on = False

        def publish(self, turn_id, **fields):
            ok = real_publish(self, turn_id, **fields)
            bus_obs["publishes"].append(
                {"turn": turn_id, "ok": ok, "fields": sorted(fields)})
            if turn_id is not None:
                bus_obs["turn_ids"].append(turn_id)
            if not ok:
                bus_obs["dropped"] += 1
            return ok

        def replace(src, dst, *a, **k):
            if str(dst) == state_file:
                bus_obs["file_replaces"] += 1
                if not getattr(in_bus, "on", False):
                    bus_obs["outside_writes"] += 1
            return real_replace(src, dst, *a, **k)
        state_mod.StateBus._write_locked = write_locked
        state_mod.StateBus.publish = publish
        os.replace = replace

        st = state_mod.StateBus()
        bus_obs["boot_writes"] = bus_obs["bus_writes"]
        bus_obs["file_replaces_boot"] = bus_obs["file_replaces"]
        bus_obs["file_replaces"] = 0
        bus_obs["bus_writes"] = 0
        sub = st.subscribe(maxsize=10000)
        view = dict(sub.snapshot)
        stop_drain = threading.Event()

        # -- interrupt (stands in for the user's stop) -----------------
        # `interrupt_after_ms` is wall-clock from run_listen; under CPU
        # load the pre-brain stages can outlast it, so the stop lands before
        # the turn reaches the stage it means to cancel. The event-relative
        # keys arm the timer when the drained view first shows that stage:
        #   interrupt_after_first_delta_ms: answer first non-empty
        #   interrupt_after_in_flight_ms:   first tool action in_flight
        #   interrupt_after_step_done_ms:   first tool action done
        interrupt = threading.Event()
        rel_delta = spec.get("interrupt_after_first_delta_ms")
        rel_flight = spec.get("interrupt_after_in_flight_ms")
        rel_done = spec.get("interrupt_after_step_done_ms")
        armed = {"done": False}
        timers = []

        def fire():
            out["interrupt_t"] = time.monotonic()
            out["interrupt_fired"] = True
            interrupt.set()

        def arm(ms):
            t = threading.Timer(ms / 1000.0, fire)
            t.daemon = True
            timers.append(t)
            t.start()

        def tool_status_seen(status):
            return any(a.get("kind") == "tool" and a.get("status") == status
                       for a in view.get("actions") or [])

        def arm_relative():
            if armed["done"]:
                return
            if rel_delta is not None and view.get("answer"):
                delay = rel_delta
            elif rel_flight is not None and tool_status_seen("in_flight"):
                delay = rel_flight
            elif rel_done is not None and tool_status_seen("done"):
                delay = rel_done
            else:
                return
            armed["done"] = True
            arm(delay)

        def drain():
            while True:
                ev = sub.get(0.05)
                if ev is None:
                    if stop_drain.is_set():
                        return
                    continue
                if ev.get("type") != "state":
                    continue
                view.update(ev["diff"])
                arm_relative()
                bus_obs["event_seqs"].append(ev["seq"])
                out["events"].append({
                    "t": time.monotonic(), "status": view["status"],
                    "seq": ev["seq"], "turn_id": view["turn_id"],
                    "transcript": view["transcript"],
                    "answer": view["answer"], "result": view["result"],
                    "choices": view["choices"], "error": view["error"],
                    "prompt_id": view.get("prompt_id", ""),
                    "error_code": view.get("error_code", ""),
                    "error_detail": view.get("error_detail", ""),
                    "steps": len(view["steps"]),
                    "points": [dict(pt) for pt in view.get("points") or []],
                    "drawings": [dict(d) for d in view.get("drawings") or []]})
        drainer = threading.Thread(target=drain, daemon=True)
        drainer.start()

        # -- chooser (stands in for the IPC choice waiter) ------------
        chooser = spec.get("chooser")
        wait = None
        if chooser is not None:
            def wait(timeout, **_kw):
                time.sleep(chooser.get("delay_ms", 0) / 1000.0)
                return chooser.get("pick")

        after = spec.get("interrupt_after_ms")
        if after is not None and (rel_delta is not None
                                  or rel_flight is not None
                                  or rel_done is not None):
            raise ValueError("interrupt_after_ms cannot be combined with "
                             "an event-relative interrupt key")
        if after is not None:
            arm(after)

        sp_ctx = None
        if spec.get("selection"):
            # the press-time primary selection (B22)
            from wisp import context as _context
            sp_ctx = _context.Speculative(
                {"selection": lambda: spec["selection"]}).start()
        code = pipeline.run_listen(cfg, st, wait_for_choice=wait,
                                   interrupted=interrupt.is_set,
                                   speculative=sp_ctx)
        out["exit_code"] = code
        if cfg["voice"]["enabled"] == "true":
            # run_listen returns while TTS is still playing; keep
            # observing until the turn leaves `speaking` (bounded)
            end = time.monotonic() + 5
            while view["status"] == "speaking" and time.monotonic() < end:
                time.sleep(0.02)
        time.sleep(0.2)            # let a coalesced tail flush
        stop_drain.set()
        drainer.join(timeout=2)
        out["final"] = st.snapshot()
        st.close()
        out["trace"] = trace_mod.read(tail=2000)
    finally:
        out["violations"] = list(guard.violations)
        guard.uninstall()
        result_path.write_text(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
