// Settings window body (overhaul U4): a category sidebar and the page for
// the chosen category. Window-free so the snapshot harness can render it;
// shells/settings/shell.qml hosts it in a FloatingWindow. Pages arrive in
// U5; until then each page says where its settings live today.
// Up/Down in the sidebar move the category.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/settings.js" as S

Item {
  id: root

  property var service: null
  property string category: S.CATEGORIES[0]
  signal picked(string category)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1
  readonly property int sidebarWidth: 200
  readonly property int index: Math.max(0, S.CATEGORIES.indexOf(category))

  function select(name) {
    if (S.CATEGORIES.indexOf(name) < 0 || name === category) return
    category = name
    picked(name)
  }

  width: 960
  height: 700

  Rectangle {
    id: sidebar
    width: root.sidebarWidth
    height: parent.height
    color: root.tk.raised

    Rectangle {
      anchors.right: parent.right
      width: M.size.keyline
      height: parent.height
      color: root.tk.keyline
    }

    Column {
      id: list
      objectName: "sidebar"
      x: M.scale.space.sm
      y: M.scale.space.lg
      width: parent.width - 2 * M.scale.space.sm
      spacing: M.scale.space.xs
      activeFocusOnTab: true

      Accessible.role: Accessible.List
      Keys.onUpPressed: root.select(S.CATEGORIES[Math.max(0, root.index - 1)])
      Keys.onDownPressed: root.select(S.CATEGORIES[Math.min(S.CATEGORIES.length - 1, root.index + 1)])

      Repeater {
        model: S.CATEGORIES
        delegate: Rectangle {
          id: item
          required property string modelData
          readonly property bool current: modelData === root.category
          objectName: "cat:" + modelData
          width: list.width
          height: M.controlHeight(false)
          radius: Math.min(M.radius.chrome, M.radius.chip)
          color: current ? root.tk.selection : (area.containsMouse ? root.tk.canvas : root.tk.raised)
          border.width: current && list.activeFocus ? M.scale.focusRing : 0
          border.color: root.tk.accent

          Accessible.role: Accessible.ListItem
          Accessible.name: label.text
          Accessible.selected: current

          Text {
            id: label
            textFormat: Text.PlainText
            anchors.verticalCenter: parent.verticalCenter
            x: M.scale.space.md
            width: parent.width - 2 * M.scale.space.md
            elide: Text.ElideRight
            text: root.service.ui("set.cat." + item.modelData)
            color: item.current ? root.tk.accent : root.tk.ink
            font.family: root.service.fontFamily
            font.pixelSize: M.fontSize("body", root.ts)
          }

          MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            onClicked: { list.forceActiveFocus(); root.select(item.modelData) }
          }
        }
      }
    }
  }

  ScrollPage {
    id: page
    objectName: "page"
    service: root.service
    x: sidebar.width
    width: root.width - sidebar.width
    height: root.height

    SectionHeader {
      service: root.service
      first: true
      width: parent.width
      title: root.service.ui("set.cat." + root.category)
      note: root.service.ui("ui.set.window.pending")
    }
  }
}
