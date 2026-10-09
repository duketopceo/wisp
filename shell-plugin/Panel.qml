import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "components"
import "lib/onboard.js" as Onboard

// Popup panel for io.github.duketopceo.wisp, opened from the bar mark.
// Four tabs: Now (the turn in flight), Agents (tasks), Memory (skills and
// recent decisions) and Settings (Health, then the config editor). Until
// setup is finished a first-run card sits above the tabs (wispd onboard). State
// comes only from the plugin's WispService (hostWidget.service); the tab
// bodies are window-free components under components/. The only files read
// here are skills.json and decisions.jsonl, watched, never polled; there
// are no timers. Every string comes from the copy table.
Panel {
  id: wisp
  moduleName: "io.github.duketopceo.wisp"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null

  function open() { wisp.controller.show() }
  function close() { wisp.controller.hide() }
  function toggle() { wisp.opened ? close() : open() }

  readonly property var service: hostWidget && hostWidget.service ? hostWidget.service : null
  readonly property string dataDir: Quickshell.env("HOME") + "/.local/share/wisp"
  readonly property var tabKeys: ["now", "agents", "memory", "settings"]
  property int tab: 0

  property var skills: []
  property var decisions: []
  property var connectors: []
  // `wispd onboard --status` data, and the steps skipped this session
  // (a skip is never written anywhere)
  property var onboard: null
  property var skippedSteps: []

  onOpenedChanged: {
    if (opened) loadOnboard()
    if (opened && tab === 3) loadSettings()
  }
  onTabChanged: if (tab === 3) loadSettings()

  function loadOnboard() {
    if (!service || onboardStatusProc.running) return
    onboardStatusProc.command = Onboard.statusCommand(service.wispd)
    onboardStatusProc.running = true
  }

  function onboardRun(argv) {
    if (onboardRunProc.running) return
    onboardRunProc.command = argv
    onboardRunProc.running = true
  }

  function loadSettings() {
    if (!service) return
    service.loadSettings()
    if (!connListProc.running) connListProc.running = true
  }

  FileView {
    id: skillsView
    path: wisp.dataDir + "/skills.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try { wisp.skills = JSON.parse(text()) } catch (e) { wisp.skills = [] }
    }
  }

  FileView {
    id: decisionsView
    path: wisp.dataDir + "/decisions.jsonl"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var lines = text().split("\n").filter(function (l) { return l.trim() !== "" })
      var out = []
      for (var i = lines.length - 1; i >= 0 && out.length < 15; i--) {
        var d
        try { d = JSON.parse(lines[i]) } catch (e) { continue }
        var res = d.result || ""
        out.push({
          ts: (d.ts || "").slice(11, 19),
          route: d.answers && d.answers.route ? d.answers.route.choice : "?",
          text: (d.transcript || "").slice(0, 40),
          failed: /^(ABORTED|BLOCKED|ERROR|CANCELLED|FAIL|SKIP)/.test(res)
        })
      }
      wisp.decisions = out
    }
  }

  Process {
    id: connListProc
    command: [wisp.service ? wisp.service.wispd : "wispd", "connect", "--list", "--json"]
    stdout: StdioCollector { id: connOut }
    onExited: {
      try { wisp.connectors = JSON.parse(connOut.text) } catch (e) { wisp.connectors = [] }
    }
  }

  Process {
    id: onboardStatusProc
    command: []
    stdout: StdioCollector { id: onboardOut }
    onExited: wisp.onboard = Onboard.parse(onboardOut.text)
  }

  // one card action at a time; the status is re-read when it ends
  Process {
    id: onboardRunProc
    command: []
    onExited: wisp.loadOnboard()
  }

  Process {
    id: connRunProc
    command: []
    onExited: connListProc.running = true
  }

  KeyboardPanel {
    id: panel
    anchorItem: wisp.anchorItem
    owner: wisp.hostWidget || wisp
    bar: wisp.bar
    open: wisp.opened
    contentWidth: panel.fittedContentWidth(Style.space(480))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      anchors.fill: parent
      onCloseRequested: wisp.close()
    }

    Loader {
      id: content
      width: parent.width
      active: wisp.service !== null
      height: item ? item.implicitHeight : 0

      sourceComponent: Column {
        id: col
        readonly property var svc: wisp.service
        readonly property var tk: svc.tokens
        padding: Style.space(14)
        spacing: Style.space(10)
        width: content.width

        StatusLine {
          service: col.svc
        }

        Row {
          Repeater {
            model: wisp.tabKeys
            delegate: PanelTab {
              service: col.svc
              text: col.svc.ui("ui.tab." + modelData)
              selected: wisp.tab === index
              onClicked: wisp.tab = index
            }
          }
        }

        FirstRunCard {
          visible: Onboard.visible(wisp.onboard)
          width: col.width - 2 * col.padding
          service: col.svc
          steps: wisp.onboard ? wisp.onboard.steps : []
          skipped: wisp.skippedSteps
          onRun: function (id) {
            wisp.skippedSteps = wisp.skippedSteps.filter(function (s) { return s !== id })
            wisp.onboardRun(Onboard.stepCommand(col.svc.wispd, id))
          }
          onSkip: function (id) { wisp.skippedSteps = wisp.skippedSteps.concat([id]) }
          onUndo: function (id) { wisp.onboardRun(Onboard.undoCommand(col.svc.wispd, id)) }
          onFinish: wisp.onboardRun(Onboard.finishCommand(col.svc.wispd))
        }

        NowTab {
          visible: wisp.tab === 0
          width: col.width - 2 * col.padding
          service: col.svc
          onChoose: function (pick) {
            col.svc.sendChoice(pick, col.svc.promptId)
            wisp.close()
          }
          onStopClicked: col.svc.interrupt()
          onLabelClicked: function (verdict) { col.svc.label(verdict) }
        }

        AgentsTab {
          visible: wisp.tab === 1
          width: col.width - 2 * col.padding
          service: col.svc
        }

        MemoryTab {
          visible: wisp.tab === 2
          width: col.width - 2 * col.padding
          service: col.svc
          skills: wisp.skills
          decisions: wisp.decisions
        }

        SettingsTab {
          visible: wisp.tab === 3
          width: col.width - 2 * col.padding
          service: col.svc
          cua: col.svc.cuaStatus
          spendModels: col.svc.spendModels
          values: col.svc.configValues
          errors: col.svc.configErrors
          savedKey: col.svc.configSaved
          connectors: wisp.connectors
          onSave: function (key, value) { col.svc.configSet(key, value) }
          onConnectClicked: function (alias) {
            connRunProc.command = [col.svc.wispd, "connect", alias]
            connRunProc.running = true
          }
        }

        Text {
          width: col.width - 2 * col.padding
          text: col.svc.ui("ui.bar.hint")
          color: col.tk.inkMuted
          font.family: col.svc.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }
}
