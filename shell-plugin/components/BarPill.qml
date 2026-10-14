// Bar pill: the live-activities row that grows beside the bar mark while
// the daemon works — the wordView word in its tone plus a mic-level meter
// while listening. While a run is live (U8) it shows a progress dot and
// the truncated intent instead of the generic word; when the run resolves
// an outcome tint (ok / fail / stopped) holds for a few seconds, then the
// pill folds away — an ambient signal, not a second panel. Motion off
// skips the tint entirely. Collapses to zero width at idle so the bar
// keeps its rest footprint; the WidgetButton's animated width does the
// grow/shrink. No timers, no polling: every value binds straight to
// WispService.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: service ? service.motionMode : "off"
  readonly property var view: service ? service.wordView : ({ word: "", tone: "muted" })
  readonly property var run: service && service.run ? service.run
    : ({ present: false, active: false, outcome: "", intent: "", key: "" })
  readonly property bool runActive: run.active === true
  readonly property string runOutcome: !runActive && run.present ? run.outcome : ""
  readonly property bool listening: service ? service.status === "listening" : false
  // the tint is up until `tintFor` catches the resolved run's key — one
  // pause per outcome, then the pill folds through the opacity behavior.
  // `tintKey` snapshots the key at tint start: a new run interrupting the
  // hold must not steal the key and lose its own outcome tint
  property string tintFor: ""
  property string tintKey: ""
  readonly property bool tintUp: runOutcome !== "" && motionMode !== "off"
    && tintFor !== run.key
  onTintUpChanged: if (tintUp) tintKey = run.key
  // live while the daemon works or waits on the user, or while a fresh
  // outcome tint is still up; an error keeps the word up until the next
  // turn so a failed ask isn't silent
  readonly property bool live: service !== null && (
    service.busy || service.status === "listening" ||
    service.status === "awaiting_choice" || service.confirm !== null ||
    service.suggestion !== null || service.status === "error" || tintUp)

  clip: true
  implicitWidth: live ? row.implicitWidth + M.spacing.lg : 0
  implicitHeight: row.implicitHeight
  opacity: live ? 1 : 0
  Behavior on opacity {
    enabled: root.motionMode !== "off"
    NumberAnimation { duration: 140 }
  }

  PauseAnimation {
    id: tintHold
    duration: 2800
    running: root.tintUp
    onStopped: root.tintFor = root.tintKey
  }

  Row {
    id: row
    anchors.verticalCenter: parent.verticalCenter
    spacing: M.spacing.md

    // progress dot while a run is live; the outcome tint in its place
    // once it resolves
    Rectangle {
      visible: root.runActive || root.tintUp
      width: M.spacing.md
      height: M.spacing.md
      radius: width / 2
      anchors.verticalCenter: parent.verticalCenter
      color: root.tintUp
        ? root.tk[root.runOutcome === "done" ? "ok"
          : root.runOutcome === "failed" ? "fail" : "inkMuted"]
        : root.tk.ember
    }

    Column {
      anchors.verticalCenter: parent.verticalCenter
      spacing: 2

      Text {
        objectName: "word"
        width: Math.min(implicitWidth, 160)
        elide: Text.ElideRight
        // a live run's intent echo replaces the generic status word
        text: root.runActive && root.run.intent !== ""
          ? root.run.intent : root.view.word
        color: root.tk[M.toneToken(root.view.tone)]
        font.family: root.service ? root.service.fontFamily : ""
        font.pixelSize: M.font.label
        font.weight: Font.DemiBold
      }

      // mic level, listening only: the pill breathes with the voice
      Rectangle {
        visible: root.listening
        width: 36
        height: 3
        radius: 1.5
        color: root.tk.inkMuted ? Qt.alpha(root.tk.inkMuted, 0.35) : "transparent"
        Rectangle {
          width: parent.width * Math.max(0.08, root.service ? root.service.level : 0)
          height: parent.height
          radius: parent.radius
          color: root.tk.ember
        }
      }
    }
  }
}
