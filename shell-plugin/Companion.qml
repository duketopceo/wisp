pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import "components"
import "lib/cursor.js" as Cursor
import "lib/companion.js" as Companion

// Companion host for io.github.duketopceo.wisp (Ember U11 to U13).
// Window plumbing only: every visual is a component in components/, every
// piece of state comes from WispService (never state.json directly).
//   Top window     wisp-companion: corner creature + console, hidden when
//                  the focused workspace has a fullscreen window.
//   Overlay window wisp-points: pill, answer bubble, ghost cursor, beacons
//                  (a waiting Wisp stays visible over fullscreen).
// Both windows are full-output, click-through (empty input region) except
// the interactive items: creature, console, pill, bubble.
Item {
  id: root

  property var shell: null
  property var manifest: null
  // handed over by the shell when the plugin pairs an overlay with a service
  property var service: null

  readonly property var svc: service ? service
    : (shell && manifest ? shell.serviceFor(manifest.id) : null)

  // user hid the corner creature until the next Super+D or bar click
  property bool hidden: false
  property bool userOpen: false
  // the safety net fired: a stuck daemon status must not pin the console
  property bool capped: false
  property bool bubbleDismissed: false
  property bool labeled: false
  // real pointer in layer coordinates, read once when an answer arrives
  property var pointer: null
  property int pointerRequest: 0
  // width the open console takes (0 when closed), for bubble placement
  property real consoleExtent: 0

  // event-driven (Hyprland workspace state), no polling
  readonly property bool fullscreen: Hyprland.focusedWorkspace
    ? Hyprland.focusedWorkspace.hasFullscreen : false

  // refresh rate of the output a window sits on (QScreen has it, the
  // shell's screen object does not); the creature quantizes its clock to it
  function refreshOf(shellScreen) {
    var list = Application.screens;
    for (var i = 0; shellScreen && i < list.length; i++)
      if (list[i].name === shellScreen.name) return list[i].refreshRate;
    return 60;
  }

  // plugin contract: the shell calls these for reasons that are not ours
  // (rescan, panel sweep), so open() only reveals and close() only collapses
  function open(payload) { root.hidden = false; }
  function close() { root.userOpen = false; }
  function toggle() { root.userOpen = Companion.userToggle(root.userOpen); root.capped = false; }
  function dismiss() { root.userOpen = false; }

  Connections {
    target: root.svc
    function onStatusChanged() {
      root.capped = false;
      if (root.svc.status === "listening") root.hidden = false;
    }
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

  // ── top window: corner creature and console ─────────────────────
  LazyLoader {
    active: root.svc !== null

    PanelWindow {
      id: topWin
      visible: top.shown
      color: "transparent"
      anchors { left: true; right: true; top: true; bottom: true }
      exclusionMode: ExclusionMode.Ignore
      // input only where interactive: the creature's bounds and the console
      mask: Region {
        Region { item: top.cornerShown ? top.corner : null }
        Region { item: top.consoleShown ? top.consoleCard : null }
      }
      WlrLayershell.namespace: "wisp-companion"
      WlrLayershell.layer: WlrLayer.Top
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

      // Safety net (plan KTD8): the console never hangs open. One the user
      // opened compresses after 180 s, one the daemon opened (a choice) or
      // a busy one after 120 s. One-shot, runs only while the console shows.
      Timer {
        id: capTimer
        interval: root.userOpen ? 180000 : 120000
        running: top.consoleShown
        onTriggered: { root.userOpen = false; root.capped = true; }
      }
      Connections {
        target: root.svc
        function onStatusChanged() { if (capTimer.running) capTimer.restart(); }
      }

      CornerLayer {
        id: top
        anchors.fill: parent
        service: root.svc
        hidden: root.hidden
        fullscreen: root.fullscreen
        capped: root.capped
        userOpen: root.userOpen
        gap: Style.gapsOut
        refreshHz: root.refreshOf(topWin.screen)
        onConsoleExtentChanged: root.consoleExtent = consoleExtent
        onCornerClicked: root.toggle()
        onTalk: root.svc.trigger()
        onHide: { root.hidden = true; root.userOpen = false; }
        onStopClicked: root.svc.interrupt()
      }
    }
  }

  // ── overlay window: pill, bubble, ghost cursor, beacons ─────────
  LazyLoader {
    active: root.svc !== null

    PanelWindow {
      id: win
      visible: layer.shown
      color: "transparent"
      anchors { left: true; right: true; top: true; bottom: true }
      exclusionMode: ExclusionMode.Ignore
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
        consoleExtent: root.consoleExtent
        bubbleDismissed: root.bubbleDismissed
        labeled: root.labeled
        onChoose: function (pick, index) { root.svc.sendChoice(pick, root.svc.promptId); }
        onConfirmChosen: function (pick, promptId) { root.svc.sendChoice(pick, promptId); }
        onMoreClicked: { root.userOpen = true; root.capped = false; }
        onVerdict: function (verdict) { root.labeled = true; root.svc.label(verdict); }
      }
    }
  }
}
