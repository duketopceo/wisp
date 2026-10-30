// Bar pill: the Wisp element beside the bar mark (U3). Idle and offline
// show nothing here (the mark alone carries them, so the bar keeps its rest
// footprint); every other state is a pill of glyph plus word: a 5-bar mic
// waveform for listening, a turning arc for thinking, the buddy's triangle
// for speaking, a pointer for acting with the step count when known, an
// alert in a yellow border for needs you, an x in a red border plus one
// muted word of cause for error (it stays until the next turn starts), and
// after a finished turn a check, "done" and two thumb buttons for the
// service's 8 s rating window (hovering pauses it). While a dev session is
// on, a small yellow "dev" badge sits at the end of the pill, idle included
// (then it is the whole pill), so the mode is never on by accident. Spend, voice and the
// mouse map live in the hover card, not here. The word always repeats the
// state; color is never the only signal. No Timer: the window is the
// service's; the arc turns only while thinking and only in full motion.
import QtQuick
import QtQuick.Shapes
import "../lib/bar.js" as B
import "../lib/metrics.js" as M
import "../lib/motion.js" as Motion
import "../lib/rate.js" as Rate

Item {
  id: root

  property var service: null

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: service ? service.motionMode : "off"
  readonly property var info: B.pillState({
    status: service ? service.status : "offline",
    result: service ? service.result : "",
    errorCode: service ? service.errorCode : "",
    offline: service ? service.offline === true : true,
    confirm: service ? service.confirm !== null : false,
    windowOpen: service ? service.ratingWindowOpen === true : false,
    rateable: service ? Rate.rateable(service.status, service.answer,
      service.result, service.errorCode) : false,
    dev: service ? service.devOn === true : false,
    run: service ? service.run : null
  })
  readonly property real glyphSize: M.font.icon - 2
  // a tap rates the turn it was made on; a newer turn starts the pill fresh
  property string tapped: ""
  property string tappedFor: ""
  readonly property bool rated: tapped !== "" && service !== null && tappedFor === service.turnId

  clip: true
  implicitWidth: info.visible ? pill.width + M.spacing.md : 0
  implicitHeight: pill.height
  opacity: info.visible ? 1 : 0
  Behavior on opacity {
    enabled: root.motionMode !== "off"
    NumberAnimation { duration: 140 }
  }

  // hovering the pill holds the rating window open
  HoverHandler {
    id: hover
    enabled: root.info.visible
  }
  // a Binding (not a handler write) so the flag drops when the pill hides
  // or is destroyed under the pointer; a stuck true would pause the
  // rating window forever
  Binding {
    target: root.service
    property: "pillHover"
    value: hover.hovered && root.info.visible
    when: root.service !== null
    restoreMode: Binding.RestoreBindingOrValue
  }

  Rectangle {
    id: pill
    x: M.spacing.md
    anchors.verticalCenter: parent.verticalCenter
    height: M.size.control - M.spacing.lg
    width: row.implicitWidth + 2 * M.spacing.lg
    radius: M.pillRadius(height, M.radius.chrome)
    color: "transparent"
    border.width: M.size.keyline
    border.color: root.tk[root.info.border] ? root.tk[root.info.border] : "transparent"

    Row {
      id: row
      anchors.centerIn: parent
      spacing: M.spacing.md

      // glyph slot: one of waveform / arc / triangle / icon
      Item {
        visible: root.info.glyph !== ""
        width: root.glyphSize
        height: root.glyphSize
        anchors.verticalCenter: parent.verticalCenter

        Row {
          visible: root.info.glyph === "waveform"
          anchors.centerIn: parent
          spacing: 1
          Repeater {
            model: B.waveBars(root.service ? root.service.level : 0)
            delegate: Rectangle {
              required property var modelData
              required property int index
              objectName: "bar" + index
              width: 2
              height: modelData
              radius: 1
              anchors.verticalCenter: parent.verticalCenter
              color: root.tk.ember
            }
          }
        }

        Item {
          id: arc
          visible: root.info.glyph === "arc"
          anchors.fill: parent
          // turns only while thinking, only in full motion; static otherwise
          RotationAnimator on rotation {
            from: 0
            to: 360
            duration: 1100
            loops: Animation.Infinite
            running: Motion.loops("thinking", root.motionMode) && root.info.kind === "thinking"
          }
          Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            antialiasing: true
            ShapePath {
              fillColor: "transparent"
              strokeColor: root.tk.ember
              strokeWidth: 1.5
              capStyle: ShapePath.RoundCap
              PathAngleArc {
                centerX: root.glyphSize / 2
                centerY: root.glyphSize / 2
                radiusX: root.glyphSize / 2 - 1.5
                radiusY: root.glyphSize / 2 - 1.5
                startAngle: -90
                sweepAngle: 270
              }
            }
          }
        }

        Shape {
          visible: root.info.glyph === "triangle"
          anchors.fill: parent
          preferredRendererType: Shape.CurveRenderer
          antialiasing: true
          ShapePath {
            fillColor: root.tk.ember
            strokeColor: "transparent"
            startX: root.glyphSize / 2
            startY: 1
            PathLine { x: root.glyphSize - 1; y: root.glyphSize - 2 }
            PathLine { x: 1; y: root.glyphSize - 2 }
            PathLine { x: root.glyphSize / 2; y: 1 }
          }
        }

        Icon {
          visible: root.info.glyph !== "waveform" && root.info.glyph !== "arc"
            && root.info.glyph !== "triangle"
          anchors.centerIn: parent
          name: root.info.glyph
          size: root.glyphSize
          color: root.tk[root.info.token] ? root.tk[root.info.token] : "transparent"
        }
      }

      Text {
        textFormat: Text.PlainText
        objectName: "word"
        visible: text !== ""
        anchors.verticalCenter: parent.verticalCenter
        text: !root.service || !root.info.visible ? ""
          : root.info.thumbs && root.rated ? root.service.ui(root.tapped === "incorrect" ? "ui.rate.wrong" : "ui.rate.good")
          : root.service.ui(root.info.wordKey)
        color: root.tk[root.info.wordToken]
        font.family: root.service ? root.service.fontFamily : ""
        font.pixelSize: M.font.label
        font.weight: Font.DemiBold
      }

      // acting: "2/4" when the run knows its steps
      Text {
        textFormat: Text.PlainText
        objectName: "step"
        visible: root.info.step !== ""
        anchors.verticalCenter: parent.verticalCenter
        text: root.info.step
        color: root.tk.inkMuted
        font.family: root.service ? root.service.fontFamily : ""
        font.pixelSize: M.font.label
      }

      // error: one muted word of cause
      Text {
        textFormat: Text.PlainText
        objectName: "cause"
        visible: root.info.cause !== ""
        anchors.verticalCenter: parent.verticalCenter
        text: root.info.cause
        color: root.tk.inkMuted
        font.family: root.service ? root.service.fontFamily : ""
        font.pixelSize: M.font.label
      }

      // done window: rate this turn through the service's label path
      Row {
        visible: root.info.thumbs && !root.rated
        anchors.verticalCenter: parent.verticalCenter
        spacing: M.spacing.sm

        Rectangle {
          id: thumbUp
          objectName: "thumbUp"
          width: M.font.icon + M.spacing.md
          height: width
          radius: M.radius.chip
          color: upArea.pressed ? root.tk.selection : "transparent"
          border.width: M.size.keyline
          border.color: upArea.containsMouse ? root.tk.keylineStrong : root.tk.keyline
          Accessible.role: Accessible.Button
          Accessible.name: root.service ? root.service.ui("ui.label.good") : ""
          function activate() { root.rate("correct"); }
          Icon {
            anchors.centerIn: parent
            name: "thumb-up"
            size: M.font.icon - 2
            color: root.tk.ink
          }
          MouseArea {
            id: upArea
            anchors.fill: parent
            hoverEnabled: true
            onClicked: thumbUp.activate()
          }
        }

        Rectangle {
          id: thumbDown
          objectName: "thumbDown"
          width: thumbUp.width
          height: width
          radius: M.radius.chip
          color: downArea.pressed ? root.tk.selection : "transparent"
          border.width: M.size.keyline
          border.color: downArea.containsMouse ? root.tk.keylineStrong : root.tk.keyline
          Accessible.role: Accessible.Button
          Accessible.name: root.service ? root.service.ui("ui.label.wrong") : ""
          function activate() { root.rate("incorrect"); }
          Icon {
            anchors.centerIn: parent
            name: "thumb-down"
            size: M.font.icon - 2
            color: root.tk.ink
          }
          MouseArea {
            id: downArea
            anchors.fill: parent
            hoverEnabled: true
            onClicked: thumbDown.activate()
          }
        }
      }
      // dev session: the mode badge, in the yellow token (a mode, not an error)
      Rectangle {
        id: devBadge
        objectName: "devBadge"
        visible: root.info.dev
        anchors.verticalCenter: parent.verticalCenter
        width: devWord.implicitWidth + 2 * M.spacing.md
        height: devWord.implicitHeight + M.spacing.sm
        radius: M.radius.chip
        color: "transparent"
        border.width: M.size.keyline
        border.color: root.tk.needsYou
        Text {
          id: devWord
          textFormat: Text.PlainText
          anchors.centerIn: parent
          text: root.service ? root.service.ui("ui.bar.badge") : ""
          color: root.tk.needsYou
          font.family: root.service ? root.service.fontFamily : ""
          font.pixelSize: M.font.caption
          font.weight: Font.DemiBold
        }
      }
    }
  }

  function rate(verdict) {
    if (!root.service) return
    root.tapped = verdict
    root.tappedFor = root.service.turnId
    root.service.label(verdict, root.service.turnId, "")
  }
}
