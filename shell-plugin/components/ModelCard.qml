// ModelCard: a small 3D model from the paper (`::model[url=...]`) whose
// parts can be clicked to ask about. A renderer of one record from
// lib/model3d.js modelOf(): each part is a projected block (no GL), drag
// turns the model, a click on a part sends one question naming it through
// service.askAbout(). Unlike the picture card this one takes the pointer,
// so the host adds it to the window's input region only while it is shown.
pragma ComponentBehavior: Bound
import QtQuick
import "../lib/model3d.js" as Model
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  // lib/model3d.js modelOf(): {title, parts, source, host}
  property var model: null
  property real yaw: Model.YAW0
  property real pitch: Model.PITCH0
  property string hoverName: ""
  readonly property bool hovered: area.containsMouse

  readonly property var tk: service ? service.tokens : ({})
  readonly property var size: Model.cardSize()
  readonly property var rects: model ? Model.project(model.parts, yaw, pitch, size.viewW, size.viewH) : []
  readonly property string caption: hoverName !== "" ? hoverName : (model ? model.title : "")

  width: size.w
  height: size.h
  visible: model !== null

  Rectangle {
    anchors.fill: parent
    radius: M.radius.chrome
    color: root.tk.raised
    border.width: 1
    border.color: root.tk.keyline
  }

  Item {
    id: view
    objectName: "modelView"
    x: Model.PAD
    y: Model.PAD
    width: root.size.viewW
    height: root.size.viewH
    clip: true

    Repeater {
      model: root.rects
      delegate: Rectangle {
        required property var modelData
        required property int index
        objectName: "modelPart"
        x: modelData.x
        y: modelData.y
        width: modelData.w
        height: modelData.h
        z: modelData.depth
        radius: M.radius.chip
        color: root.hoverName === modelData.name ? root.tk.accent : root.tk.canvas
        opacity: root.hoverName === modelData.name ? 1 : 0.85
        border.width: 1
        border.color: root.tk.keylineStrong
      }
    }

    MouseArea {
      id: area
      objectName: "modelArea"
      anchors.fill: parent
      hoverEnabled: true
      property real px: 0
      property real py: 0
      property bool dragged: false
      onPositionChanged: function (m) {
        if (pressed) {
          root.yaw += (m.x - px) * 0.012
          root.pitch = Model.clampPitch(root.pitch + (m.y - py) * 0.012)
          if (Math.abs(m.x - px) + Math.abs(m.y - py) > 0) dragged = true
        } else {
          root.hoverName = Model.hit(root.rects, m.x, m.y)
        }
        px = m.x
        py = m.y
      }
      onPressed: function (m) { px = m.x; py = m.y; dragged = false }
      onExited: root.hoverName = ""
      onReleased: function (m) {
        if (dragged || !root.service) return
        var q = Model.question(root.model ? root.model.title : "", Model.hit(root.rects, m.x, m.y))
        if (q !== "") root.service.askAbout(q)
      }
    }
  }

  Text {
    textFormat: Text.PlainText
    objectName: "modelCaption"
    x: Model.PAD
    y: Model.PAD * 2 + root.size.viewH
    width: root.size.viewW
    height: Model.TITLE_H
    text: root.caption
    elide: Text.ElideRight
    verticalAlignment: Text.AlignVCenter
    color: root.tk.inkMuted
    font.family: root.service ? root.service.fontFamily : ""
    font.pixelSize: M.font.label
  }
}
