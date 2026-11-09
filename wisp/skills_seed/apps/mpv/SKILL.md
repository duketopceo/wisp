---
name: mpv
description: mpv player - keyboard-driven playback, seeking, subtitles, audio track, speed. Use for teaching playback in an mpv window.
tier: safe
app_classes: mpv
asks: How do I seek forward; How do I switch subtitles; How do I change the speed
provenance: authored: wisp seed, 2026-11-08
---
# mpv

## Teaching

### Where things live
- There is no menu bar or toolbar. A thin on-screen controller appears at the bottom when the pointer moves.
- Settings live in `~/.config/mpv/mpv.conf`, not in a dialog. Everything else is a key.

### First steps
- `Space` pauses, `F` toggles fullscreen, `M` mutes, `Q` quits. `9` and `0` turn the volume down and up.
- `Left` and `Right` seek 5 seconds, `Up` and `Down` seek a minute.
- `J` cycles subtitle tracks, `V` shows or hides them, `Hash` cycles audio tracks.
- `[` and `]` change the speed, `Backspace` resets it. `S` takes a screenshot. `Shift+I` shows playback stats.

### Linux pitfalls
- The window shows nothing to point at; point at the video and speak the key; do not invent a button.
