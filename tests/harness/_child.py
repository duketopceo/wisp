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
        cfg["stt"] = {"provider": "openai", "base_url": urls["whisper"],
                      "model": "fake", "key_env": "WISP_FAKE_STT_KEY",
                      "prompt": "static", "vocab_dynamic": "false"}
        cfg.setdefault("brain", {}).update({
            "router": "jev", "default": "openai_compat:fake-model"})
        cfg["brain.openai_compat"] = {
            "base_url": urls["brain_base"], "key_env": "",
            "vision": "false", "tools": "true"}
        if "brain2_base" in urls:
            cfg["brain.fallback_fake"] = {
                "base_url": urls["brain2_base"], "key_env": "",
                "vision": "false", "tools": "true"}
        for section, vals in spec.get("config", {}).items():
            cfg.setdefault(section, {}).update(vals)

        # -- seams: no desktop, no notifications, no real launches ----
        pipeline.notify = lambda msg: out["notifications"].append(msg)
        pipeline.active_window = lambda: {}

        def fake_record(secs, state=None):
            dst = config.CFG_DIR / "utterance.wav"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(spec["wav"], dst)
            return dst
        pipeline.record = fake_record

        def fake_launch(arg):
            out["launch_calls"].append(arg)
            return f"LAUNCHED {arg} (replay stub)"
        desc = tools.REGISTRY["launch"][2]
        tools.REGISTRY["launch"] = (fake_launch, "safe", desc)

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
                bus_obs["event_seqs"].append(ev["seq"])
                out["events"].append({
                    "t": time.monotonic(), "status": view["status"],
                    "seq": ev["seq"], "turn_id": view["turn_id"],
                    "transcript": view["transcript"],
                    "answer": view["answer"], "result": view["result"],
                    "choices": view["choices"], "error": view["error"],
                    "error_code": view.get("error_code", ""),
                    "error_detail": view.get("error_detail", ""),
                    "steps": len(view["steps"])})
        drainer = threading.Thread(target=drain, daemon=True)
        drainer.start()

        # -- chooser (stands in for the IPC choice waiter) ------------
        chooser = spec.get("chooser")
        wait = None
        if chooser is not None:
            def wait(timeout):
                time.sleep(chooser.get("delay_ms", 0) / 1000.0)
                return chooser.get("pick")

        interrupt = threading.Event()
        after = spec.get("interrupt_after_ms")
        if after is not None:
            def fire():
                interrupt.set()
                out["interrupt_fired"] = True
            threading.Timer(after / 1000.0, fire).start()

        code = pipeline.run_listen(cfg, st, wait_for_choice=wait,
                                   interrupted=interrupt.is_set)
        out["exit_code"] = code
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
