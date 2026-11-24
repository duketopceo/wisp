// Settings window body: a search field and the sidebar, and the page for
// the chosen entry: a config category (SettingsPage), a management or
// Status page (ManagePage, one-surface U3), or the search. The sidebar
// runs Home, Activity, Memory, Tasks; the config categories; then the
// Status group (lib/settings.js SIDEBAR). Window-free so the snapshot
// harness can render it; shells/settings/shell.qml hosts it in a
// FloatingWindow and binds the data properties below to WispService and
// its file reads. Up/Down in the sidebar move the entry and focus lands on
// a management page's heading; a search replaces the page and dims the
// sidebar; Ctrl+F focuses the search, Esc clears it and the chosen entry
// is back.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/settings.js" as S

Item {
  id: root

  property var service: null
  property string category: S.SIDEBAR[0]
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
  // management and Status pages (see ManagePage)
  property bool heard: false
  property string pageError: ""
  property var turns: []
  property var suggestions: []
  property var corrections: []
  property string memoryText: ""
  property string userText: ""
  property string auditText: ""
  property var binds: null
  property var cua: null
  property var spendModels: []
  signal picked(string category)
  signal commit(string key, string value)
  signal retry()
  signal retryConnectors()
  signal connectAlias(string alias)
  signal retryPage()
  signal talk()
  signal restart()
  signal stop()
  signal answer(string pick)
  signal saveMemory(string which, string text)
  signal startTask(string text)
  signal cancelTask(string name)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1
  readonly property int sidebarWidth: 200
  readonly property int index: Math.max(0, S.SIDEBAR.indexOf(category))
  readonly property bool searching: S.trim(query) !== ""
  readonly property bool onPage: S.isPage(category) && !searching

  // choosing an entry leaves the search; a page change moves keyboard
  // focus to a management page's heading unless the sidebar holds it
  function select(name) {
    if (S.SIDEBAR.indexOf(name) < 0) return
    clearSearch()
    if (name === category) return
    category = name
    picked(name)
    if (S.isPage(name) && !list.activeFocus) managePage.focusHeading()
  }
  function focusSearch() { searchBox.focusField() }
  function clearSearch() {
    query = ""
    searchBox.text = ""
  }

  onQueryChanged: if (searchBox.text !== query) searchBox.text = query
  // keep the chosen entry in the sidebar's view (the row of its delegate)
  onCategoryChanged: Qt.callLater(function () {
    var e = entries.itemAt(S.SIDEBAR.indexOf(category))
    if (e) sideScroll.reveal(e.row)
  })

  Shortcut {
    sequences: [StandardKey.Find]
    onActivated: root.focusSearch()
  }
  // Esc outside any text field; inside one the field handles it (the
  // search field clears itself, a row's field reverts its draft)
  readonly property Item focusItem: Window.activeFocusItem
  Shortcut {
    sequence: "Esc"
    enabled: root.searching && !(root.focusItem && ("cursorPosition" in root.focusItem))
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

    // the sidebar scrolls when the window is shorter than its entries
    // (the 520 px minimum) and keeps the current entry in view
    Flickable {
      id: sideScroll
      objectName: "sidebarScroll"
      x: M.scale.space.sm
      y: searchBox.y + searchBox.height + M.scale.space.md
      width: parent.width - 2 * M.scale.space.sm
      height: parent.height - y
      contentWidth: width
      contentHeight: list.implicitHeight + M.scale.space.md
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      flickableDirection: Flickable.VerticalFlick

      function reveal(item) {
        if (!item) return
        var top = item.mapToItem(list, 0, 0).y
        var bottom = top + item.height
        if (top < contentY) contentY = top
        else if (bottom > contentY + height) contentY = Math.min(contentHeight - height, bottom - height)
      }

      Column {
        id: list
        objectName: "sidebar"
        opacity: root.searching ? 0.4 : 1
        width: sideScroll.width
        spacing: M.scale.space.xs
        activeFocusOnTab: true

        Accessible.role: Accessible.List
        Keys.onUpPressed: root.select(S.SIDEBAR[Math.max(0, root.index - 1)])
        Keys.onDownPressed: root.select(S.SIDEBAR[Math.min(S.SIDEBAR.length - 1, root.index + 1)])
        Keys.onTabPressed: (event) => {
          if (root.onPage) { managePage.focusHeading(); event.accepted = true }
          else event.accepted = false
        }

        Repeater {
          id: entries
          model: S.SIDEBAR
          delegate: Column {
            id: entry
            property alias row: item
            required property string modelData
            // a group caption above the first config category and the
            // first Status page
            readonly property string group: modelData === S.CATEGORIES[0] ? "settings"
              : modelData === S.STATUS_PAGES[0] ? "status" : ""
            width: list.width

            Text {
              objectName: "group:" + entry.group
              visible: entry.group !== ""
              textFormat: Text.PlainText
              x: M.scale.space.md
              topPadding: M.scale.space.md
              bottomPadding: M.scale.space.xs
              text: entry.group !== "" ? root.service.ui("set.group." + entry.group) : ""
              color: root.tk.inkMuted
              font.family: root.service.fontFamily
              font.pixelSize: M.fontSize("caption", root.ts)
            }

            Rectangle {
              id: item
              readonly property bool current: entry.modelData === root.category
              objectName: "cat:" + entry.modelData
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
                text: root.service.ui("set.cat." + entry.modelData)
                color: item.current ? root.tk.accent : root.tk.ink
                font.family: root.service.fontFamily
                font.pixelSize: M.fontSize("body", root.ts)
              }

              MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                onClicked: { list.forceActiveFocus(); root.select(entry.modelData) }
              }
            }
          }
        }
      }
    }
  }

  SettingsPage {
    id: page
    objectName: "page"
    visible: !root.onPage
    service: root.service
    x: sidebar.width
    width: root.width - sidebar.width
    height: root.height
    category: S.isPage(root.category) ? S.CATEGORIES[0] : root.category
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

  ManagePage {
    id: managePage
    objectName: "managePage"
    visible: root.onPage
    service: root.service
    x: sidebar.width
    width: root.width - sidebar.width
    height: root.height
    page: S.isPage(root.category) ? root.category : "home"
    heard: root.heard
    error: root.pageError
    turns: root.turns
    suggestions: root.suggestions
    corrections: root.corrections
    memoryText: root.memoryText
    userText: root.userText
    auditText: root.auditText
    binds: root.binds
    cua: root.cua
    spendModels: root.spendModels
    onRetry: root.retryPage()
    onTalk: root.talk()
    onRestart: root.restart()
    onStop: root.stop()
    onAnswer: (pick) => root.answer(pick)
    onSaveMemory: (which, text) => root.saveMemory(which, text)
    onStartTask: (text) => root.startTask(text)
    onCancelTask: (name) => root.cancelTask(name)
  }
}
