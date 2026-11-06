---
name: blender
description: Blender 3D editor layout and first steps - viewport, outliner, properties, render. Use for teaching the Blender interface; not for modelling technique.
tier: safe
app_classes: blender, org.blender.blender
asks: How do I move an object; How do I render an image; How do I orbit the view
provenance: authored: wisp seed, audited 2026-11-05
draft: first-run (unverified)
---
# blender

## Teaching

### Where things live
- Center: the 3D Viewport. Top-right: Outliner (scene objects). Below it: Properties (tabs down its left edge: Render, Output, Object, Modifiers, Material). Bottom: Timeline.
- Viewport header holds the mode menu (Object Mode, Edit Mode) and Shading buttons; `T` toggles the left toolbar and `N` the right sidebar.
- Blender draws its own interface, so expect no accessibility labels; point by the visible text on a tab or menu.

### First steps
- Select an object by clicking it in the viewport or the Outliner. `G` grab, `R` rotate, `S` scale, then move the mouse and click to confirm or `Esc` to cancel.
- `Shift+A` opens Add. `Tab` toggles Edit Mode. `F3` searches every menu command by name.
- Render: set the camera, then `F12` or Render > Render Image. `Ctrl+S` saves the .blend file; the render itself is saved from the render window with Image > Save As.

### Linux pitfalls
- No middle mouse button or numpad on a laptop: Edit > Preferences > Input > enable Emulate 3 Button Mouse (Alt+drag orbits) and Emulate Numpad.
- Scrolling over a number field while holding `Ctrl` changes it in steps, so a stray scroll does not move the view.
