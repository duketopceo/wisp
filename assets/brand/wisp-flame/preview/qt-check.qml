// Qt Quick 3D load check for the Wisp flame (not shipped).
// Run in the live desktop session; Quick 3D needs a real GPU backend, so the
// offscreen platform cannot render it:
//
//   qml6 assets/brand/wisp-flame/preview/qt-check.qml
//
// Prints "wisp-flame: qt <status> <errorString>" and quits after a moment.
import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils

Window {
    width: 320
    height: 360
    visible: true
    color: "#0b0c11"
    title: "wisp-flame qt check"

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
        }
        PerspectiveCamera {
            position: Qt.vector3d(0, 45, 600)
            clipNear: 1
        }
        RuntimeLoader {
            id: loader
            source: Qt.resolvedUrl("../export/wisp-flame.glb")
            scale: Qt.vector3d(100, 100, 100)
        }
    }

    function report() {
        const s = loader.status === RuntimeLoader.Success ? "Success"
                : loader.status === RuntimeLoader.Error ? "Error" : "Empty"
        console.log("wisp-flame: qt " + s + " " + loader.errorString)
    }

    Timer {
        interval: 1500
        running: true
        onTriggered: { report(); Qt.quit() }
    }
}
