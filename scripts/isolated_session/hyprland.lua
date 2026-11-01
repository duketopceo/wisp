-- Test-only Hyprland config for the isolated session
-- (scripts/isolated_session.py). It is deliberately bare: no Omarchy
-- defaults, no autostart, no bindings that reach the owner's tools.
-- Outputs are not declared here; `isolated_session.py start` creates the
-- two headless outputs through the instance socket and sets their modes.

-- no X11 clients: every sandbox app must speak Wayland natively, so
-- nothing can fall back to an X display on the owner's session
hl.config({
  xwayland = { enabled = false },
})
