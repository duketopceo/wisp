// One setting (U3): label, one help line, the control for its kind and a
// state strip (saving, saved, the daemon's error, or "changed from
// default" with a reset). One layout for every kind: the control sits
// right of the text, or under it when the row is narrow. `def` is a
// lib/settings.js field; the row picks the control from def.kind and
// re-emits its commit(value). reset() commits the schema default.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property var def: ({})
  property string value: ""
  // "", "saving", "saved" or "error" (the host sets it around a write)
  property string saveState: ""
  property string errorText: ""
  signal commit(string value)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1
  readonly property string kind: def && def.kind ? def.kind : ""
  readonly property string key: def && def.key ? def.key : ""
  readonly property string labelText: def && def.label ? service.ui(def.label) : ""
  readonly property string helpText: def && def.help ? service.ui(def.help) : ""
  readonly property bool hasDefault: kind !== "secret" && def !== null
    && def.default !== undefined
  readonly property bool differs: hasDefault && value !== String(def.default)
  readonly property bool stacked: width < M.scale.rowStack
  readonly property int gap: M.scale.space.lg
  readonly property Item control: loader.item
  readonly property real controlWidth: {
    var c = loader.item
    if (!c) return 0
    var want = c.naturalWidth !== undefined ? c.naturalWidth : c.implicitWidth
    return Math.ceil(Math.min(want, stacked ? width : Math.floor(width * 0.55)))
  }
  readonly property string stripText: saveState === "saving" ? service.ui("ui.set.saving")
    : saveState === "error" ? errorText
    : saveState === "saved" ? service.ui("ui.set.saved")
    : differs ? service.ui("ui.set.changed") : ""

  function reset() {
    if (!hasDefault || !differs || saveState === "saving") return
    var d = String(def.default)
    if (control && typeof control.discard === "function") control.discard(d)
    commit(d)
  }

  width: 640
  implicitHeight: Math.max(textCol.y + textCol.height, box.y + box.height)
    + (strip.visible ? M.scale.space.xs + strip.height : 0)
  height: implicitHeight

  Column {
    id: textCol
    width: root.stacked ? root.width : root.width - root.controlWidth - root.gap
    spacing: M.scale.space.xs

    Text {
      textFormat: Text.PlainText
      width: parent.width
      wrapMode: Text.Wrap
      text: root.labelText
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("body", root.ts)
    }
    Text {
      textFormat: Text.PlainText
      visible: text !== ""
      width: parent.width
      wrapMode: Text.Wrap
      text: root.helpText
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("caption", root.ts)
    }
  }

  Item {
    id: box
    x: root.stacked ? 0 : root.width - width
    y: root.stacked ? textCol.height + M.scale.space.sm : 0
    width: root.controlWidth
    height: loader.item ? loader.item.height : 0

    Loader {
      id: loader
      sourceComponent: root.kind === "bool" ? toggleC
        : root.kind === "choice" ? selectC
        : root.kind === "secret" ? secretC
        : (root.kind === "int" || root.kind === "usd" || root.kind === "text") ? inputC
        : null
    }
  }

  Row {
    id: strip
    visible: root.stripText !== "" || resetLink.visible
    y: Math.max(textCol.y + textCol.height, box.y + box.height) + M.scale.space.xs
    width: root.width
    spacing: M.scale.space.md

    Text {
      objectName: "strip"
      textFormat: Text.PlainText
      visible: text !== ""
      width: Math.min(implicitWidth, root.width - (resetLink.visible ? resetLink.width + strip.spacing : 0))
      wrapMode: Text.Wrap
      text: root.stripText
      color: root.saveState === "error" ? root.tk.fail
        : root.saveState === "saved" ? root.tk.ok : root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("caption", root.ts)
    }

    Text {
      id: resetLink
      objectName: "reset"
      textFormat: Text.PlainText
      visible: root.differs && root.saveState !== "saving"
      text: root.service.ui("ui.set.reset")
      color: root.tk.accent
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("caption", root.ts)
      font.underline: resetArea.containsMouse || activeFocus
      activeFocusOnTab: true
      Accessible.role: Accessible.Button
      Accessible.name: text
      Accessible.onPressAction: root.reset()
      Keys.onReturnPressed: root.reset()
      Keys.onEnterPressed: root.reset()
      Keys.onSpacePressed: root.reset()

      MouseArea {
        id: resetArea
        anchors.fill: parent
        anchors.margins: -M.scale.space.xs
        hoverEnabled: true
        onClicked: root.reset()
      }
    }
  }

  Component {
    id: toggleC
    ToggleControl {
      service: root.service
      label: root.labelText
      checked: root.value === "true"
      onCommit: (v) => root.commit(v)
    }
  }
  Component {
    id: selectC
    SelectControl {
      service: root.service
      label: root.labelText
      width: root.controlWidth
      options: root.def.options || []
      value: root.value
      onCommit: (v) => root.commit(v)
    }
  }
  Component {
    id: inputC
    InputControl {
      service: root.service
      key: root.key
      kind: root.kind
      label: root.labelText
      unit: root.def.unit || ""
      maxWidth: root.controlWidth
      value: root.value
      saveState: root.saveState
      onCommit: (v) => root.commit(v)
    }
  }
  Component {
    id: secretC
    Text {
      textFormat: Text.PlainText
      height: M.controlHeight(false)
      verticalAlignment: Text.AlignVCenter
      text: root.service.ui(root.value !== "" ? "ui.set.secret.set" : "ui.set.secret.missing")
      color: root.value !== "" ? root.tk.ok : root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("label", root.ts)
    }
  }
}
