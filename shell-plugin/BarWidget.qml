import QtQuick
import qs.Commons
import qs.Ui
import "components"
import "lib/bar.js" as B

// Bar mark for io.github.duketopceo.wisp: one glyph for the daemon state
// (components/BarMark), a tooltip with health and spend, and the mouse map
// in components/BarActions: click toggles listening, middle click stops the
// turn, right click opens the Panel. State comes only from WispService (the
// one reader: stream, stale window, offline); this file opens no socket,
// reads no file, runs no Process and no Timer.
BarWidget {
  id: root
  moduleName: "io.github.duketopceo.wisp"

  // The plugin's own service, through the bar's shell facade. Null until the
  // host has injected the bar; the mark then renders offline and the
  // buttons do nothing.
  readonly property var service: bar && bar.shell
    ? bar.shell.serviceFor(moduleName) : null

  readonly property string word: service ? service.wordView.word : "offline"

  // Rebuilt from the service view only when it changes; no polling.
  readonly property string tooltip: service
    ? B.tooltipLines(service.view, {
        word: root.word, hint: service.status === "error" ? service.errorHint : "", notice: service.notice,
        stale: service.stale,
        offline: service.offline, ui: service.ui
      }).join("\n")
    : "wisp: offline"

  readonly property bool opened: panelLoader.item
    ? panelLoader.item.opened === true
    : false

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.anchorItem = button
    panelLoader.item.hostWidget = root
  }

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  BarActions {
    id: actions
    service: root.service
    onPanelRequested: root.toggle()
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    fixedWidth: content.implicitWidth + Style.spaceReal(2 * horizontalMargin)
    tooltipText: root.tooltip
    onPressed: function(buttonCode) { actions.press(buttonCode) }

    // live-activities grow/shrink: the bar widens smoothly while the pill
    // clips and fades its contents in; off when motion is off
    Behavior on fixedWidth {
      enabled: root.service ? root.service.motionMode !== "off" : false
      NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
    }

    Row {
      id: content
      anchors.centerIn: parent
      spacing: 0

      BarMark {
        id: mark
        anchors.verticalCenter: parent.verticalCenter
        service: root.service
        size: Style.bar.iconCanvas
      }

      BarPill {
        anchors.verticalCenter: parent.verticalCenter
        service: root.service
      }
    }
  }
}
