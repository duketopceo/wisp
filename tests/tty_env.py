"""Run wispd with a pseudo-terminal on stdin, stdout and stderr, so the
tty-only views, hints and wordmark can be tested."""
import os
import pathlib
import pty
import termios
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def tty_run(env, argv, stdin_text: str = "", script: str = "wispd"):
    master, slave = pty.openpty()
    attrs = termios.tcgetattr(slave)
    attrs[3] &= ~termios.ECHO          # no echo of what the test types
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    p = subprocess.Popen([sys.executable, str(ROOT / script), *argv],
                         env=env, stdin=slave, stdout=slave, stderr=slave,
                         close_fds=True)
    os.close(slave)
    if stdin_text:
        os.write(master, stdin_text.encode())
    out = b""
    while True:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    p.wait(timeout=60)
    os.close(master)
    return p.returncode, out.decode("utf-8", "replace").replace("\r\n", "\n")
