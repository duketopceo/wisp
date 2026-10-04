// Bar actions: maps a mouse button on the bar mark to the existing daemon
// commands through the service. Left toggles listening (wispd trigger),
// middle interrupts the turn in flight, right asks the host to open the
// Panel; left starts the daemon while the bar reads offline. Non-visual: the bar button forwards its pressed(button) here.
import QtQuick
import "../lib/bar.js" as B

QtObject {
  id: root

  property var service: null

  signal panelRequested()

  function press(button) {
    var a = B.actionFor(button, root.service ? root.service.offline === true : false)
    if (a === "panel") { root.panelRequested(); return a }
    if (!root.service) return ""
    if (a === "talk") root.service.trigger()
    else if (a === "start") root.service.startDaemon()
    else if (a === "stop") root.service.interrupt()
    return a
  }
}
