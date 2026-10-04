"""Record or verify CLI alias-parity transcripts (W19).

    python tests/cli_golden.py record wispd_old   # from the pre-W19 script
    python tests/cli_golden.py verify             # current wispd vs golden

Transcripts are recorded from the pre-rebuild `sys.argv` wispd (git
035aac2) against the hermetic env in cli_env.py: stdout, exit code and
the IPC commands the daemon received. The test suite replays the legacy
argv and the canonical argv against the new CLI and requires the same
stdout and IPC trace.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cli_env  # noqa: E402

GOLDEN = cli_env.ROOT / "tests" / "golden" / "cli_transcripts.json"


def run_scenario(argv, daemon, seed, exe="wispd"):
    with cli_env.CliEnv(daemon=daemon) as env:
        if seed:
            env.seed_tasks()
        code, out, err = env.run(argv, exe=exe)
        return {"stdout": out, "code": code, "ipc": list(env.ipc)}


def record(exe):
    data = {}
    for name, legacy, _canon, daemon, seed in cli_env.SCENARIOS:
        r = run_scenario(legacy, daemon, seed, exe)
        data[name] = {"argv": legacy, **r}
    GOLDEN.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    print(f"recorded {len(data)} transcripts -> {GOLDEN}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["record"]:
        record(sys.argv[2])
