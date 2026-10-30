// Card: a picture from the paper (`::image[url=...]`) with its source line.
// A pure renderer of one image record from lib/card.js imageOf(): the local
// copy wisp stored (never a remote URL) and where it came from. The host
// (OverlayLayer) places it with Card.place() on calm space; the card is
// click-through and holds no state of its own.
pragma ComponentBehavior: Bound
import QtQuick
import "../lib/card.js" as CardLib
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  // lib/card.js imageOf(): {local, source, host, w, h, alt, caption}
  property var img: null
  // fixtures pin a picture instead of the stored local copy
  property url pictureOverride: ""

  readonly property var tk: service ? service.tokens : ({})
  readonly property var size: CardLib.cardSize(img)
  readonly property string sourceText: img ? CardLib.sourceLine(img.source) : ""

  width: size.w
  height: size.h
  visible: img !== null

  Rectangle {
    anchors.fill: parent
    radius: M.radius.chrome
    color: root.tk.raised
    border.width: 1
    border.color: root.tk.keyline
  }

  Image {
    id: pic
    objectName: "cardPicture"
    x: CardLib.PAD
    y: CardLib.PAD
    width: root.size.picW
    height: root.size.picH
    fillMode: Image.PreserveAspectFit
    asynchronous: false
    cache: false
    source: root.pictureOverride.toString() !== "" ? root.pictureOverride
      : (root.img ? CardLib.fileUrl(root.img.local) : "")
  }

  Text {
    textFormat: Text.PlainText
    objectName: "cardSource"
    x: CardLib.PAD
    y: CardLib.PAD * 2 + root.size.picH
    width: root.size.picW
    height: CardLib.SOURCE_H
    text: root.sourceText
    elide: Text.ElideMiddle
    verticalAlignment: Text.AlignVCenter
    color: root.tk.inkMuted
    font.family: root.service ? root.service.fontFamily : ""
    font.pixelSize: M.font.label
  }
}
