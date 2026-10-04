// Audit view of the management app: the cua audit log, read only. `log` is
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
  property string log: ""
  property int limit: 50

  readonly property var tk: service ? service.tokens : ({})
  readonly property var rows: Manage.auditRows(log, limit)

  width: 560
  spacing: M.spacing.md

  component Cell: Text {
    elide: Text.ElideRight
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }

  Text {
    text: root.service.ui("ui.manage.audit")
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.title
    font.weight: Font.DemiBold
  }
  Text {
    text: root.service.ui("ui.manage.audit.sub")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.caption
    bottomPadding: M.spacing.lg
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
        spacing: M.spacing.xxl
        topPadding: M.spacing.lg
        bottomPadding: M.spacing.lg
        Cell { width: 64; text: modelData.time; color: root.tk.inkMuted }
        Cell {
          width: 84
          text: root.service.ui("ui.manage.audit." + modelData.decision)
          color: root.tk[Manage.TONE_KEY[Manage.decisionTone(modelData.decision)]]
        }
        Cell { width: 150; text: modelData.app !== "" ? modelData.app : "-" }
        Cell { width: 90; text: modelData.tool }
        Cell { width: 60; text: modelData.ms + " ms"; color: root.tk.inkMuted; horizontalAlignment: Text.AlignRight }
      }
    }
  }
}
