#!/bin/sh
# fetch_whisper.sh — first-run whisper.cpp + model bootstrap.
# Builds whisper-cli and downloads the configured ggml model into
# ~/src/whisper.cpp. Idempotent: skips build if the binary and model
# already exist. Override paths with WHISPER_HOME / WHISPER_MODEL.
set -eu

WHISPER_HOME="${WHISPER_HOME:-$HOME/src/whisper.cpp}"
WHISPER_MODEL="${WHISPER_MODEL:-ggml-small.en.bin}"
BIN="$WHISPER_HOME/build/bin/whisper-cli"

if [ -x "$BIN" ] && [ -f "$WHISPER_HOME/models/$WHISPER_MODEL" ]; then
    echo "whisper already installed: $BIN (+ $WHISPER_MODEL)"
    exit 0
fi

if [ ! -d "$WHISPER_HOME" ]; then
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$WHISPER_HOME"
fi

if [ ! -x "$BIN" ]; then
    cmake -B "$WHISPER_HOME/build" -S "$WHISPER_HOME" \
        -DCMAKE_BUILD_TYPE=Release
    cmake --build "$WHISPER_HOME/build" -j --target whisper-cli
fi

MODEL_FILE="$WHISPER_HOME/models/$WHISPER_MODEL"
# A truncated fetch can leave a partial file that both this check and the
# upstream downloader would treat as installed — every real ggml model is
# >100MB, so anything under 1MB is debris. Remove it before deciding.
if [ -f "$MODEL_FILE" ] && [ "$(wc -c < "$MODEL_FILE")" -lt 1048576 ]; then
    rm -f "$MODEL_FILE"
fi
if [ ! -f "$MODEL_FILE" ]; then
    case "$WHISPER_MODEL" in
        ggml-*.bin) model="${WHISPER_MODEL#ggml-}"; model="${model%.bin}" ;;
        *) model="$WHISPER_MODEL" ;;
    esac
    sh "$WHISPER_HOME/models/download-ggml-model.sh" "$model"
    [ -s "$MODEL_FILE" ] || { echo "model download failed" >&2; exit 1; }
fi

echo "ready: $BIN -m $MODEL_FILE"
