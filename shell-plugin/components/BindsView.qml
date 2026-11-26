// Binds page of the settings window: the hold-to-talk chord and the Hyprland
// binds wisp registered (`wispd binds --json` data, passed in by the app).
// Binds that belong to a submap (W24: Esc stops, Enter confirms, number keys
// choose) get their own list; without W24 the view says the submap is not
// installed instead of showing an empty list.
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
  property var binds: null

  readonly property var tk: service ? service.tokens : ({})
  readonly property var view: Manage.bindsView(binds)

  width: 560
  spacing: M.scale.space.sm

  component Cell: Text {
    textFormat: Text.PlainText
    elide: Text.ElideRight
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("label", root.ts)
  }

  component Sub: Text {
    textFormat: Text.PlainText
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("caption", root.ts)
    topPadding: M.scale.space.lg
  }

  Text {
    textFormat: Text.PlainText
    visible: root.titled
    text: root.service.ui("ui.manage.binds")
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("title", root.ts)
    font.weight: Font.DemiBold
  }
  Text {
    textFormat: Text.PlainText
    visible: root.titled
    text: root.service.ui("ui.manage.binds.sub")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("caption", root.ts)
    bottomPadding: M.scale.space.sm
  }

  Row {
    spacing: M.scale.space.md
    Cell { width: 160; text: root.view.hotkey !== "" ? root.view.hotkey : "-"; font.weight: Font.DemiBold }
    Cell { text: root.service.ui("ui.manage.binds.hold"); color: root.tk.inkMuted }
  }
  Cell {
    visible: !root.view.hyprland
    width: root.width
    text: root.service.ui("ui.manage.binds.no_hypr")
    color: root.tk.needsYou
  }

  Sub { text: root.service.ui("ui.manage.binds.global") }
  Cell {
    visible: root.view.hyprland && root.view.global.length === 0
    width: root.width
    text: root.service.ui("ui.manage.binds.none")
    color: root.tk.inkMuted
  }
  Repeater {
    model: root.view.global
    delegate: Row {
      spacing: M.scale.space.md
      Cell { width: 160; text: modelData.chord }
      Cell { width: root.width - 160 - M.scale.space.md; text: modelData.arg; color: root.tk.inkMuted }
    }
  }

  Sub { text: root.service.ui("ui.manage.binds.submap") }
  Cell {
    visible: !root.view.hasSubmap
    width: root.width
    text: root.service.ui("ui.manage.binds.no_submap")
    color: root.tk.inkMuted
  }
  Repeater {
    model: root.view.submaps
    delegate: Row {
      spacing: M.scale.space.md
      Cell { width: 160; text: modelData.chord }
      Cell { width: root.width - 160 - M.scale.space.md; text: modelData.submap + "  " + modelData.arg; color: root.tk.inkMuted }
    }
  }
}
