import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "components"
import "lib/onboard.js" as Onboard
import "lib/whatsnew.js" as WhatsNew

// Popup panel for io.github.duketopceo.wisp, opened from the bar mark.
// Four tabs: Now (the turn in flight), Agents (tasks), Memory (skills and
// recent decisions) and Quick (a health summary and the quick settings); a
// fifth, Dev (local only), is appended when `[dev] panel = true`. Until
// setup is finished a first-run card sits on the Now tab (wispd onboard).
// The card body is the window-free components/PanelBody.qml; this file is
// the host and its file and process plumbing. State comes only from the
// plugin's WispService (hostWidget.service). The only files read here are
// skills.json and decisions.jsonl, watched, never polled; there are no
// timers. "Open settings" starts `wispd settings` detached. Every string
// comes from the copy table.
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
  readonly property var baseTabs: ["now", "agents", "memory", "quick"]
  // Dev is index 4, after Quick (index 3), and only with the flag or a
  // dev session on
  readonly property bool devPanelOn: service !== null && service.devTab
  readonly property var tabKeys: service && service.devTab ? baseTabs.concat(["devtab"]) : baseTabs
  property int tab: 0

  property var skills: []
  property var decisions: []
  // `wispd onboard --status` data, and the steps skipped this session
  // (a skip is never written anywhere)
  property var onboard: null
  property var skippedSteps: []
  // `wispd whatsnew --json`: the card for a version just installed, once
  property var whatsnew: null

  onOpenedChanged: {
    if (opened) {
      loadOnboard(); loadWhatsnew()
      if (service) service.loadConfig()
      if (content.item) content.item.focusPage()
    }
    else dismissWhatsnew()
    if (opened && tab === 4 && service) service.loadDev()
  }
  onTabChanged: {
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

  // the settings window, started detached (never through runAction) so it
  // outlives the Panel; the Panel closes behind it
  function openSettings() {
    if (!service) return
    Quickshell.execDetached([service.wispd, "settings"])
    close()
  }

  function onboardRun(argv) {
    if (onboardRunProc.running) return
    onboardRunProc.command = argv
    onboardRunProc.running = true
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

  KeyboardPanel {
    id: panel
    anchorItem: wisp.anchorItem
    owner: wisp.hostWidget || wisp
    bar: wisp.bar
    open: wisp.opened
    contentWidth: panel.fittedContentWidth(Style.space(480))
    contentHeight: panel.fittedContentHeight(content.item ? content.item.implicitHeight : 0)

    PanelKeyCatcher {
      anchors.fill: parent
      onCloseRequested: wisp.close()
      // Tab and Shift+Tab step through the tabs
      onTabRequested: function (direction) {
        var n = wisp.tabKeys.length
        wisp.tab = (wisp.tab + direction + n) % n
      }
    }

    // the card body (components/PanelBody.qml): header, tabs and the
    // scrolling page; it fills the card the host sized from its height
    Loader {
      id: content
      anchors.fill: parent
      active: wisp.service !== null

      sourceComponent: PanelBody {
        service: wisp.service
        tabKeys: wisp.tabKeys
        tab: wisp.tab
        devPanelOn: wisp.devPanelOn
        skills: wisp.skills
        decisions: wisp.decisions
        onboard: wisp.onboard
        skippedSteps: wisp.skippedSteps
        whatsnew: wisp.whatsnew
        onPickTab: function (index) { wisp.tab = index }
        onOpenSettings: wisp.openSettings()
        onCloseRequested: wisp.close()
        onWhatsnewDismiss: wisp.dismissWhatsnew()
        onWhatsnewLink: function (url) {
          var argv = WhatsNew.linkCommand(url)
          if (argv.length === 0 || whatsnewLinkProc.running) return
          whatsnewLinkProc.command = argv
          whatsnewLinkProc.running = true
        }
        onOnboardStep: function (id) {
          wisp.skippedSteps = wisp.skippedSteps.filter(function (s) { return s !== id })
          wisp.onboardRun(Onboard.stepCommand(wisp.service.wispd, id))
        }
        onOnboardSkip: function (id) { wisp.skippedSteps = wisp.skippedSteps.concat([id]) }
        onOnboardUndo: function (id) { wisp.onboardRun(Onboard.undoCommand(wisp.service.wispd, id)) }
        onOnboardFinish: wisp.onboardRun(Onboard.finishCommand(wisp.service.wispd))
      }
    }
  }
}
