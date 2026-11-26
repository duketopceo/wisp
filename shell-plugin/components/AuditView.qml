// Audit page of the settings window: the cua audit log, read only. `log` is
// the raw cua.jsonl text (wisp/cua_safety.audit_default_path()); the view
// shows time, decision, app, tool and duration per guarded call and nothing
// else. Typed text is never in the log, and coordinates and keys stay out of
// the view too.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/manage.js" as Manage

Column {
  id: root

  property var service: null
  readonly property real ts: service ? service.textScale : 1
  // the title and its line; a settings-window page hides them and
  // shows its own heading
  property bool titled: true
  property string log: ""
  property int limit: 50

  readonly property var tk: service ? service.tokens : ({})
  readonly property var rows: Manage.auditRows(log, limit)
  // the columns reflow to the width: time, decision, tool and duration are
  // fixed, the app column takes what is left
  readonly property int gap: M.scale.space.lg
  readonly property int timeWidth: 64
  readonly property int decisionWidth: 84
  readonly property int toolWidth: 90
  readonly property int msWidth: 60
  readonly property real appWidth: Math.max(48, width - (timeWidth + decisionWidth + toolWidth + msWidth) - 4 * gap)

  width: 560
  spacing: M.scale.space.sm

  component Cell: Text {
    textFormat: Text.PlainText
    elide: Text.ElideRight
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("label", root.ts)
  }

  Text {
    textFormat: Text.PlainText
    visible: root.titled
    text: root.service.ui("ui.manage.audit")
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("title", root.ts)
    font.weight: Font.DemiBold
  }
  Text {
    textFormat: Text.PlainText
    visible: root.titled
    text: root.service.ui("ui.manage.audit.sub")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("caption", root.ts)
    bottomPadding: M.scale.space.sm
  }
  Cell {
    visible: root.rows.length === 0
    width: root.width
    text: root.service.ui("ui.manage.audit.none")
    color: root.tk.inkMuted
  }
  Repeater {
    model: root.rows
    delegate: Column {
      width: root.width
      Rectangle { width: parent.width; height: M.size.keyline; color: root.tk.keyline }
      Row {
        spacing: root.gap
        topPadding: M.scale.space.sm
        bottomPadding: M.scale.space.sm
        Cell { width: root.timeWidth; text: modelData.time; color: root.tk.inkMuted }
        Cell {
          width: root.decisionWidth
          text: root.service.ui("ui.manage.audit." + modelData.decision)
          color: root.tk[Manage.TONE_KEY[Manage.decisionTone(modelData.decision)]]
        }
        Cell { width: root.appWidth; text: modelData.app !== "" ? modelData.app : "-" }
        Cell { width: root.toolWidth; text: modelData.tool }
        Cell { width: root.msWidth; text: modelData.ms + " ms"; color: root.tk.inkMuted; horizontalAlignment: Text.AlignRight }
      }
    }
  }
}
