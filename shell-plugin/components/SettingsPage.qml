// One page of the settings window: the rows of one category, or the
// rows matching a search with a category chip on each. Rows come from the
// schema (lib/settings.js); values, write states and daemon errors arrive
// by key from the host, and an edit leaves as commit(key, value) in schema
// format. Loading, offline and could-not-read states show above the rows;
// the Connectors page adds the connector list under its two browser rows.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/settings.js" as S

ScrollPage {
  id: root

  property string category: S.CATEGORIES[0]
  // the search text; any word replaces the page with matching rows
  property string query: ""
  // "section.key" -> value as the daemon reports it
  property var values: ({})
  // key -> "queued" | "saving" | "saved" | "error", and key -> daemon message
  property var saveStates: ({})
  property var errors: ({})
  // the config read finished (any exit); readError is its first stderr line
  property bool loaded: false
  property string readError: ""
  // `wispd status` said the daemon is down; pages still edit the file
  property bool offline: false
  // Connectors page: [{alias, name, connected}], and the list read state
  // ("loading", "ready" or "failed")
  property var connectors: []
  property string connectorState: "loading"
  property string connectorError: ""
  property string connectorRunning: ""
  property var connectorErrors: ({})
  signal commit(string key, string value)
  signal pickCategory(string name)
  signal retry()
  signal retryConnectors()
  signal connectAlias(string alias)

  // the theme tokens (ScrollPage.tk), under a local name for the inline components
  readonly property var colors: tk
  readonly property real ts: service ? service.textScale : 1
  readonly property bool searching: S.trim(query) !== ""
  readonly property bool readable: loaded && readError === ""
  readonly property var rows: searching ? S.search(query)
    : S.categoryFields(category).map(function (f) { return { key: f.key, category: f.category, def: f } })
  readonly property bool showConnectors: category === "connectors" && !searching

  function valueOf(def) {
    if (def.kind === "secret") return values.hasOwnProperty(def.key) ? "set" : ""
    return values.hasOwnProperty(def.key) ? S.formatValue(def.key, values[def.key])
      : S.formatValue(def.key, String(def.default))
  }

  component Note: Text {
    textFormat: Text.PlainText
    width: parent ? parent.width : 0
    wrapMode: Text.Wrap
    color: root.colors.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("body", root.ts)
  }

  // a sentence with a Retry action on the right
  component Banner: Rectangle {
    id: banner
    property string text: ""
    signal retry()
    width: parent ? parent.width : 0
    height: Math.max(msg.height, btn.height) + 2 * M.scale.space.md
    radius: Math.min(M.radius.chrome, M.radius.chip)
    color: root.colors.raised
    border.width: M.size.keyline
    border.color: root.colors.keylineStrong

    Text {
      id: msg
      textFormat: Text.PlainText
      x: M.scale.space.md
      anchors.verticalCenter: parent.verticalCenter
      width: banner.width - btn.width - 3 * M.scale.space.md
      wrapMode: Text.Wrap
      text: banner.text
      color: root.colors.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("body", root.ts)
    }
    Chip {
      id: btn
      objectName: "retry"
      service: root.service
      anchors.right: parent.right
      anchors.rightMargin: M.scale.space.md
      anchors.verticalCenter: parent.verticalCenter
      label: root.service.ui("ui.set.retry")
      onClicked: banner.retry()
    }
  }

  SectionHeader {
    service: root.service
    first: true
    width: parent.width
    title: root.searching ? root.service.ui("ui.set.search.title")
      : root.service.ui("set.cat." + root.category)
    note: !root.searching && root.category === "models" ? root.service.ui("ui.set.models.note") : ""
  }

  Banner {
    objectName: "offlineBanner"
    visible: root.offline && root.readError === ""
    text: root.service.ui("ui.set.offline")
    onRetry: root.retry()
  }
  Banner {
    objectName: "unreadableBanner"
    visible: root.readError !== ""
    text: root.service.ui("ui.set.unreadable") + (root.readError !== "" ? ": " + root.readError : "")
    onRetry: root.retry()
  }
  Note {
    objectName: "loading"
    visible: !root.loaded
    text: root.service.ui("ui.set.loading")
  }
  Note {
    objectName: "empty"
    visible: root.readable && root.rows.length === 0 && !root.showConnectors
    text: root.searching ? root.service.ui("ui.set.search.empty") : root.service.ui("ui.set.empty")
  }

  Repeater {
    model: root.readable ? root.rows : []
    delegate: Column {
      id: item
      required property var modelData
      width: parent ? parent.width : 0
      spacing: M.scale.space.xs

      Chip {
        objectName: "chip:" + item.modelData.key
        visible: root.searching
        service: root.service
        label: root.service.ui("set.cat." + item.modelData.category)
        onClicked: root.pickCategory(item.modelData.category)
      }
      SettingRow {
        objectName: "row:" + item.modelData.key
        service: root.service
        def: item.modelData.def
        width: parent.width
        value: root.valueOf(item.modelData.def)
        saveState: root.saveStates.hasOwnProperty(item.modelData.key) ? root.saveStates[item.modelData.key] : ""
        errorText: root.errors.hasOwnProperty(item.modelData.key) ? root.errors[item.modelData.key] : ""
        onCommit: (v) => root.commit(item.modelData.key, S.formatValue(item.modelData.key, v))
      }
    }
  }

  SectionHeader {
    visible: root.showConnectors
    service: root.service
    width: parent.width
    title: root.service.ui("ui.set.conn.title")
  }
  Note {
    objectName: "connectorsLoading"
    visible: root.showConnectors && root.connectorState === "loading"
    text: root.service.ui("ui.set.conn.loading")
  }
  Banner {
    objectName: "connectorsFailed"
    visible: root.showConnectors && root.connectorState === "failed"
    text: root.service.ui("ui.set.conn.failed") + (root.connectorError !== "" ? ": " + root.connectorError : "")
    onRetry: root.retryConnectors()
  }
  Note {
    objectName: "connectorsEmpty"
    visible: root.showConnectors && root.connectorState === "ready" && root.connectors.length === 0
    text: root.service.ui("ui.set.conn.empty")
  }
  Repeater {
    model: root.showConnectors && root.connectorState === "ready" ? root.connectors : []
    delegate: Column {
      id: conn
      required property var modelData
      readonly property bool running: root.connectorRunning === modelData.alias
      readonly property string problem: root.connectorErrors.hasOwnProperty(modelData.alias)
        ? root.connectorErrors[modelData.alias] : ""
      objectName: "connector:" + modelData.alias
      width: parent ? parent.width : 0
      spacing: M.scale.space.xs

      Item {
        width: parent.width
        height: Math.max(M.size.control, nameText.height)

        Rectangle {
          id: dot
          width: M.scale.space.md
          height: width
          radius: width / 2
          anchors.verticalCenter: parent.verticalCenter
          color: conn.modelData.connected ? root.colors.ok : root.colors.inkMuted
        }
        Column {
          id: nameCol
          x: dot.width + M.scale.space.md
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width - dot.width - btn.width - 3 * M.scale.space.md

          Text {
            id: nameText
            objectName: "name"
            textFormat: Text.PlainText
            width: parent.width
            elide: Text.ElideRight
            text: conn.modelData.name
            color: root.colors.ink
            font.family: root.service.fontFamily
            font.pixelSize: M.fontSize("body", root.ts)
          }
          Text {
            objectName: "status"
            textFormat: Text.PlainText
            width: parent.width
            elide: Text.ElideRight
            text: root.service.ui(conn.modelData.connected ? "ui.set.conn.on" : "ui.set.conn.off")
            color: root.colors.inkMuted
            font.family: root.service.fontFamily
            font.pixelSize: M.fontSize("caption", root.ts)
          }
        }
        Chip {
          id: btn
          objectName: "connect:" + conn.modelData.alias
          service: root.service
          visible: !conn.modelData.connected
          width: visible ? implicitWidth : 0
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          enabled: root.connectorRunning === ""
          label: root.service.ui(conn.running ? "ui.set.conn.running" : "ui.set.conn.go")
          onClicked: root.connectAlias(conn.modelData.alias)
        }
      }
      Text {
        objectName: "problem"
        textFormat: Text.PlainText
        visible: conn.problem !== ""
        width: parent.width
        wrapMode: Text.Wrap
        text: conn.problem
        color: root.colors.fail
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("caption", root.ts)
      }
    }
  }
}
