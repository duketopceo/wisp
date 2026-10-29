// Panel Dev tab (local only, behind `[dev] panel`): the v1 gate card, the
// recent turns with a stacked per-stage bar, the selected turn's stage
// breakdown and the top misses. A pure renderer: the Panel hands in the
// parsed `wispd dev turns --json` data (service.devData), the loading flag
// and the error code, and the refresh button leaves through `refresh`
// (the Panel calls service.loadDev). Rows select on click; the newest turn
// is selected until one is picked. No timers, no files, no processes.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/dev.js" as D

Column {
  id: root

  property var service: null
  // the reply's data: {turns, gate, rated, finished, rated_share, misses}
  property var reply: null
  property bool loading: false
  // "" when fine, else a short code (the words come from the copy table)
  property string error: ""
  // the picked turn id; "" selects the newest
  property string selectedId: ""
  signal refresh()

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: service ? service.motionMode : "off"
  readonly property bool hasData: !D.isEmpty(root.reply)
  readonly property var turns: hasData ? root.reply.turns : []
  readonly property var gate: D.gateView(root.reply ? root.reply.gate : null)
  readonly property var names: D.stageNames(root.turns)
  readonly property var pick: D.selected(root.turns, root.selectedId)
  readonly property int barW: 150
  readonly property int rowH: 34

  function tone(token) { return root.tk[token] }
  function ui(k) { return root.service.ui(k) }

  width: 340
  spacing: M.spacing.xl

  // header: the card title and the refresh button, always present
  Item {
    width: parent.width
    height: M.size.control

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.hasData
      text: root.ui("ui.dev.gate")
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.body
      font.weight: Font.DemiBold
    }

    Text {
      id: refreshLabel
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: root.ui("ui.dev.refresh")
      color: refreshArea.containsMouse ? root.tk.ink : root.tk.accent
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
      font.underline: refreshArea.containsMouse
      Accessible.role: Accessible.Button
      Accessible.name: text
      MouseArea {
        id: refreshArea
        anchors.fill: parent
        anchors.margins: -M.spacing.lg
        hoverEnabled: true
        onClicked: root.refresh()
      }
    }
  }

  // loading, error and empty states stand in for the body
  Text {
    visible: root.loading && !root.hasData
    width: parent.width
    text: root.ui("ui.dev.loading")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
  }

  Column {
    visible: !root.loading && root.error !== "" && !root.hasData
    width: parent.width
    spacing: M.spacing.md
    Text {
      width: parent.width
      text: root.ui("ui.dev.error")
      wrapMode: Text.Wrap
      color: root.tk.fail
      font.family: root.service.fontFamily
      font.pixelSize: M.font.body
    }
    Text {
      width: parent.width
      text: root.ui("ui.dev.error.hint")
      wrapMode: Text.Wrap
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }
  }

  Column {
    visible: !root.loading && root.error === "" && !root.hasData
    width: parent.width
    spacing: M.spacing.md
    Text {
      width: parent.width
      text: root.ui("ui.dev.empty")
      wrapMode: Text.Wrap
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.body
    }
    Text {
      width: parent.width
      text: root.ui("ui.dev.empty.hint")
      wrapMode: Text.Wrap
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }
  }

  // an error while older data is still showing
  Text {
    visible: root.error !== "" && root.hasData
    width: parent.width
    text: root.ui("ui.dev.error")
    color: root.tk.fail
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }

  // 1. gate card
  Rectangle {
    visible: root.hasData
    width: parent.width
    height: gateCol.implicitHeight + 2 * M.spacing.xxl
    radius: M.radius.chrome
    color: root.tk.raised
    border.width: M.size.keyline
    border.color: root.tk.keyline

    Column {
      id: gateCol
      x: M.spacing.xxl
      y: M.spacing.xxl
      width: parent.width - 2 * M.spacing.xxl
      spacing: M.spacing.md

      Item {
        width: parent.width
        height: rateText.implicitHeight
        Text {
          id: rateText
          text: root.gate.rateText
          color: root.tone(D.toneToken(root.gate.tone))
          font.family: root.service.fontFamily
          font.pixelSize: M.font.title
          font.weight: Font.DemiBold
        }
        Text {
          x: rateText.width + M.spacing.md
          anchors.baseline: rateText.baseline
          visible: root.gate.tick >= 0
          text: root.ui("ui.dev.of") + " " + root.gate.gateText
          color: root.tk.inkMuted
          font.family: root.service.fontFamily
          font.pixelSize: M.font.body
        }
      }

      // progress bar with a tick at the gate
      Item {
        width: parent.width
        height: 6
        Rectangle {
          anchors.fill: parent
          radius: 3
          color: root.tk.keyline
        }
        Rectangle {
          width: Math.round(parent.width * root.gate.fill)
          height: parent.height
          radius: 3
          color: root.tone(D.toneToken(root.gate.tone))
          Behavior on width {
            enabled: root.motionMode !== "off"
            NumberAnimation { duration: 140 }
          }
        }
        Rectangle {
          visible: root.gate.tick >= 0
          x: Math.round(parent.width * root.gate.tick) - 1
          y: -2
          width: 2
          height: parent.height + 4
          color: root.tk.needsYou
        }
      }

      Text {
        text: root.gate.labelled + " / " + root.gate.minTurns + " " + root.ui("ui.dev.labelled")
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.label
      }
      Text {
        visible: root.reply && typeof root.reply.rated_share === "number"
        text: root.ui("ui.dev.rated") + " " + D.pct(root.reply ? root.reply.rated_share : null)
          + " " + root.ui("ui.dev.of_turns")
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.label
      }
      Text {
        readonly property string line: D.kindLine(root.reply && root.reply.gate ? root.reply.gate.kinds : null)
        visible: line !== ""
        width: parent.width
        text: line
        elide: Text.ElideRight
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.label
      }
    }
  }

  // 2. recent turns
  Column {
    visible: root.hasData
    width: parent.width
    spacing: M.spacing.sm

    Text {
      text: root.ui("ui.dev.recent")
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.body
      font.weight: Font.DemiBold
    }

    Repeater {
      model: root.turns
      delegate: Rectangle {
        id: row
        required property var modelData
        readonly property bool on: root.pick !== null && root.pick.id === modelData.id
        readonly property var shares: D.stageShares(modelData.stages, modelData.total_ms)
        readonly property var widths: D.barWidths(shares, root.barW)
        width: root.width
        height: root.rowH
        radius: M.radius.chip
        color: on ? root.tk.selection : "transparent"
        Behavior on color {
          enabled: root.motionMode !== "off"
          ColorAnimation { duration: 90 }
        }

        Column {
          x: M.spacing.lg
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width - root.barW - 2 * M.spacing.lg - M.size.control
          spacing: 1
          Text {
            width: parent.width
            text: row.modelData.transcript
            elide: Text.ElideRight
            color: root.tk.ink
            font.family: root.service.fontFamily
            font.pixelSize: M.font.label
          }
          Text {
            width: parent.width
            text: D.routeLine(row.modelData, { step: root.ui("ui.dev.step"), steps: root.ui("ui.dev.steps") })
            elide: Text.ElideRight
            color: root.tk.inkMuted
            font.family: root.service.fontFamily
            font.pixelSize: M.font.caption
          }
        }

        // stacked stage bar
        Row {
          x: parent.width - root.barW - M.size.control - M.spacing.lg
          anchors.verticalCenter: parent.verticalCenter
          height: 8
          Repeater {
            model: row.shares
            delegate: Rectangle {
              required property var modelData
              required property int index
              width: row.widths[index]
              height: 8
              color: root.tone(D.stageToken(root.names, modelData.name))
            }
          }
        }

        // label: check, cross or a hollow circle
        Item {
          x: parent.width - M.size.control
          width: M.size.control
          height: parent.height
          Icon {
            anchors.centerIn: parent
            visible: D.labelIcon(row.modelData.label) !== "hollow"
            name: D.labelIcon(row.modelData.label)
            size: 14
            color: root.tone(D.toneToken(D.labelTone(row.modelData.label)))
          }
          Rectangle {
            anchors.centerIn: parent
            visible: D.labelIcon(row.modelData.label) === "hollow"
            width: 10
            height: 10
            radius: 5
            color: "transparent"
            border.width: 1
            border.color: root.tk.inkMuted
          }
        }

        MouseArea {
          anchors.fill: parent
          onClicked: root.selectedId = row.modelData.id
        }
      }
    }

    // legend: the stage colors
    Flow {
      width: parent.width
      spacing: M.spacing.xl
      topPadding: M.spacing.sm
      Repeater {
        model: root.names
        delegate: Row {
          required property string modelData
          spacing: M.spacing.sm
          Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 8
            height: 8
            color: root.tone(D.stageToken(root.names, parent.modelData))
          }
          Text {
            text: parent.modelData
            color: root.tk.inkMuted
            font.family: root.service.fontFamily
            font.pixelSize: M.font.caption
          }
        }
      }
    }
  }

  // 3. selected turn
  Rectangle {
    visible: root.hasData && root.pick !== null
    width: parent.width
    height: pickCol.implicitHeight + 2 * M.spacing.xxl
    radius: M.radius.chrome
    color: root.tk.raised
    border.width: M.size.keyline
    border.color: root.tk.keyline

    Column {
      id: pickCol
      x: M.spacing.xxl
      y: M.spacing.xxl
      width: parent.width - 2 * M.spacing.xxl
      spacing: M.spacing.md

      Text {
        width: parent.width
        text: root.pick ? root.pick.transcript : ""
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.font.body
      }

      Repeater {
        model: root.pick ? D.stageShares(root.pick.stages, root.pick.total_ms) : []
        delegate: Item {
          id: stageRow
          required property var modelData
          width: pickCol.width
          height: 16
          Text {
            width: 64
            anchors.verticalCenter: parent.verticalCenter
            text: stageRow.modelData.name
            elide: Text.ElideRight
            color: root.tk.inkMuted
            font.family: root.service.fontFamily
            font.pixelSize: M.font.label
          }
          Rectangle {
            x: 72
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(stageRow.modelData.ms > 0 ? 1 : 0,
              Math.floor((parent.width - 72 - 64) * stageRow.modelData.share))
            height: 8
            color: root.tone(D.stageToken(root.names, stageRow.modelData.name))
          }
          Text {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: Math.round(stageRow.modelData.ms) + " ms"
            color: root.tk.ink
            font.family: root.service.fontFamily
            font.pixelSize: M.font.label
          }
        }
      }

      Text {
        visible: text !== ""
        width: parent.width
        text: root.pick ? root.pick.result : ""
        wrapMode: Text.Wrap
        maximumLineCount: 3
        elide: Text.ElideRight
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.caption
      }
    }
  }

  // 4. top misses
  Column {
    visible: root.hasData && root.reply.misses && root.reply.misses.length > 0
    width: parent.width
    spacing: M.spacing.sm
    Text {
      text: root.ui("ui.dev.misses")
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.body
      font.weight: Font.DemiBold
    }
    Repeater {
      model: root.hasData && root.reply.misses ? root.reply.misses.slice(0, 5) : []
      delegate: Item {
        id: missRow
        required property var modelData
        width: root.width
        height: 16
        Text {
          width: parent.width - 36
          anchors.verticalCenter: parent.verticalCenter
          text: missRow.modelData.pattern
          elide: Text.ElideRight
          color: root.tk.inkMuted
          font.family: root.service.fontFamily
          font.pixelSize: M.font.label
        }
        Text {
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          text: missRow.modelData.count
          color: root.tk.ink
          font.family: root.service.fontFamily
          font.pixelSize: M.font.label
        }
      }
    }
  }
}
