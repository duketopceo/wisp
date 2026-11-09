---
name: obs-studio
description: OBS Studio - scenes, sources, recording, streaming, settings. Use for teaching tasks in OBS; not for stream setup advice.
tier: safe
app_classes: com.obsproject.studio
asks: How do I add a screen capture; How do I start recording; How do I change the recording folder
provenance: authored: wisp seed, 2026-11-08
---
# obs-studio

## Teaching

### Where things live
- Bottom: the Scenes and Sources docks, the Audio Mixer, and a Controls dock with Start Streaming, Start Recording and Settings. Centre: the preview.
- Sources are added with the plus button under the Sources dock.

### First steps
- Add a source with the plus under Sources. On Wayland pick Screen Capture (PipeWire); the system dialog then asks which screen.
- Click Start Recording in the Controls dock. The file lands in the folder set under Settings, then Output.
- OBS has no default hotkeys; they are assigned under Settings, then Hotkeys.

### Linux pitfalls
- Never press Start Streaming while teaching; recording is the safe first step. Streaming goes live to a real audience.
