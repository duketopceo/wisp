"""Small helpers for writing replay scenarios (W5; used by W6)."""
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import runner  # noqa: E402

FIXTURE_DIR = runner.FIXTURE_DIR
ASK_WAV = str(FIXTURE_DIR / "ask.wav")


def load(name: str) -> dict:
    """A fresh, mutable copy of a turn fixture by short name."""
    return copy.deepcopy(runner.load_fixture(name + ".json"))


def turn(transcript: str, brain: list, *, fakes: dict | None = None,
         config: dict | None = None, expect: dict | None = None,
         name: str = "scenario") -> dict:
    """Build a fixture dict: fixed ask.wav, scripted whisper/brain, run
    on the default act router. No decision endpoint is scripted; the
    harness's Jev fake is a tripwire (see tests/harness/fakes.py)."""
    fx = {
        "name": name, "audio": ASK_WAV,
        "endpoints": {
            "whisper": {"transcript": transcript},
            "brain": {"responses": brain},
        },
        "expect": expect or {},
    }
    if fakes:
        fx["fakes"] = fakes
    if config:
        fx["config"] = config
    return fx


def probe_child_env(fx: dict) -> dict:
    """Run the fixture's fake set + a probe 'child' (a python subprocess
    with the turn's env) and report what PATH resolves to."""
    import os
    import shutil
    import subprocess
    import tempfile
    from fakes import FakeSet
    with tempfile.TemporaryDirectory(prefix="wisp-probe-") as d:
        fs = FakeSet(fx.get("fakes", {}), d).start()
        try:
            env = runner.child_env(pathlib.Path(d), fs)
            code = ("import json,shutil,os;print(json.dumps({'PATH':"
                    "os.environ['PATH'],'which_ls':shutil.which('ls'),"
                    "'which_notify':shutil.which('notify-send'),"
                    "'which_cua':shutil.which('cua-driver')}))")
            out = subprocess.run([sys.executable, "-c", code], env=env,
                                 capture_output=True, text=True,
                                 timeout=20).stdout
            return json.loads(out)
        finally:
            fs.stop()
