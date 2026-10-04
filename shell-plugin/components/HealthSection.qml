// Health section of the Settings tab: endpoints, speech, cua, spend and the
// last errors, all from the service health rows and spend field plus two
// one-shot results the Panel passes in (`cua` from wispd cua status --json,
// `spendModels` from wispd spend --json). States: all ok, a row down, cua
// down, budget blocked, stale, offline.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/health.js" as H
import "../lib/copy.js" as Copy

Column {
  id: root

  property var service: null
  property var cua: null
  property var spendModels: []

  readonly property var tk: service ? service.tokens : ({})
  readonly property var sec: H.sections(service.health)
  readonly property var sp: H.spendView(service.spend)
  readonly property var cv: H.cuaView(cua)
  readonly property var models: H.modelRows(spendModels)
  readonly property bool dim: service.offline || service.stale

  width: 340
  spacing: M.spacing.md

  component Dot: Rectangle {
    property bool good: true
    width: M.spacing.lg
    height: M.spacing.lg
    radius: width / 2
    color: good ? root.tk.ok : root.tk.fail
    opacity: root.dim ? 0.4 : 1
  }

  component Heading: Text {
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
    font.weight: Font.DemiBold
    topPadding: M.spacing.md
  }

  component Line: Text {
    width: root.width
    elide: Text.ElideRight
    color: root.dim ? root.tk.inkMuted : root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }

  component Row2: Row {
    id: r
    property bool good: true
    property string label: ""
    property string detail: ""
    spacing: M.spacing.lg
    Dot { good: r.good; anchors.verticalCenter: parent.verticalCenter }
    Text {
      text: r.label
      color: root.dim ? root.tk.inkMuted : root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      text: r.detail
      color: r.good ? root.tk.inkMuted : root.tk.fail
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
      anchors.verticalCenter: parent.verticalCenter
    }
  }

  function words(name) { return String(name).replace(/_/g, " ") }
  function errText(r) {
    if (r.code && Copy.ERRORS.hasOwnProperty(r.code)) return Copy.errorMessage(r.code)
    if (r.name === "cua" && root.cv !== null) return root.service.ui("ui.cua." + root.cv.state)
    return r.code ? words(r.code) : root.service.ui("ui.bar.down")
  }

  Heading { text: root.service.ui("ui.settings.health") }

  Text {
    // W25 moved "out of date" off service.notice (a stale turn reads
    // reconnecting in the status line); settings views still say it.
    readonly property string line: root.service.notice !== "" ? root.service.notice
      : root.service.stale ? Copy.string("state.stale") : ""
    visible: line !== ""
    text: line
    color: root.tk.needsYou
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }

  // endpoints
  Heading { text: root.service.ui("ui.health.endpoints"); font.weight: Font.Normal; color: root.tk.inkMuted; font.pixelSize: M.font.caption }
  Text {
    visible: root.sec.endpoints.length === 0
    text: root.service.ui("ui.health.none")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }
  Repeater {
    model: root.sec.endpoints
    delegate: Row2 {
      good: modelData.ok
      label: root.words(modelData.name)
      detail: modelData.ok ? (modelData.latencyMs !== null ? modelData.latencyMs + " ms" : root.service.ui("ui.bar.ok"))
        : root.service.ui("ui.bar.down")
    }
  }

  // speech
  Row2 {
    visible: root.sec.stt !== null
    good: root.sec.stt ? root.sec.stt.ok : true
    label: root.service.ui("ui.health.stt")
    detail: root.sec.stt && root.sec.stt.ok ? root.service.ui("ui.bar.ok") : root.service.ui("ui.bar.down")
  }

  // cua
  Heading { text: root.service.ui("ui.health.cua"); font.weight: Font.Normal; color: root.tk.inkMuted; font.pixelSize: M.font.caption }
  Row2 {
    good: root.sec.cua ? root.sec.cua.ok : (root.cv !== null && root.cv.live)
    label: root.cv !== null ? root.service.ui("ui.cua." + root.cv.state)
      : root.sec.cua ? (root.sec.cua.ok ? root.service.ui("ui.bar.ok") : root.service.ui("ui.bar.down"))
      : root.service.ui("ui.cua.unknown")
    detail: root.cv !== null && root.cv.version !== "" ? root.service.ui("ui.health.version") + " " + root.cv.version : ""
  }
  Line {
    visible: root.cv !== null && root.cv.fix !== ""
    text: root.service.ui("ui.health.fix") + ": " + (root.cv ? root.cv.fix : "")
    color: root.tk.inkMuted
  }
  Row {
    visible: root.cv !== null && (root.cv.kill || root.cv.dryRun)
    spacing: M.spacing.lg
    Text {
      visible: root.cv !== null && root.cv.kill
      text: root.service.ui("ui.cua.kill_switch_on")
      color: root.tk.needsYou
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
    Text {
      visible: root.cv !== null && root.cv.dryRun
      text: root.service.ui("ui.cua.dry_run")
      color: root.tk.needsYou
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
  }

  // spend
  Heading { text: root.service.ui("ui.health.spend"); font.weight: Font.Normal; color: root.tk.inkMuted; font.pixelSize: M.font.caption }
  Row2 {
    visible: root.sp.has
    good: !root.sp.blocked
    label: root.service.ui("ui.spend.today") + " " + root.sp.today + " / "
      + (root.sp.cap !== "" ? root.sp.cap : root.service.ui("ui.spend.no_cap"))
    detail: root.sp.blocked ? root.service.ui("ui.spend.blocked") : ""
  }
  Rectangle {
    visible: root.sp.has && root.sp.cap !== ""
    width: root.width
    height: M.size.tick * 2
    color: root.tk.keyline
    Rectangle {
      width: parent.width * root.sp.ratio
      height: parent.height
      color: root.sp.blocked ? root.tk.fail : root.tk.ember
    }
  }
  Line {
    visible: root.sp.has
    text: root.service.ui("ui.spend.month") + " " + root.sp.month + " / "
      + (root.sp.monthCap !== "" ? root.sp.monthCap : root.service.ui("ui.spend.no_cap"))
    color: root.tk.inkMuted
  }
  Text {
    visible: root.models.length > 0
    text: root.service.ui("ui.health.models")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.caption
  }
  Repeater {
    model: root.models
    delegate: Line {
      text: modelData.model + "  " + modelData.calls + "  " + modelData.usd
      color: root.tk.inkMuted
      font.pixelSize: M.font.caption
    }
  }

  // last errors
  Heading { text: root.service.ui("ui.health.errors"); font.weight: Font.Normal; color: root.tk.inkMuted; font.pixelSize: M.font.caption }
  Text {
    visible: root.sec.errors.length === 0
    text: root.service.ui("ui.health.no_errors")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }
  Repeater {
    model: root.sec.errors
    delegate: Line {
      text: root.words(modelData.name) + ": " + root.errText(modelData)
      color: root.tk.fail
    }
  }
}
