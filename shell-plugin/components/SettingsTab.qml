// Panel Settings tab: the Health section, then the editor for the keys in
// lib/settings.js. Edits are validated here (inline error under the field)
// and leave as save(key, value); the Panel sends them to the service, which
// runs `wispd config set`. A daemon rejection comes back through `errors`.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/settings.js" as S

Column {
  id: root

  property var service: null
  property var cua: null
  property var spendModels: []
  // current values by key ("budget.daily_usd": "2.00")
  property var values: ({})
  // daemon errors by key, and the key last saved without error
  property var errors: ({})
  property string savedKey: ""
  // edits in progress by key
  property var draft: ({})
  property var connectors: []
  property bool showAdvanced: false
  signal save(string key, string value)
  signal connectClicked(string alias)

  readonly property var tk: service ? service.tokens : ({})

  width: 340
  spacing: M.spacing.xl

  function current(key) {
    return draft.hasOwnProperty(key) ? draft[key] : (values.hasOwnProperty(key) ? values[key] : "")
  }
  function setDraft(key, v) {
    var d = {}
    for (var k in draft) d[k] = draft[k]
    d[key] = v
    draft = d
  }
  function problem(key) {
    if (draft.hasOwnProperty(key)) {
      var bad = S.validate(key, draft[key])
      if (bad !== "") return service.ui(bad)
    }
    return errors.hasOwnProperty(key) ? errors[key] : ""
  }
  function dirty(key) {
    return draft.hasOwnProperty(key) && draft[key] !== (values.hasOwnProperty(key) ? values[key] : "")
  }

  HealthSection {
    service: root.service
    cua: root.cua
    spendModels: root.spendModels
    width: parent.width
  }

  component Group: Text {
    textFormat: Text.PlainText
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
    font.weight: Font.DemiBold
  }

  component Field: Column {
    id: f
    property var def: ({})
    property string key: def.key
    spacing: M.spacing.sm
    width: root.width

    Text {
      textFormat: Text.PlainText
      text: root.service.ui(f.def.label)
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }

    // text fields
    Row {
      visible: f.def.kind === "usd" || f.def.kind === "int"
      spacing: M.spacing.lg
      Rectangle {
        width: 120
        height: M.size.control
        radius: Math.min(M.radius.chrome, M.radius.chip)
        color: root.tk.raised
        border.width: M.size.keyline
        border.color: input.activeFocus ? root.tk.accent : root.tk.keyline
        TextInput {
          id: input
          anchors.fill: parent
          anchors.margins: M.spacing.lg
          verticalAlignment: TextInput.AlignVCenter
          text: root.current(f.key)
          color: root.tk.ink
          selectionColor: root.tk.selection
          font.family: root.service.fontFamily
          font.pixelSize: M.font.body
          clip: true
          onTextEdited: root.setDraft(f.key, text)
          onAccepted: if (saveChip.enabled) saveChip.clicked()
        }
      }
      Chip {
        id: saveChip
        objectName: "save:" + f.key
        service: root.service
        label: root.service.ui("ui.set.save")
        enabled: root.dirty(f.key) && S.validate(f.key, root.current(f.key)) === ""
        onClicked: root.save(f.key, root.current(f.key))
      }
    }

    // bool and choice fields
    Flow {
      visible: f.def.kind === "bool" || f.def.kind === "choice"
      width: parent.width
      spacing: M.spacing.lg
      Repeater {
        model: f.def.kind === "bool" ? ["true", "false"] : (f.def.options || [])
        delegate: Chip {
          service: root.service
          objectName: "opt:" + f.key + ":" + modelData
          label: f.def.kind === "bool"
            ? (modelData === "true" ? root.service.ui("ui.set.on") : root.service.ui("ui.set.off"))
            : String(modelData).replace(/_/g, " ")
          selected: root.current(f.key) === modelData
          onClicked: root.save(f.key, modelData)
        }
      }
    }

    Text {
      textFormat: Text.PlainText
      visible: text !== ""
      width: parent.width
      text: root.problem(f.key)
      wrapMode: Text.Wrap
      color: root.tk.fail
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
    Text {
      textFormat: Text.PlainText
      visible: root.savedKey === f.key && root.problem(f.key) === ""
      text: root.service.ui("ui.set.saved")
      color: root.tk.ok
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
  }

  Rectangle {
    width: parent.width
    implicitHeight: voiceCol.implicitHeight + 2 * M.spacing.lg
    radius: M.radius.chrome
    color: root.tk.surface
    border.width: M.size.keyline
    border.color: root.tk.keyline
    Column {
      id: voiceCol
      x: M.spacing.lg
      y: M.spacing.lg
      width: parent.width - 2 * M.spacing.lg
      spacing: M.spacing.md
      Group { text: root.service.ui("ui.settings.voice") }
      Repeater {
        model: S.group("voice")
        delegate: Field { def: modelData; width: voiceCol.width }
      }
    }
  }

  Rectangle {
    width: parent.width
    implicitHeight: dictCol.implicitHeight + 2 * M.spacing.lg
    radius: M.radius.chrome
    color: root.tk.surface
    border.width: M.size.keyline
    border.color: root.tk.keyline
    Column {
      id: dictCol
      x: M.spacing.lg
      y: M.spacing.lg
      width: parent.width - 2 * M.spacing.lg
      spacing: M.spacing.md
      Group { text: root.service.ui("ui.settings.dictation") }
      Repeater {
        model: S.group("dictation")
        delegate: Field { def: modelData; width: dictCol.width }
      }
    }
  }

  Rectangle {
    width: parent.width
    implicitHeight: ptrCol.implicitHeight + 2 * M.spacing.lg
    radius: M.radius.chrome
    color: root.tk.surface
    border.width: M.size.keyline
    border.color: root.tk.keyline
    Column {
      id: ptrCol
      x: M.spacing.lg
      y: M.spacing.lg
      width: parent.width - 2 * M.spacing.lg
      spacing: M.spacing.md
      Group { text: root.service.ui("ui.settings.pointer") }
      Repeater {
        model: S.group("pointer")
        delegate: Field { def: modelData; width: ptrCol.width }
      }
      Group { text: root.service.ui("ui.settings.agent") }
      Repeater {
        model: S.group("agent")
        delegate: Field { def: modelData; width: ptrCol.width }
      }
    }
  }

  Rectangle {
    width: parent.width
    implicitHeight: cuaCol.implicitHeight + 2 * M.spacing.lg
    radius: M.radius.chrome
    color: root.tk.surface
    border.width: M.size.keyline
    border.color: root.tk.keyline
    Column {
      id: cuaCol
      x: M.spacing.lg
      y: M.spacing.lg
      width: parent.width - 2 * M.spacing.lg
      spacing: M.spacing.md
      Row {
        width: parent.width
        spacing: M.spacing.lg
        Group {
          text: root.service.ui("ui.settings.cua")
          anchors.verticalCenter: parent.verticalCenter
        }
        Chip {
          objectName: "toggle:advanced"
          service: root.service
          label: root.showAdvanced
            ? root.service.ui("ui.set.advanced.hide")
            : root.service.ui("ui.set.advanced.show")
          onClicked: root.showAdvanced = !root.showAdvanced
        }
      }
      Repeater {
        model: root.showAdvanced ? S.group("cua") : []
        delegate: Field { def: modelData; width: cuaCol.width }
      }
    }
  }

  Rectangle {
    width: parent.width
    implicitHeight: budgetCol.implicitHeight + 2 * M.spacing.lg
    radius: M.radius.chrome
    color: root.tk.surface
    border.width: M.size.keyline
    border.color: root.tk.keyline
    Column {
      id: budgetCol
      x: M.spacing.lg
      y: M.spacing.lg
      width: parent.width - 2 * M.spacing.lg
      spacing: M.spacing.md
      Group { text: root.service.ui("ui.settings.budget") }
      Repeater {
        model: S.group("budget")
        delegate: Field { def: modelData; width: budgetCol.width }
      }
      Text {
        textFormat: Text.PlainText
        text: root.service.ui("ui.set.blank")
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.caption
      }
    }
  }

  Rectangle {
    width: parent.width
    implicitHeight: connCol.implicitHeight + 2 * M.spacing.lg
    radius: M.radius.chrome
    color: root.tk.surface
    border.width: M.size.keyline
    border.color: root.tk.keyline
    Column {
      id: connCol
      x: M.spacing.lg
      y: M.spacing.lg
      width: parent.width - 2 * M.spacing.lg
      spacing: M.spacing.sm
      Group { text: root.service.ui("ui.settings.connect") }
      Text {
        textFormat: Text.PlainText
        visible: root.connectors.length === 0
        text: root.service.ui("ui.settings.connect.none")
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.label
        width: parent.width
        wrapMode: Text.Wrap
      }
      Repeater {
        model: root.connectors
        delegate: Row {
          spacing: M.spacing.lg
          Rectangle {
            width: M.spacing.lg
            height: M.spacing.lg
            radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            color: modelData.connected ? root.tk.ok : root.tk.inkMuted
          }
          Text {
            textFormat: Text.PlainText
            width: 180
            text: modelData.name
            elide: Text.ElideRight
            anchors.verticalCenter: parent.verticalCenter
            color: root.tk.ink
            font.family: root.service.fontFamily
            font.pixelSize: M.font.label
          }
          Chip {
            visible: !modelData.connected
            service: root.service
            label: root.service.ui("ui.settings.connect.go")
            onClicked: root.connectClicked(modelData.alias)
          }
        }
      }
    }
  }
}
