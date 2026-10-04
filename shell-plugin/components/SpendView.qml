// Spend view of the management app: today and month against the caps, the
// paid-calls-paused state, and the per model table. `service.spend` is the
// state field (W14); `models` is `wispd spend --json` data.models, passed in
// by the app after a one-shot read.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/copy.js" as Copy
import "../lib/health.js" as H
import "../lib/manage.js" as Manage

Column {
  id: root

  property var service: null
  property var models: []

  readonly property var tk: service ? service.tokens : ({})
  readonly property var sp: H.spendView(service.spend)
  readonly property var rows: Manage.spendModels(models)
  readonly property bool dim: service.offline || service.stale

  width: 560
  spacing: M.spacing.md

  component Cell: Text {
    elide: Text.ElideRight
    color: root.dim ? root.tk.inkMuted : root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }

  Text {
    text: root.service.ui("ui.manage.spend")
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.title
    font.weight: Font.DemiBold
  }
  Text {
    text: root.service.ui("ui.manage.spend.sub")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.caption
    bottomPadding: M.spacing.lg
  }
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

  Cell {
    visible: root.sp.has
    width: root.width
    text: root.service.ui("ui.spend.today") + " " + root.sp.today + " / "
      + (root.sp.cap !== "" ? root.sp.cap : root.service.ui("ui.spend.no_cap"))
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
  Cell {
    visible: root.sp.blocked
    width: root.width
    text: root.service.ui("ui.spend.blocked")
    color: root.tk.fail
  }
  Cell {
    visible: root.sp.has
    width: root.width
    text: root.service.ui("ui.spend.month") + " " + root.sp.month + " / "
      + (root.sp.monthCap !== "" ? root.sp.monthCap : root.service.ui("ui.spend.no_cap"))
    color: root.tk.inkMuted
  }

  Text {
    text: root.service.ui("ui.health.models")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.caption
    topPadding: M.spacing.huge
  }
  Cell {
    visible: root.rows.length === 0
    width: root.width
    text: root.service.ui("ui.manage.spend.none")
    color: root.tk.inkMuted
  }
  Repeater {
    model: root.rows
    delegate: Row {
      spacing: M.spacing.xxl
      Cell { width: root.width - 3 * 96 - 3 * M.spacing.xxl; text: modelData.model }
      Cell { width: 96; text: modelData.calls + " " + root.service.ui("ui.manage.spend.calls"); color: root.tk.inkMuted }
      Cell { width: 96; text: modelData.tokens; color: root.tk.inkMuted }
      Cell { width: 96; text: modelData.usd; horizontalAlignment: Text.AlignRight }
    }
  }
}
