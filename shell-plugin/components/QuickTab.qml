// Panel Quick tab (one-surface U2): a one-row health summary, then every
// schema field marked `quick`, grouped by its schema group, through the
// settings window's rows (SettingRow) and the service's one-at-a-time
// write path. Offline the fields stay enabled (`wispd config set` writes
// config.toml with no daemon) under a one-line note; a failed config read
// shows its error with Retry and locks the fields until a read succeeds.
// Actions leave as signals; the Panel opens the settings window.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/settings.js" as S
import "../lib/health.js" as H

Column {
  id: root

  property var service: null
  signal openSettings()

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1
  readonly property bool loaded: service !== null && service.configLoaded
  readonly property string readError: service ? service.configReadError : ""
  readonly property bool readable: loaded && readError === ""
  readonly property bool offline: service !== null && service.offline
  // health checks that are down right now
  readonly property int down: service ? H.sections(service.health).errors.length : 0
  // the summary: the status table's word while the daemon is offline or
  // stale, else all ok or how many checks are down
  readonly property string summaryText: !service ? ""
    : (offline || service.stale) ? service.wordView.word
    : down === 0 ? service.ui("ui.bar.ok")
    : down + " " + service.ui("ui.bar.down")
  readonly property string summaryTone: !service ? "muted"
    : (offline || service.stale) ? service.wordView.tone
    : down === 0 ? "ok" : "fail"
  readonly property var summaryColor: tk[M.toneToken(summaryTone)]
  // the schema groups that hold quick fields, in schema order
  readonly property var groups: {
    var seen = [], out = []
    for (var i = 0; i < S.FIELDS.length; i++) {
      var f = S.FIELDS[i]
      if (f.quick && seen.indexOf(f.group) < 0) { seen.push(f.group); out.push(f.group) }
    }
    return out
  }

  function valueOf(def) {
    var vals = service ? service.configValues : ({})
    return vals.hasOwnProperty(def.key) ? S.formatValue(def.key, vals[def.key])
      : S.formatValue(def.key, String(def.default))
  }

  // the Panel sets the page width; this default only seeds a first layout
  width: 456
  spacing: M.scale.space.lg

  // health summary: one row, the whole row opens the settings window
  Rectangle {
    id: summary
    objectName: "healthSummary"
    width: parent.width
    implicitHeight: Math.max(M.controlHeight(true), summaryRow.implicitHeight + 2 * M.scale.space.sm)
    height: implicitHeight
    radius: M.radius.chrome
    color: root.tk.raised
    border.width: summaryArea.activeFocus ? M.scale.focusRing : M.size.keyline
    border.color: summaryArea.activeFocus ? root.tk.accent
      : summaryArea.containsMouse ? root.tk.keylineStrong : root.tk.keyline
    Accessible.role: Accessible.Button
    Accessible.name: root.service ? root.service.ui("ui.settings.health") + " " + root.summaryText : ""

    Row {
      id: summaryRow
      x: M.scale.space.md
      anchors.verticalCenter: parent.verticalCenter
      spacing: M.scale.space.sm
      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: M.scale.space.sm
        height: width
        radius: width / 2
        color: root.summaryColor
      }
      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: root.service ? root.service.ui("ui.settings.health") : ""
        color: root.tk.ink
        font.family: root.service ? root.service.fontFamily : ""
        font.pixelSize: M.fontSize("body", root.ts)
        font.weight: Font.DemiBold
      }
      Text {
        textFormat: Text.PlainText
        objectName: "healthWord"
        anchors.verticalCenter: parent.verticalCenter
        text: root.summaryText
        color: root.summaryColor
        font.family: root.service ? root.service.fontFamily : ""
        font.pixelSize: M.fontSize("body", root.ts)
      }
    }

    MouseArea {
      id: summaryArea
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      activeFocusOnTab: true
      onClicked: root.openSettings()
      Keys.onReturnPressed: root.openSettings()
      Keys.onSpacePressed: root.openSettings()
    }
  }

  component Note: Text {
    textFormat: Text.PlainText
    width: root.width
    wrapMode: Text.Wrap
    color: root.tk.inkMuted
    font.family: root.service ? root.service.fontFamily : ""
    font.pixelSize: M.fontSize("caption", root.ts)
  }

  Note {
    objectName: "loadingLine"
    visible: !root.loaded
    text: root.service ? root.service.ui("ui.set.loading") : ""
  }

  Note {
    objectName: "offlineNote"
    visible: root.offline && root.readable
    text: root.service ? root.service.ui("ui.set.offline") : ""
  }

  Row {
    objectName: "readError"
    visible: root.loaded && root.readError !== ""
    width: root.width
    spacing: M.scale.space.md
    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - retry.width - parent.spacing
      wrapMode: Text.Wrap
      text: root.service ? root.service.ui("ui.set.unreadable") + ": " + root.readError : ""
      color: root.tk.fail
      font.family: root.service ? root.service.fontFamily : ""
      font.pixelSize: M.fontSize("caption", root.ts)
    }
    Chip {
      id: retry
      objectName: "retry"
      anchors.verticalCenter: parent.verticalCenter
      service: root.service
      label: root.service ? root.service.ui("ui.set.retry") : ""
      onClicked: root.service.loadConfig()
    }
  }

  Repeater {
    // rows are built only while the tab shows (hidden tabs add no height)
    model: root.readable && root.visible ? root.groups : []
    delegate: Column {
      id: grp
      required property var modelData
      required property int index
      width: root.width
      spacing: M.scale.space.md

      SectionHeader {
        service: root.service
        width: parent.width
        first: grp.index === 0
        title: root.service ? root.service.ui("ui.settings." + grp.modelData) : ""
      }

      Repeater {
        model: S.group(grp.modelData)
        delegate: SettingRow {
          required property var modelData
          objectName: "row:" + modelData.key
          service: root.service
          def: modelData
          width: grp.width
          value: root.valueOf(modelData)
          saveState: root.service.configState.hasOwnProperty(modelData.key)
            ? root.service.configState[modelData.key] : ""
          errorText: root.service.configErrors.hasOwnProperty(modelData.key)
            ? root.service.configErrors[modelData.key] : ""
          onCommit: (v) => root.service.configSet(modelData.key, S.formatValue(modelData.key, v))
        }
      }
    }
  }
}
