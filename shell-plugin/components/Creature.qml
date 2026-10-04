// Wisp creature: one item, all 13 states (lib/creature.js), reparented
// between corner, pill and ghost cursor. With a GPU scene graph it draws
// assets/shaders/wisp.frag (baked to shell-plugin/shaders/wisp.frag.qsb);
// under motion=off, the software backend, or a shader load failure it
// draws the static mark from the same state vectors with plain items.
// Only this component loops, only while the state needs it, only in full
// motion; idle flicker is quantized to 10 Hz, continuous states to 60 Hz
// even on a 120 Hz display. Transients (confirmed, didnt_understand, the
// error return, the beckon) run as finite animations, never timers.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/motion.js" as Motion
import "../lib/creature.js" as C

Item {
  id: root

  property var service: null
  property string status: service ? service.status : "idle"
  property real level: service ? service.level : 0
  property real size: M.creatureSize(status)
  // fixtures and hosts can pin a state; "" derives it from status
  property string forceState: ""
  // "" follows the service; "full" | "reduced" | "off" overrides it
  property string motion: ""
  property real refreshHz: 60
  // TTS envelope 0..1; negative means none (synthetic rhythm)
  property real envelope: -1
  // result state from the copy table ("didnt_understand" or null)
  property string resultState: service && service.resultView.state ? service.resultView.state : ""

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: motion !== "" ? motion : (service ? service.motionMode : "off")

  property string blip: ""
  property bool errorSettled: false
  property string prevStatus: status
  property real clockT: 0
  property real beckon: 0
  property real shakePhase: 0

  readonly property string cstate: forceState !== "" ? forceState
    : C.stateFor(status, blip, errorSettled)
  readonly property real t: C.quantize(clockT, cstate, refreshHz)
  readonly property real env: cstate === "speaking"
    ? (envelope >= 0 ? envelope : C.speakingEnvelope(t, motionMode)) : 0.5
  readonly property var u: C.uniforms(cstate, level, env, motionMode, beckon, C.shakeOffset(shakePhase, 1))
  readonly property color tone: tk[C.toneToken(cstate)]
  readonly property bool dashed: cstate === "offline"
  readonly property bool lightMode: service && service.themeMode === "light"
  readonly property bool shaderOk: motionMode !== "off" && gpu.status === Loader.Ready
    && gpu.item && gpu.item.status !== ShaderEffect.Error

  implicitWidth: size
  implicitHeight: size
  width: size
  height: size

  onStatusChanged: {
    var tr = motionMode === "off" ? "" : C.transition(prevStatus, status, resultState)
    errorSettled = false
    blip = tr
    prevStatus = status
  }

  // --- GPU path ----------------------------------------------------------
  Loader {
    id: gpu
    anchors.fill: parent
    active: root.motionMode !== "off" && GraphicsInfo.api !== GraphicsInfo.Software
    sourceComponent: ShaderEffect {
      property color ember: root.tone
      property color core: root.tk.emberCore
      property vector2d gaze: Qt.vector2d(root.u.gaze[0], root.u.gaze[1])
      property real energy: root.u.energy
      property real cohesion: root.u.cohesion
      property real heat: root.u.heat
      property real time: root.t
      property real mode: root.lightMode ? 1 : 0
      property real dashed: root.dashed ? 1 : 0
      blending: true
      fragmentShader: Qt.resolvedUrl("../shaders/wisp.frag.qsb")
    }
  }

  // --- static mark (off, software, load failure) --------------------------
  Item {
    id: mark
    anchors.fill: parent
    visible: !root.shaderOk
    x: C.shakeOffset(root.shakePhase, root.size * 0.12)

    Rectangle {
      id: halo
      anchors.centerIn: parent
      width: root.size
      height: width
      radius: width / 2
      color: root.dashed ? "transparent" : Qt.alpha(root.tone, 0.06 + 0.26 * root.u.energy)
      border.width: root.dashed ? M.size.keyline : 0
      border.color: Qt.alpha(root.tone, 0.6)
    }
    Rectangle {
      anchors.centerIn: parent
      width: root.size * 0.78
      height: width
      radius: width / 2
      visible: !root.dashed
      color: Qt.alpha(root.tone, 0.10 + 0.24 * root.u.energy)
    }
    // fray: low cohesion sheds satellites around the body
    Repeater {
      model: root.u.cohesion < 0.6 && !root.dashed ? 4 : 0
      delegate: Rectangle {
        required property int index
        width: Math.max(2, root.size * 0.11)
        height: width
        radius: width / 2
        color: Qt.alpha(root.tone, 0.2 + 0.5 * (1 - root.u.cohesion))
        x: root.width / 2 - width / 2 + Math.cos(index * 1.7 + 0.6) * root.size * (0.30 + 0.12 * index / 4)
        y: root.height / 2 - height / 2 + Math.sin(index * 1.7 + 0.6) * root.size * (0.30 + 0.12 * index / 4)
      }
    }
    Rectangle {
      id: body
      anchors.centerIn: parent
      width: root.size * (0.34 + 0.20 * root.u.cohesion + 0.10 * root.u.energy)
      height: width
      radius: width / 2
      color: root.dashed ? "transparent" : Qt.alpha(root.tone, 0.50 + 0.45 * root.u.energy)
      border.width: root.dashed ? M.size.keyline : 0
      border.color: root.tone
      Behavior on color {
        enabled: root.motionMode !== "off"
        ColorAnimation { duration: Motion.duration.effectsDefault; easing.type: Easing.OutCubic }
      }
    }
    // wick: leans against the gaze, warmer as heat rises
    Rectangle {
      visible: !root.dashed
      width: root.size * 0.16
      height: width
      radius: width / 2
      color: Qt.alpha(root.tone, 0.25 + 0.45 * root.u.heat)
      x: root.width / 2 - width / 2 - root.u.gaze[0] * root.size * 0.42
      y: root.height / 2 - height / 2 - root.u.gaze[1] * root.size * 0.42
    }
    Rectangle {
      id: core
      width: root.size * 0.28
      height: width
      radius: width / 2
      visible: !root.dashed
      x: root.width / 2 - width / 2 + root.u.gaze[0] * root.size * 0.11
      y: root.height / 2 - height / 2 + root.u.gaze[1] * root.size * 0.11
      color: root.cstate === "error" ? root.tone : Qt.alpha(root.tk.emberCore, 0.55 + 0.45 * root.u.heat)
    }
    // confirmed: a single bright keyline ring
    Rectangle {
      anchors.centerIn: parent
      width: root.size * 0.9
      height: width
      radius: width / 2
      visible: root.cstate === "confirmed"
      color: "transparent"
      border.width: M.size.keyline
      border.color: root.tk.emberCore
    }
  }

  // --- clock and transients (finite or gated; no timers) -------------------
  NumberAnimation on clockT {
    from: 0
    to: 3600
    duration: 3600000
    loops: Animation.Infinite
    running: Motion.loops(root.cstate, root.motionMode)
      || (root.motionMode === "full" && C.flickers(root.cstate))
  }

  SequentialAnimation {
    running: root.blip === "confirmed" && root.motionMode !== "off"
    PauseAnimation { duration: C.TIMING.confirmedMs }
    ScriptAction { script: root.blip = "" }
  }
  SequentialAnimation {
    running: root.blip === "didnt_understand" && root.motionMode !== "off"
    NumberAnimation {
      target: root
      property: "shakePhase"
      from: 0
      to: root.motionMode === "full" ? 1 : 0
      duration: C.TIMING.shakeMs
    }
    ScriptAction { script: { root.shakePhase = 0; root.blip = "" } }
  }
  SequentialAnimation {
    running: root.status === "error" && root.motionMode !== "off"
    PauseAnimation { duration: C.TIMING.errorReturnMs }
    ScriptAction { script: root.errorSettled = true }
  }
  // awaiting_choice: at most beckonMax pulses, beckonGapMs apart, then still
  SequentialAnimation {
    running: root.cstate === "awaiting_choice" && root.motionMode === "full"
    loops: C.TIMING.beckonMax
    NumberAnimation { target: root; property: "beckon"; to: -0.15; duration: C.TIMING.wakeDipMs }
    NumberAnimation { target: root; property: "beckon"; to: 1; duration: C.TIMING.beckonMs / 3; easing.type: Easing.OutBack }
    NumberAnimation { target: root; property: "beckon"; to: 0; duration: C.TIMING.beckonMs * 2 / 3; easing.type: Easing.InOutSine }
    PauseAnimation { duration: C.TIMING.beckonGapMs }
  }
}
