#!/bin/sh
# Stage-by-stage end-to-end test (no human voice needed).
# espeak-ng -> wav -> whisper.cpp -> Jev -> hyprctl launch
set -x
cd ~/src/whisper.cpp

# 1. synth speech
espeak-ng -w /tmp/dim-test.wav "open terminal"

# 2. transcribe
TRANSCRIPT=$(./build/bin/whisper-cli -m models/ggml-base.en.bin -nt -f /tmp/dim-test.wav | tr -s ' \n' ' ')
echo "TRANSCRIPT=$TRANSCRIPT"

# 3. Jev decision (uses ~/.config/dim-agent/.env)
python3 - "$TRANSCRIPT" <<'EOF'
import json, sys, pathlib, urllib.request
key = [l.split("=",1)[1].strip() for l in (pathlib.Path.home()/".config/dim-agent/.env").read_text().splitlines() if l.startswith("OPENROUTER_API_KEY=")][0]
sys.path.insert(0, str(pathlib.Path.home()/".local/opt/dim-agent"))
import importlib.util
spec = importlib.util.spec_from_file_location("dimd", pathlib.Path.home()/".local/opt/dim-agent/dimd")
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
payload = {"model": "~typesafe/jev-latest", "state": sys.argv[1], "questions": d.JEV_QUESTIONS}
req = urllib.request.Request(d.JEV_ENDPOINT, data=json.dumps(payload).encode(),
    headers={"Authorization": "Bearer "+key, "Content-Type": "application/json"})
print(json.dumps(json.loads(urllib.request.urlopen(req, timeout=30).read()), indent=2))
EOF

# 4. hyprctl launch (guarded: only because we expect launch+low risk)
# Same path dimd uses: Hyprland 0.56 Lua dispatcher (dispatch exec hits the
# hyprwm/Hyprland#16224 Lua parse bug).
export HYPRLAND_INSTANCE_SIGNATURE=$(ls $XDG_RUNTIME_DIR/hypr | head -1)
hyprctl eval 'hl.dsp.exec_cmd("ghostty")' && echo "LAUNCH OK"
