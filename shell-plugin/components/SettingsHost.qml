// Settings window body (overhaul U4, U5): a search field and category
// sidebar, and the page for the chosen category (SettingsPage) or for the
// search. Window-free so the snapshot harness can render it;
// shells/settings/shell.qml hosts it in a FloatingWindow and binds the
// data properties below to WispService. Up/Down in the sidebar move the
// category; a search replaces the page and dims the sidebar; Ctrl+F
// focuses the search, Esc clears it and the chosen category is back.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/settings.js" as S

Item {
  id: root

  property var service: null
  property string category: S.CATEGORIES[0]
  property string query: ""
  // data for the page, set by the shell (see SettingsPage)
  property var values: ({})
  property var saveStates: ({})
  property var errors: ({})
  property bool loaded: false
  property string readError: ""
  property bool offline: false
  property var connectors: []
  property string connectorState: "loading"
  property string connectorError: ""
  property string connectorRunning: ""
  property var connectorErrors: ({})
  signal picked(string category)
  signal commit(string key, string value)
  signal retry()
  signal retryConnectors()
  signal connectAlias(string alias)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1
  readonly property int sidebarWidth: 200
  readonly property int index: Math.max(0, S.CATEGORIES.indexOf(category))
  readonly property bool searching: S.trim(query) !== ""

  // choosing a category leaves the search
  function select(name) {
    if (S.CATEGORIES.indexOf(name) < 0) return
    clearSearch()
    if (name === category) return
    category = name
    picked(name)
  }
  function focusSearch() { searchBox.focusField() }
  function clearSearch() {
    query = ""
    searchBox.text = ""
  }

  onQueryChanged: if (searchBox.text !== query) searchBox.text = query

  Shortcut {
    sequences: [StandardKey.Find]
    onActivated: root.focusSearch()
  }
  // Esc outside the field; inside it the field clears itself
  Shortcut {
    sequence: "Esc"
    enabled: root.searching && !searchBox.focused
    onActivated: root.clearSearch()
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

    SearchControl {
      id: searchBox
      objectName: "searchBox"
      service: root.service
      x: M.scale.space.sm
      y: M.scale.space.lg
      width: parent.width - 2 * M.scale.space.sm
      onSearch: (text) => root.query = text
    }

    Column {
      id: list
      objectName: "sidebar"
      x: M.scale.space.sm
      y: searchBox.y + searchBox.height + M.scale.space.md
      opacity: root.searching ? 0.4 : 1
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

  SettingsPage {
    id: page
    objectName: "page"
    service: root.service
    x: sidebar.width
    width: root.width - sidebar.width
    height: root.height
    category: root.category
    query: root.query
    values: root.values
    saveStates: root.saveStates
    errors: root.errors
    loaded: root.loaded
    readError: root.readError
    offline: root.offline
    connectors: root.connectors
    connectorState: root.connectorState
    connectorError: root.connectorError
    connectorRunning: root.connectorRunning
    connectorErrors: root.connectorErrors
    onCommit: (key, value) => root.commit(key, value)
    onPickCategory: (name) => root.select(name)
    onRetry: root.retry()
    onRetryConnectors: root.retryConnectors()
    onConnectAlias: (alias) => root.connectAlias(alias)
  }
}
