// Panel body (one-surface U2): everything inside the Panel card, window
// free so the tests and the snapshot harness can mount it. A fixed header
// (the status line with "Open settings" at its right edge, then the tab
// row) over one scrolling page. Only the shown tab sits in the page's
// column, so a hidden tab adds no height; the what's-new and first-run
// banners live on the Now tab. Scroll resets to the top on a tab switch,
// and PageUp, PageDown, Home and End scroll the page. Data arrives as
// properties from Panel.qml; actions that need a process leave as
// signals, the rest call the service. The host keeps keyboard focus and
// forwards keys to `page`.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/onboard.js" as Onboard
import "../lib/whatsnew.js" as WhatsNew
import "../lib/dev.js" as Dev

Item {
  id: root

  property var service: null
  readonly property real ts: service ? service.textScale : 1
  // tab keys in order (now, agents, memory, quick, then devtab when on)
  property var tabKeys: ["now", "agents", "memory", "quick"]
  property int tab: 0
  property bool devPanelOn: false
  property var skills: []
  property var decisions: []
  property var onboard: null
  property var skippedSteps: []
  property var whatsnew: null

  signal pickTab(int index)
  // "" opens the settings window's default page; the Quick tab's health
  // summary asks for "health"
  signal openSettings(string category)
  signal closeRequested()
  signal whatsnewDismiss()
  signal whatsnewLink(string url)
  signal onboardStep(string id)
  signal onboardSkip(string id)
  signal onboardUndo(string id)
  signal onboardFinish()

  readonly property var tk: service ? service.tokens : ({})
  readonly property int pad: M.scale.space.md
  readonly property alias page: page
  // the height the card wants: header plus the shown tab, uncapped (the
  // host caps it to the screen and the page scrolls the rest)
  implicitHeight: page.y + page.contentHeight
  width: 480
  height: implicitHeight

  onTabChanged: page.scrollTo(0)

  Column {
    id: header
    x: root.pad
    y: root.pad
    width: root.width - 2 * root.pad
    spacing: M.scale.space.sm

    Item {
      width: parent.width
      height: Math.max(status.implicitHeight, settingsChip.implicitHeight)

      StatusLine {
        id: status
        anchors.verticalCenter: parent.verticalCenter
        service: root.service
        maxWidth: parent.width - settingsChip.width - M.scale.space.sm
      }

      Chip {
        id: settingsChip
        objectName: "openSettings"
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        service: root.service
        label: root.service ? root.service.ui("ui.panel.settings") : ""
        onClicked: root.openSettings("")
      }
    }

    Row {
      Repeater {
        model: root.tabKeys
        delegate: PanelTab {
          objectName: "tab:" + modelData
          service: root.service
          text: root.service.ui("ui.tab." + modelData)
          selected: root.tab === index
          onClicked: root.pickTab(index)
        }
      }
      // local-only marker beside the Dev tab
      Rectangle {
        visible: root.devPanelOn
        anchors.verticalCenter: parent.verticalCenter
        width: localBadge.implicitWidth + 2 * M.scale.space.xs
        height: localBadge.implicitHeight + M.scale.space.xs
        radius: M.radius.chip
        color: "transparent"
        border.width: M.size.keyline
        border.color: root.tk.needsYou
        Text {
          textFormat: Text.PlainText
          id: localBadge
          anchors.centerIn: parent
          text: root.service ? Dev.badgeText(root.service.devOn, root.service.devRunsLeft, {
            dev: root.service.ui("ui.tab.devtab"), local: root.service.ui("ui.dev.local"),
            one: root.service.ui("ui.dev.badge.one"), many: root.service.ui("ui.dev.badge.many") }) : ""
          font.capitalization: Font.AllUppercase
          color: root.tk.needsYou
          font.family: root.service ? root.service.fontFamily : ""
          font.pixelSize: M.fontSize("label", root.ts)
        }
      }
    }
  }

  ScrollPage {
    id: page
    objectName: "page"
    service: root.service
    y: header.y + header.height + M.scale.space.sm
    width: root.width
    height: Math.max(0, root.height - y)
    margin: root.pad
    spacing: M.scale.space.lg

    Column {
      objectName: "nowPage"
      visible: root.tab === 0
      width: parent.width
      spacing: M.scale.space.lg

      WhatsNewCard {
        visible: WhatsNew.visible(root.whatsnew)
        width: parent.width
        service: root.service
        card: root.whatsnew
        onDismiss: root.whatsnewDismiss()
        onOpenLink: function (url) { root.whatsnewLink(url) }
      }

      FirstRunCard {
        visible: Onboard.visible(root.onboard)
        width: parent.width
        service: root.service
        steps: root.onboard ? root.onboard.steps : []
        skipped: root.skippedSteps
        onRun: function (id) { root.onboardStep(id) }
        onSkip: function (id) { root.onboardSkip(id) }
        onUndo: function (id) { root.onboardUndo(id) }
        onFinish: root.onboardFinish()
      }

      NowTab {
        width: parent.width
        service: root.service
        onChoose: function (pick) {
          if (root.service.sendChoice(pick, root.service.promptId)) root.closeRequested()
        }
        onStopClicked: root.service.interrupt()
        onLabelClicked: function (verdict) { root.service.label(verdict, root.service.turnId, "") }
        onNoteSaved: function (text) {
          if (root.service.ratePrompt !== null) root.service.label("incorrect", root.service.ratePrompt.turn, text)
        }
        onNoteSkipped: root.service.skipRatePrompt()
      }
    }

    AgentsTab {
      visible: root.tab === 1
      width: parent.width
      service: root.service
    }

    MemoryTab {
      visible: root.tab === 2
      width: parent.width
      service: root.service
      skills: root.skills
      decisions: root.decisions
    }

    QuickTab {
      visible: root.tab === 3
      width: parent.width
      service: root.service
      onOpenHealth: root.openSettings("health")
    }

    DevTab {
      visible: root.devPanelOn && root.tab === 4
      width: parent.width
      service: root.service
      reply: root.service.devData
      runsReply: root.service.devRuns
      runsLoading: root.service.devRunsLoading
      runsError: root.service.devRunsError
      loading: root.service.devLoading
      error: root.service.devError
      onRefresh: root.service.loadDev()
    }

    Text {
      textFormat: Text.PlainText
      width: parent.width
      wrapMode: Text.Wrap
      text: root.service ? root.service.ui("ui.bar.hint") : ""
      color: root.tk.inkMuted
      font.family: root.service ? root.service.fontFamily : ""
      font.pixelSize: M.fontSize("label", root.ts)
    }
  }
}
