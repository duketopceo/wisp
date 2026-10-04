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

        # -- observe state transitions --------------------------------
        t0 = time.monotonic()
        out["t0"] = t0
        real_transition = state_mod.State.transition

        def transition(self, status, **fields):
            real_transition(self, status, **fields)
            snap = self.snapshot()
            out["events"].append({
                "t": time.monotonic(), "status": status,
                "transcript": snap["transcript"], "answer": snap["answer"],
                "result": snap["result"], "choices": snap["choices"],
                "error": snap["error"], "steps": len(snap["steps"])})
        state_mod.State.transition = transition

        st = state_mod.State()

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
        out["final"] = st.snapshot()
        out["trace"] = trace_mod.read(tail=2000)
    finally:
        out["violations"] = list(guard.violations)
        guard.uninstall()
        result_path.write_text(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
