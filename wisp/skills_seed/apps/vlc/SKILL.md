---
name: vlc
description: VLC media player - open files and streams, subtitles, audio track, speed, fullscreen. Use for teaching playback tasks in VLC.
tier: safe
app_classes: vlc
asks: How do I add subtitles; How do I change the playback speed; How do I open a network stream
provenance: authored: wisp seed, 2026-11-08
---
# vlc

## Teaching

### Where things live
- Top: the menu bar (Media, Playback, Audio, Video, Subtitle, Tools, View, Help). Bottom: play controls and the seek bar.
- Preferences are under Tools; the simple view hides some options until Show All is ticked.

### First steps
- `Ctrl+O` opens a file, `Ctrl+N` opens a network stream. `Space` plays or pauses, `F` toggles fullscreen, `M` mutes.
- `Ctrl+Up` and `Ctrl+Down` change the volume. `Shift+Left` and `Shift+Right` jump a few seconds.
- Subtitle menu, then Add Subtitle File loads one; `V` cycles subtitle tracks and `B` cycles audio tracks.
- `[` and `]` slow down and speed up playback; `=` returns to normal speed.

### Linux pitfalls
- If video is blank or green, the fix is under Tools, Preferences, Input and Codecs, hardware decoding; name the menu path, not a command.
