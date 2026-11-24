// Scrolling page for the settings window (U3). Children stack in a
// column inset by the `space` scale. Scrolls by wheel, drag, the themed
// scrollbar, PageUp/PageDown/Home/End, and brings a row into view when
// keyboard focus moves into it.
import QtQuick
import QtQuick.Controls
import "../lib/metrics.js" as M

Flickable {
  id: root

  property var service: null
  default property alias content: column.data
  property alias spacing: column.spacing
  property int margin: M.scale.space.xl
  readonly property real maxY: Math.max(0, contentHeight - height)
  readonly property var tk: service ? service.tokens : ({})
  // the item with keyboard focus in this window, to follow it on Tab
  readonly property Item focusItem: Window.activeFocusItem

  function typing() { return !!focusItem && ("cursorPosition" in focusItem) }
  function scrollTo(y) { contentY = Math.max(0, Math.min(maxY, y)) }
  function scrollBy(dy) { scrollTo(contentY + dy) }
  function ensureVisible(item) {
    if (!item) return
    var p = item.mapToItem(column, 0, 0)
    var top = column.y + p.y - margin
    var bottom = column.y + p.y + item.height + margin
    if (top < contentY) scrollTo(top)
    else if (bottom > contentY + height) scrollTo(bottom - height)
  }
  function isMine(item) {
    for (var p = item; p; p = p.parent) if (p === column) return true
    return false
  }

  onFocusItemChanged: if (focusItem && isMine(focusItem)) ensureVisible(focusItem)

  width: 640
  height: 480
  contentWidth: width
  contentHeight: column.implicitHeight + 2 * margin
  clip: true
  boundsBehavior: Flickable.StopAtBounds
  flickableDirection: Flickable.VerticalFlick
  activeFocusOnTab: false

  Keys.onPressed: (event) => {
    var page = root.height - 2 * root.margin
    if (event.key === Qt.Key_PageDown) root.scrollBy(page)
    else if (event.key === Qt.Key_PageUp) root.scrollBy(-page)
    else if (event.key === Qt.Key_Home && !root.typing()) root.scrollTo(0)
    else if (event.key === Qt.Key_End && !root.typing()) root.scrollTo(root.maxY)
    else return
    event.accepted = true
  }

  Column {
    id: column
    x: root.margin
    y: root.margin
    width: root.width - 2 * root.margin - (bar.visible ? bar.width : 0)
    spacing: M.scale.space.lg
  }

  ScrollBar.vertical: ScrollBar {
    id: bar
    visible: root.contentHeight > root.height
    policy: ScrollBar.AlwaysOn
    width: M.scale.space.sm + 2 * M.scale.focusRing
    padding: M.scale.focusRing
    background: Item {}
    contentItem: Rectangle {
      implicitWidth: M.scale.space.sm
      radius: M.pillRadius(width, M.radius.chrome)
      color: bar.pressed || bar.hovered ? root.tk.ink : root.tk.inkMuted
      opacity: bar.pressed || bar.hovered ? 0.8 : 0.45
    }
  }
}
