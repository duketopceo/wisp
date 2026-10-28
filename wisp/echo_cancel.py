"""`wispd install --echo-cancel` (B33): one PipeWire config file so the mic
Wisp listens to has the speaker output cancelled out of it, which is what
lets the optional wake word run over speakers without hearing itself.

The file is a drop-in under ~/.config/pipewire/pipewire.conf.d/. Nothing
else is touched and PipeWire is not restarted for you.
"""
import pathlib

NAME = "60-wisp-echo-cancel.conf"
CONF = """\
# Written by `wispd install --echo-cancel`. Remove this file to undo it.
context.modules = [
  { name = libpipewire-module-echo-cancel
    args = {
      library.name = aec/libspa-aec-webrtc
      node.latency = 1024/48000
      capture.props = { node.name = "wisp-echo-cancel-source"
                        node.description = "Wisp echo-cancelled microphone" }
      source.props  = { node.name = "wisp-echo-cancel-source" }
      sink.props    = { node.name = "wisp-echo-cancel-sink" }
    }
  }
]
"""


def path(home) -> pathlib.Path:
    return pathlib.Path(home) / ".config" / "pipewire" / "pipewire.conf.d" / NAME


def plan(home) -> str:
    p = path(home)
    state = "replaces the existing file" if p.exists() else "creates"
    return (f"wispd install --echo-cancel {state}:\n  {p}\n"
            "It adds one PipeWire echo-cancel module and nothing else. "
            "Apply it with:\n  systemctl --user restart pipewire "
            "pipewire-pulse wireplumber\nUndo it by deleting the file.")


def write(home) -> pathlib.Path:
    p = path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(CONF, encoding="utf-8")
    return p
