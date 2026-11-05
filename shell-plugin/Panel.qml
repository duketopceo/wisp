import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "components"
import "lib/onboard.js" as Onboard
import "lib/whatsnew.js" as WhatsNew
import "lib/dev.js" as Dev

// Popup panel for io.github.duketopceo.wisp, opened from the bar mark.
// Four tabs: Now (the turn in flight), Agents (tasks), Memory (skills and
// recent decisions) and Settings (Health, then the config editor); a fifth,
// Dev (local only), is appended when `[dev] panel = true`. Until
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
  readonly property var baseTabs: ["now", "agents", "memory", "settings"]
  // Dev is index 4, after Settings (index 3), and only with the flag or a
  // dev session on
  readonly property bool devPanelOn: service !== null && service.devTab
  readonly property var tabKeys: service && service.devTab ? baseTabs.concat(["devtab"]) : baseTabs
  property int tab: 0

  property var skills: []
  property var decisions: []
  property var connectors: []
  // `wispd onboard --status` data, and the steps skipped this session
  // (a skip is never written anywhere)
  property var onboard: null
  property var skippedSteps: []
  // `wispd whatsnew --json`: the card for a version just installed, once
  property var whatsnew: null

  onOpenedChanged: {
    if (opened) { loadOnboard(); loadWhatsnew(); if (service) service.loadConfig() }
    else dismissWhatsnew()
    if (opened && tab === 3) loadSettings()
    if (opened && tab === 4 && service) service.loadDev()
  }
  onTabChanged: {
    if (tab === 3) loadSettings()
    if (tab === 4 && service) service.loadDev()
  }

  // the flag arrives with the config read: back to Now if it went off, read
  // the Dev data if its tab is already the open one
  Connections {
    target: wisp.service
    function onDevTabChanged() {
      if (!wisp.service.devTab && wisp.tab === 4) wisp.tab = 0
      else if (wisp.service.devTab && wisp.opened && wisp.tab === 4) wisp.service.loadDev()
    }
  }

  // a wrong rating asks for its note: show it on the Now tab
  Connections {
    target: wisp.service
    function onRatePromptTurnChanged() {
      if (wisp.service.ratePromptTurn !== "") wisp.tab = 0
    }
  }

  function loadOnboard() {
    if (!service || onboardStatusProc.running) return
    onboardStatusProc.command = Onboard.statusCommand(service.wispd)
    onboardStatusProc.running = true
  }

  function loadWhatsnew() {
    if (!service || whatsnewProc.running || whatsnewSeenProc.running || whatsnew) return
    whatsnewProc.command = WhatsNew.statusCommand(service.wispd)
    whatsnewProc.running = true
  }

  // closing the panel (or the button) marks the version seen: shown once
  function dismissWhatsnew() {
    if (!whatsnew || !service) return
    whatsnew = null
    whatsnewSeenProc.command = WhatsNew.seenCommand(service.wispd)
    whatsnewSeenProc.running = true
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

  Process {
    id: whatsnewProc
    command: []
    stdout: StdioCollector { id: whatsnewOut }
    onExited: wisp.whatsnew = WhatsNew.parse(whatsnewOut.text)
  }

  Process {
    id: whatsnewSeenProc
    command: []
  }

  Process {
    id: whatsnewLinkProc
    command: []
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
          // local-only marker beside the Dev tab
          Rectangle {
            visible: wisp.devPanelOn
            anchors.verticalCenter: parent.verticalCenter
            width: localBadge.implicitWidth + 2 * Style.space(6)
            height: localBadge.implicitHeight + Style.space(2)
            radius: Style.space(3)
            color: "transparent"
            border.width: 1
            border.color: col.tk.needsYou
            Text {
              textFormat: Text.PlainText
              id: localBadge
              anchors.centerIn: parent
              text: Dev.badgeText(col.svc.devOn, col.svc.devRunsLeft, {
                dev: col.svc.ui("ui.tab.devtab"), local: col.svc.ui("ui.dev.local"),
                one: col.svc.ui("ui.dev.badge.one"), many: col.svc.ui("ui.dev.badge.many") })
              font.capitalization: Font.AllUppercase
              color: col.tk.needsYou
              font.family: col.svc.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
          }
        }

        WhatsNewCard {
          visible: WhatsNew.visible(wisp.whatsnew)
          width: col.width - 2 * col.padding
          service: col.svc
          card: wisp.whatsnew
          onDismiss: wisp.dismissWhatsnew()
          onOpenLink: function (url) {
            var argv = WhatsNew.linkCommand(url)
            if (argv.length === 0 || whatsnewLinkProc.running) return
            whatsnewLinkProc.command = argv
            whatsnewLinkProc.running = true
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
            if (col.svc.sendChoice(pick, col.svc.promptId)) wisp.close()
          }
          onStopClicked: col.svc.interrupt()
          onLabelClicked: function (verdict) { col.svc.label(verdict, col.svc.turnId, "") }
          onNoteSaved: function (text) {
            if (col.svc.ratePrompt !== null) col.svc.label("incorrect", col.svc.ratePrompt.turn, text)
          }
          onNoteSkipped: col.svc.skipRatePrompt()
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

        DevTab {
          visible: wisp.devPanelOn && wisp.tab === 4
          width: col.width - 2 * col.padding
          service: col.svc
          reply: col.svc.devData
          runsReply: col.svc.devRuns
          runsLoading: col.svc.devRunsLoading
          runsError: col.svc.devRunsError
          loading: col.svc.devLoading
          error: col.svc.devError
          onRefresh: col.svc.loadDev()
        }

        Text {
          textFormat: Text.PlainText
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
