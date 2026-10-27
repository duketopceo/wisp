pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import "components"
import "lib/buddy.js" as Buddy
import "lib/companion.js" as Co
import "lib/cursor.js" as Cursor

// Companion overlay for io.github.duketopceo.wisp.
// The corner creature/orb is gone (2026-10-07): a persistent bottom-right
// window sat over user content; the live surface is the bar pill now.
// One window remains — wisp-points, a transient overlay for the listening
// pill, answer bubble, cursor buddy and beacons. Full-output, click-through
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

  // --- cursor buddy feed (U2) -------------------------------------------
  // The pointer and the frame clock live here, not in components/ (which
  // bans timers and sockets). Both run only while the buddy is wanted:
  // a live status, or the model's post-turn dwell and return tail. The
  // window's screen rect (global px) is handed in by the overlay wiring;
  // the model and its view are in that screen's layer coordinates.
  property var screenRect: ({ x: 0, y: 0, w: 0, h: 0 })
  property var buddyModel: Buddy.init()
  // null until the first step; the overlay keeps Buddy's own hidden view
  property var buddyView: null
  property var pointerGlobal: null
  // the label pill's size, read back from the overlay so view() can flip it
  property var buddyPill: ({ w: 0, h: 0 })

  readonly property string buddyStatus: svc ? svc.status : "offline"
  readonly property string buddyMotion: svc ? svc.motionMode : "off"
  readonly property bool buddyLive: Buddy.LIVE.indexOf(buddyStatus) >= 0
  readonly property bool buddyWanted: buddyLive || buddyModel.phase !== "hidden"
  readonly property bool buddyFull: buddyMotion === "full"
  readonly property var pointerLayer: Buddy.layerPointer(pointerGlobal, screenRect)

  // Where the buddy points, in layer coordinates (lib/companion.js).
  readonly property var buddyTarget: svc
    ? Co.buddyTarget(svc, { x: screenRect.x, y: screenRect.y },
        svc.ui("ui.target.click"), svc.ui("ui.target.unsure"))
    : null

  function advance(dt) {
    var m = Buddy.step(root.buddyModel, {
      pointer: root.pointerLayer, status: root.buddyStatus,
      level: root.svc ? root.svc.level : 0,
      target: root.buddyTarget, motion: root.buddyMotion }, Math.min(dt, 0.25));
    root.buddyModel = m;
    var v = Buddy.view(m, { screen: { w: root.screenRect.w, h: root.screenRect.h },
      motion: root.buddyMotion, pill: root.buddyPill.w > 0 ? root.buddyPill : undefined });
    // pointer on another screen: the following buddy hides (R4)
    if (Co.buddyOffScreen(m.phase, root.pointerLayer)) v.visible = false;
    root.buddyView = v;
  }

  FrameAnimation {
    running: root.buddyWanted && root.buddyFull
    onTriggered: root.advance(frameTime)
  }

  // reduced and off motion snap, so no frame clock: a slow tick carries the
  // entry delay and the dwell tail
  Timer {
    interval: 100
    repeat: true
    running: root.buddyWanted && !root.buddyFull
    onTriggered: root.advance(0.1)
  }

  // Hyprland request socket, 30 Hz while a turn is live. One request per
  // connect; the client closes first (no PeerClosedError flood).
  Socket {
    id: ptrSock
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/hypr/"
      + Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") + "/.socket.sock"
    onConnectedChanged: {
      if (!connected) return;
      write("j/cursorpos");
      flush();
    }
    parser: SplitParser {
      splitMarker: ""
      onRead: function (text) {
        ptrSock.connected = false;
        var p = Buddy.parsePointer(text);
        if (p === null) return;
        root.pointerGlobal = p;
        if (!root.buddyFull) root.advance(0);
      }
    }
  }

  Timer {
    interval: 33
    repeat: true
    running: root.buddyLive
    // a request still open at the next tick never got its reply: drop it
    onTriggered: ptrSock.connected = !ptrSock.connected
    onRunningChanged: {
      if (running) return;
      ptrSock.connected = false;
      root.pointerGlobal = null;
    }
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
    }
    function onAnswerChanged() {
      if (root.svc.answer === "") return;
      root.bubbleDismissed = false;
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

      // Bubble dwell: 9 s plus 40 ms per word, paused while hovered. A
      // confirm card ignores it: the daemon's own deadline ends the card.
      Timer {
        interval: Cursor.dwellMs(root.svc.answer)
        running: layer.bubbleShown && !layer.bubbleHovered && root.svc.confirm === null
        onTriggered: root.bubbleDismissed = true
      }

      // this window's screen and the overlay's label pill size feed the
      // buddy model at the root
      Binding {
        target: root
        property: "screenRect"
        value: ({ x: win.screen.x, y: win.screen.y, w: win.screen.width, h: win.screen.height })
      }
      Binding {
        target: root
        property: "buddyPill"
        value: ({ w: layer.buddyPillWidth, h: layer.buddyPillHeight })
      }

      OverlayLayer {
        id: layer
        anchors.fill: parent
        service: root.svc
        barHeight: Style.bar.sizeVertical
        buddyView: root.buddyView
        buddyWanted: root.buddyWanted
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
