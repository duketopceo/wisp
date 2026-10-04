import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Popup panel for io.github.duketopceo.wisp — opened from the bar glyph.
// Tabs: Now (status/transcript/answer/choices/steps), Agents (tasks),
// Activity (recent decisions), Tele (24h digest), Skills (imported
// skills incl. luke-agents). All data is read from local files/state —
// no daemons spawned per render.
Panel {
  id: wisp
  moduleName: "io.github.duketopceo.wisp"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null

  function open() { wisp.controller.show() }
  function close() { wisp.controller.hide() }
  function toggle() { wisp.opened ? close() : open() }

  readonly property string status: hostWidget ? hostWidget.status : "offline"
  readonly property string transcript: hostWidget ? hostWidget.transcript : ""
  readonly property string answer: hostWidget ? hostWidget.answer : ""
  readonly property string result: hostWidget ? hostWidget.result : ""
  readonly property var choices: hostWidget ? hostWidget.choices : []
  readonly property var tasks: hostWidget ? hostWidget.tasks : ({})
  readonly property var steps: hostWidget ? hostWidget.steps : []
  readonly property var suggestion: hostWidget ? hostWidget.suggestion : null
  readonly property var focus: hostWidget ? hostWidget.focus : ({})
  readonly property string goal: hostWidget ? hostWidget.goal : ""
  // Talk / Act / Agent badge — derived from the last result prefix,
  // human words not route names
  readonly property string mode: {
    var r = result || "";
    if (r.indexOf("ACTED") === 0) return "agent";
    if (r.indexOf("ASK_USER") === 0) return "asking";
    if (r.indexOf("ANSWERED") === 0 || status === "speaking")
      return "talk";
    if (r.indexOf("BLOCKED") === 0) return "blocked";
    if (busy) return "thinking";
    return "";
  }
  readonly property string error: hostWidget ? hostWidget.error : ""
  readonly property bool busy: hostWidget ? hostWidget.busy : false

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.5)
  readonly property color accent: Color.accent
  readonly property color urgent: Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property color stateColor: status === "listening" ? accent
    : status === "awaiting_choice" || status === "suggestion" ? urgent
    : status === "error" || status === "offline" ? dim
    : fg

  readonly property string dataDir: Quickshell.env("HOME")
    + "/.local/share/wisp"
  readonly property string wispdBin: Quickshell.env("HOME")
    + "/.local/bin/wispd"
  property int tab: 0
  readonly property var tabNames: ["Now", "Agents", "Activity", "Tele", "Skills", "Context", "Connect"]

  // --- U5/U6/U7 surfaces ---
  property var sessionTurns: []
  property var inventory: null
  property var connectors: []
  property string contextText: ""
  property bool connectBusy: false

  FileView {
    id: sessionView
    path: wisp.dataDir + "/session.jsonl"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var lines = text.split("\n").filter(function(l){ return l.trim() !== "" })
      var out = []
      for (var i = Math.max(0, lines.length - 5); i < lines.length; i++) {
        try {
          var t = JSON.parse(lines[i])
          out.push({text: (t.transcript || "").slice(0, 42),
                    route: t.route || "",
                    ts: (t.ts || "").slice(11, 19)})
        } catch (e) {}
      }
      wisp.sessionTurns = out.reverse()
    }
  }

  FileView {
    id: invView
    path: wisp.dataDir + "/inventory.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try { wisp.inventory = JSON.parse(text) }
      catch (e) { wisp.inventory = null }
    }
  }

  Process {
    id: ctxProc
    command: [wisp.wispdBin, "context"]
    stdout: StdioCollector {}
    onExited: wisp.contextText = stdout.text || ""
  }

  Process {
    id: connListProc
    command: [wisp.wispdBin,
              "connect", "--list", "--json"]
    stdout: StdioCollector {}
    onExited: {
      try { wisp.connectors = JSON.parse(stdout.text) }
      catch (e) { wisp.connectors = [] }
    }
  }

  Process {
    id: connRunProc
    command: [wisp.wispdBin, "connect", ""]
    onExited: {
      wisp.connectBusy = false
      connListProc.running = false
      connListProc.running = true   // refresh status after a connect
    }
  }

  function runConnect(alias) {
    if (wisp.connectBusy) return
    wisp.connectBusy = true
    connRunProc.command = [wisp.wispdBin, "connect", alias]
    connRunProc.running = true
  }

  // --- local ledgers ---
  property var decisions: []
  property var skills: []
  property var tele: ({routes: "", tools: "", turns: 0, okRate: 0, ms: ""})

  FileView {
    id: decisionsView
    path: wisp.dataDir + "/decisions.jsonl"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: wisp.parseDecisions(text)
  }
  FileView {
    id: skillsView
    path: wisp.dataDir + "/skills.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: wisp.parseSkills(text)
  }
  Timer {  // refresh digests while the panel is open
    interval: 2000
    running: wisp.opened
    repeat: true
    onTriggered: { decisionsView.reload(); skillsView.reload() }
  }

  function parseDecisions(raw) {
    var lines = raw.split("\n").filter(function(l){ return l.trim() !== "" })
    var tail = lines.slice(-40).reverse()
    var out = []
    var routes = {}, ok = 0, n = 0, msSum = {}, msN = {}
    var start = Math.max(0, lines.length - 200)
    for (var i = start; i < lines.length; i++) {
      var d
      try { d = JSON.parse(lines[i]) } catch (e) { continue }
      n++
      var r = d.answers && d.answers.route ? d.answers.route.choice : "?"
      routes[r] = (routes[r] || 0) + 1
      var res = d.result || ""
      if (!/^(ABORTED|BLOCKED|ERROR|CANCELLED|FAIL|SKIP)/.test(res)) ok++
      for (var k in (d.timing_ms || {})) {
        msSum[k] = (msSum[k] || 0) + d.timing_ms[k]
        msN[k] = (msN[k] || 0) + 1
      }
      if (out.length < 40)
        out.push({
          ts: (d.ts || "").slice(11, 19),
          route: r,
          text: (d.transcript || "").slice(0, 40),
          res: res.slice(0, 60)
        })
    }
    wisp.decisions = out
    var rlist = [], mlist = []
    for (var rk in routes) rlist.push(rk + ":" + routes[rk])
    for (var mk in msSum) mlist.push(mk + "=" + Math.round(msSum[mk] / msN[mk]))
    wisp.tele = {
      turns: n,
      okRate: n ? Math.round(100 * ok / n) : 0,
      routes: rlist.join(", "),
      ms: mlist.join(", ")
    }
  }

  function parseSkills(raw) {
    try { wisp.skills = JSON.parse(raw) } catch (e) { wisp.skills = [] }
  }

  Process {
    id: labelProc
    command: [wisp.wispdBin, "label", ""]
  }

  function sendLabel(which) {
    labelProc.command = [wisp.wispdBin, "label", which]
    labelProc.running = true
  }

  Process {
    id: interruptProc
    command: [wisp.wispdBin, "interrupt"]
  }

  function sendInterrupt() {
    interruptProc.running = false
    interruptProc.running = true
  }

  KeyboardPanel {
    id: panel
    anchorItem: wisp.anchorItem
    owner: wisp.hostWidget || wisp
    bar: wisp.bar
    open: wisp.opened
    contentWidth: panel.fittedContentWidth(Style.space(560))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      anchors.fill: parent
      onCloseRequested: wisp.close()
    }

    Column {
      id: content
      width: parent.width
      padding: Style.space(14)
      spacing: Style.space(10)

      // header
      Row {
        spacing: Style.space(8)
        Text {
          text: "✦"
          color: wisp.stateColor
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }
        Text {
          text: "Wisp — " + wisp.status
              + (wisp.focus.app ? " · " + wisp.focus.app : "")
          color: wisp.stateColor
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }
        Rectangle {
          visible: wisp.mode.length > 0
          height: modeLabel.implicitHeight + 6
          width: modeLabel.implicitWidth + 12
          radius: 4
          color: wisp.mode === "agent" ? wisp.urgent
               : wisp.mode === "act" ? wisp.accent
               : Qt.rgba(wisp.fg.r, wisp.fg.g, wisp.fg.b, 0.10)
          Text {
            id: modeLabel
            anchors.centerIn: parent
            text: wisp.mode
            color: wisp.mode === "talk" ? wisp.dim : "#fff"
            font.family: wisp.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
        }
      }

      // tab strip
      Row {
        spacing: Style.space(4)
        Repeater {
          model: wisp.tabNames
          delegate: Rectangle {
            width: tabLabel.implicitWidth + 14
            height: tabLabel.implicitHeight + 8
            radius: 6
            color: wisp.tab === index ? wisp.accent
              : Qt.rgba(wisp.fg.r, wisp.fg.g, wisp.fg.b,
                        tabHover.containsMouse ? 0.12 : 0.05)
            Text {
              id: tabLabel
              anchors.centerIn: parent
              text: modelData
              color: wisp.tab === index ? wisp.fg : wisp.dim
              font.family: wisp.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
            MouseArea {
              id: tabHover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: wisp.tab = index
            }
          }
        }
      }

      // ---- Now ----
      Column {
        visible: wisp.tab === 0
        width: parent.width - parent.padding * 2
        spacing: Style.space(8)

        Text {
          visible: wisp.focus.title
          text: "focused: " + wisp.focus.title
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          visible: wisp.goal.length > 0
          text: "working on: " + wisp.goal
          color: wisp.accent
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          visible: wisp.transcript.length > 0
          text: "heard: " + wisp.transcript
          color: wisp.fg
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          visible: wisp.answer.length > 0
          text: wisp.answer
          color: wisp.accent
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.WordWrap
          width: parent.width
        }
        // step timeline — numbered, newest emphasized
        Column {
          visible: wisp.steps.length > 0
          width: parent.width
          spacing: 2
          Repeater {
            model: wisp.steps
            delegate: Row {
              width: parent.width
              spacing: 6
              Text {
                text: String(index + 1)
                color: index === wisp.steps.length - 1
                       ? wisp.accent : wisp.dim
                font.family: wisp.fontFamily
                font.pixelSize: Style.font.bodySmall
                font.bold: index === wisp.steps.length - 1
              }
              Text {
                text: String(modelData)
                color: index === wisp.steps.length - 1
                       ? wisp.fg : wisp.dim
                font.family: wisp.fontFamily
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.WordWrap
                width: parent.width - 20
              }
            }
          }
        }
        // wisp asks — ASK_USER backchannel gets its own row, not a
        // plain result line
        Text {
          visible: wisp.result.indexOf("ASK_USER") === 0
          text: "wisp asks: " + wisp.result.slice(9).trim()
          color: wisp.urgent
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
          wrapMode: Text.WordWrap
          width: parent.width
        }
        // stop control while a turn is in flight — interrupt cancels
        // the act loop without killing the daemon
        Rectangle {
          visible: wisp.busy
          height: stopTxt.implicitHeight + 8
          width: stopTxt.implicitWidth + 18
          radius: 6
          color: Qt.rgba(wisp.urgent.r, wisp.urgent.g, wisp.urgent.b,
                         stopHov.containsMouse ? 0.45 : 0.2)
          Text {
            id: stopTxt
            anchors.centerIn: parent
            text: "■ stop"
            color: "#fff"
            font.family: wisp.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.bold: true
          }
          MouseArea {
            id: stopHov
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: wisp.sendInterrupt()
          }
        }
        Text {
          visible: wisp.result.length > 0
              && wisp.result.indexOf("ASK_USER") !== 0
          text: wisp.result
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          visible: wisp.error.length > 0
          text: wisp.error
          color: wisp.urgent
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          visible: wisp.suggestion !== null
          text: "suggestion: " + JSON.stringify(wisp.suggestion).slice(0, 120)
          color: wisp.urgent
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Flow {
          visible: wisp.choices.length > 0
          width: parent.width
          spacing: Style.spacing.sm
          Repeater {
            model: wisp.choices
            delegate: Button {
              text: String(modelData).replace(/^suggestion:/, "")
              onClicked: {
                if (wisp.hostWidget) wisp.hostWidget.sendChoice(modelData)
                wisp.close()
              }
            }
          }
        }
        // soak labels — ✓/✗ on the last finished turn feeds
        // corrections.jsonl + trajectory memory. Only shown when there
        // is a completed result to judge.
        Row {
          visible: !wisp.busy
            && (wisp.result.length > 0 || wisp.transcript.length > 0)
          spacing: Style.space(6)
          Text {
            text: "was that right?"
            color: wisp.dim
            font.family: wisp.fontFamily
            font.pixelSize: Style.font.bodySmall
            anchors.verticalCenter: parent.verticalCenter
          }
          Rectangle {
            width: okTxt.implicitWidth + 16
            height: okTxt.implicitHeight + 8
            radius: 6
            color: Qt.rgba(wisp.accent.r, wisp.accent.g, wisp.accent.b,
                           okHov.containsMouse ? 0.35 : 0.15)
            Text {
              id: okTxt
              anchors.centerIn: parent
              text: "✓ yes"
              color: wisp.fg
              font.family: wisp.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
            MouseArea {
              id: okHov
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: wisp.sendLabel("correct")
            }
          }
          Rectangle {
            width: noTxt.implicitWidth + 16
            height: noTxt.implicitHeight + 8
            radius: 6
            color: Qt.rgba(wisp.urgent.r, wisp.urgent.g, wisp.urgent.b,
                           noHov.containsMouse ? 0.35 : 0.15)
            Text {
              id: noTxt
              anchors.centerIn: parent
              text: "✗ no"
              color: wisp.fg
              font.family: wisp.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
            MouseArea {
              id: noHov
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: wisp.sendLabel("incorrect")
            }
          }
        }
        // session strip — last 5 turns, newest first; read-only
        // context for "what did wisp just do"
        Column {
          visible: wisp.sessionTurns.length > 0
          width: parent.width
          spacing: 3
          Text {
            text: "recent"
            color: wisp.dim
            font.family: wisp.fontFamily
            font.pixelSize: Style.font.bodySmall
            opacity: 0.8
          }
          Repeater {
            model: wisp.sessionTurns
            delegate: Text {
              width: parent.width
              text: modelData.ts + "  " + modelData.route
                + "  " + modelData.text
              color: wisp.dim
              font.family: wisp.fontFamily
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }
          }
        }
      }

      // ---- Agents ----
      Column {
        visible: wisp.tab === 1
        width: parent.width - parent.padding * 2
        spacing: Style.space(6)
        Text {
          visible: Object.keys(wisp.tasks).length === 0
          text: "no agent tasks"
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
        Repeater {
          model: Object.keys(wisp.tasks)
          delegate: Column {
            width: parent.width
            spacing: 2
            Text {
              text: modelData + "  [" + wisp.tasks[modelData].status + "]"
              color: wisp.tasks[modelData].status === "running"
                ? wisp.accent : wisp.dim
              font.family: wisp.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
            Text {
              visible: wisp.tasks[modelData].task !== ""
              text: wisp.tasks[modelData].task || ""
              color: wisp.dim
              font.family: wisp.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
              width: parent.width
            }
          }
        }
      }

      // ---- Activity ----
      Column {
        visible: wisp.tab === 2
        width: parent.width - parent.padding * 2
        spacing: 4
        Text {
          visible: wisp.decisions.length === 0
          text: "no decisions yet"
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
        Repeater {
          model: wisp.decisions.slice(0, 15)
          delegate: Text {
            text: modelData.ts + "  " + modelData.route + "  "
              + modelData.text + (modelData.res ? "  → " + modelData.res : "")
            color: /^(ABORTED|BLOCKED|ERROR|CANCELLED|FAIL|SKIP)/
              .test(modelData.res) ? wisp.urgent : wisp.dim
            font.family: wisp.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
            width: parent.width
          }
        }
      }

      // ---- Tele ----
      Column {
        visible: wisp.tab === 3
        width: parent.width - parent.padding * 2
        spacing: Style.space(6)
        Text {
          text: wisp.tele.turns + " turns · " + wisp.tele.okRate + "% ok"
          color: wisp.fg
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }
        Text {
          text: "routes: " + wisp.tele.routes
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          text: "avg ms: " + wisp.tele.ms
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          text: "local only — decisions.jsonl + trace.jsonl"
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          opacity: 0.7
        }
      }

      // ---- Skills ----
      Column {
        visible: wisp.tab === 4
        width: parent.width - parent.padding * 2
        spacing: 4
        Text {
          text: wisp.skills.length + " skills"
            + " (incl. luke-agents imports)"
          color: wisp.fg
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }
        Repeater {
          model: wisp.skills.slice(0, 20)
          delegate: Text {
            text: (modelData.tool ? "⚙ " : "· ") + modelData.name
              + " — " + modelData.description
            color: wisp.dim
            font.family: wisp.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
            width: parent.width
            elide: Text.ElideRight
            maximumLineCount: 2
          }
        }
        Text {
          visible: wisp.skills.length > 20
          text: "… " + (wisp.skills.length - 20) + " more — `wispd skills`"
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          opacity: 0.7
        }
      }

      // ---- Context ---- what Wisp sees: focus, workspaces, inventory
      Column {
        visible: wisp.tab === 5
        width: parent.width - parent.padding * 2
        spacing: Style.space(6)
        onVisibleChanged: {
          if (visible && !ctxProc.running) ctxProc.running = true
        }
        Text {
          text: "what wisp sees"
          color: wisp.fg
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }
        Text {
          visible: wisp.focus.app
          text: "focused: " + wisp.focus.app
              + (wisp.focus.title ? " — " + wisp.focus.title : "")
          color: wisp.accent
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          text: wisp.contextText || "(fetching — wispd context)"
          color: wisp.dim
          font.family: "monospace"
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
          width: parent.width
        }
        Text {
          visible: wisp.inventory !== null
          text: {
            if (!wisp.inventory) return ""
            var i = wisp.inventory
            var mcp = i.mcp ? Object.keys(i.mcp).length : 0
            return "inventory: " + (i.apps ? i.apps.length : 0) + " apps · "
              + (i.cli_tools ? i.cli_tools.length : 0) + " cli tools · "
              + mcp + " mcp servers · "
              + (i.skills ? i.skills.length : 0) + " skills"
          }
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }
        Text {
          visible: wisp.inventory === null
          text: "no inventory — run `wispd inventory`"
          color: wisp.urgent
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }

      // ---- Connect ---- OAuth connectors via the Strata gateway
      Column {
        visible: wisp.tab === 6
        width: parent.width - parent.padding * 2
        spacing: 4
        onVisibleChanged: {
          if (visible && !connListProc.running) connListProc.running = true
        }
        Text {
          text: "connectors (" + wisp.connectors.length + ")"
              + (wisp.connectBusy ? " — authorizing…" : "")
          color: wisp.fg
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }
        Repeater {
          model: wisp.connectors
          delegate: Row {
            width: parent.width
            spacing: 8
            Rectangle {
              width: 7; height: 7; radius: 4
              anchors.verticalCenter: parent.verticalCenter
              color: modelData.connected ? wisp.accent : wisp.dim
            }
            Text {
              text: modelData.name
              color: wisp.fg
              font.family: wisp.fontFamily
              font.pixelSize: Style.font.bodySmall
              width: parent.width - 130
              elide: Text.ElideRight
            }
            Text {
              visible: !modelData.connected
              text: "connect"
              color: connHov.containsMouse && !wisp.connectBusy
                     ? wisp.accent : wisp.dim
              font.family: wisp.fontFamily
              font.pixelSize: Style.font.bodySmall
              font.underline: connHov.containsMouse
              MouseArea {
                id: connHov
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: wisp.runConnect(modelData.alias)
              }
            }
          }
        }
        Text {
          visible: wisp.connectors.length === 0
          text: "catalog empty — needs BrowserOS running + `wispd inventory`"
          color: wisp.dim
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
        }
      }

      Text {
        text: "SUPER+D toggles the mic · right-click the glyph to record"
        color: wisp.dim
        font.family: wisp.fontFamily
        font.pixelSize: Style.font.bodySmall
        opacity: 0.7
      }
    }
  }
}
