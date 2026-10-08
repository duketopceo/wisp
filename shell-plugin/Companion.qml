pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import "components"
import "lib/cursor.js" as Cursor

// Companion overlay for io.github.duketopceo.wisp.
// The corner creature/orb is gone (2026-10-07): a persistent bottom-right
// window sat over user content; the live surface is the bar pill now.
// One window remains — wisp-points, a transient overlay for the listening
// pill, answer bubble, ghost cursor and beacons. Full-output, click-through
// except the interactive items: pill, bubble.
Item {
  id: root

  property var shell: null
  property var manifest: null
  // handed over by the shell when the plugin pairs an overlay with a service
  property var service: null

  readonly property var svc: service ? service
    : (shell && manifest ? shell.serviceFor(manifest.id) : null)

  property bool bubbleDismissed: false
  property bool labeled: false
  // real pointer in layer coordinates, read once when an answer arrives
  property var pointer: null
  property int pointerRequest: 0

  // plugin contract: the shell calls these for reasons that are not ours
  // (rescan, panel sweep); an overlay with nothing persistent has nothing
  // to open, but a sweep may collapse a stale bubble.
  function open(payload) {}
  function close() { root.bubbleDismissed = true; }
  function toggle() {}
  function dismiss() { root.bubbleDismissed = true; }

  // refresh rate of the output a window sits on (QScreen has it, the
  // shell's screen object does not); creatures quantize their clock to it.
  // Application is not resolvable in every plugin context — default 60.
  function refreshOf(shellScreen) {
    if (typeof Application === "undefined" || !shellScreen) return 60;
    var list = Application.screens;
    for (var i = 0; i < list.length; i++) {
      var rate = list[i].refreshRate;
      if (list[i].name === shellScreen.name && typeof rate === "number" && isFinite(rate)) return rate;
    }
    return 60;
  }

  Connections {
    target: root.svc
    function onTurnChanged() {
      root.bubbleDismissed = false;
      root.labeled = false;
    }
    function onConfirmChanged() {
      if (root.svc.confirm === null) return;
      root.bubbleDismissed = false;
      root.pointer = null;
      root.pointerRequest += 1;
    }
    function onAnswerChanged() {
      if (root.svc.answer === "") return;
      root.bubbleDismissed = false;
      root.pointer = null;
      root.pointerRequest += 1;
    }
  }

  LazyLoader {
    active: root.svc !== null

    PanelWindow {
      id: win
      visible: layer.shown
      color: "transparent"
      anchors { left: true; right: true; top: true; bottom: true }
      exclusionMode: ExclusionMode.Ignore
      // input only where interactive: the pill and the bubble
      mask: Region {
        Region { item: layer.pillShown ? layer.pill : null }
        Region { item: layer.bubbleShown ? layer.bubbleHost : null }
      }
      WlrLayershell.namespace: "wisp-points"
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

      // One read of the real pointer per answer, no loop: the bubble opens
      // where the user is already looking and stays there.
      Process {
        id: cursorProc
        command: ["hyprctl", "cursorpos"]
        running: false
        stdout: SplitParser {
          onRead: function (data) {
            var m = /(-?\d+)[, ]+(-?\d+)/.exec(data);
            if (m) root.pointer = { x: +m[1] - win.screen.x, y: +m[2] - win.screen.y };
          }
        }
      }
      Connections {
        target: root
        function onPointerRequestChanged() { cursorProc.running = true; }
      }

      // Bubble dwell: 9 s plus 40 ms per word, paused while hovered. A
      // confirm card ignores it: the daemon's own deadline ends the card.
      Timer {
        interval: Cursor.dwellMs(root.svc.answer)
        running: layer.bubbleShown && !layer.bubbleHovered && root.svc.confirm === null
        onTriggered: root.bubbleDismissed = true
      }

      OverlayLayer {
        id: layer
        anchors.fill: parent
        service: root.svc
        pointer: root.pointer
        originX: win.screen.x
        originY: win.screen.y
        gap: Style.gapsOut
        refreshHz: root.refreshOf(win.screen)
        bubbleDismissed: root.bubbleDismissed
        labeled: root.labeled
        onChoose: function (pick, index) { root.svc.sendChoice(pick, root.svc.promptId); }
        onConfirmChosen: function (pick, promptId) { root.svc.sendChoice(pick, promptId); }
        onMoreClicked: root.bubbleDismissed = true
        onVerdict: function (verdict) { root.labeled = true; root.svc.label(verdict); }
      }
    }
  }
}
