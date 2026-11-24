// A Status or management page of the settings window (one-surface U3):
// home, activity, memory, tasks, health, spend, audit or binds. The page
// heading takes keyboard focus on a page change. Under it, the page state
// (lib/manage.js pageState) shows through the shared EmptyState: loading
// and error replace the page, offline and stale sit above what was last
// seen. Health and Spend show offline and stale in their own rows, so the
// frame leaves those two states to them. The last action's outcome shows
// under the heading on every page. Window-free: data arrives as
// properties, actions leave as signals (shells/settings/shell.qml runs
// them through WispService.runAction).
import QtQuick
import "../lib/metrics.js" as M
import "../lib/manage.js" as Manage

ScrollPage {
  id: root

  property string page: "home"
  // the first state since the stream turned on has arrived
  property bool heard: false
  // the page's own read failure ("" when fine): the binds read
  property string error: ""
  // files the shell watches, and the one-shot reads
  property var turns: []
  property var suggestions: []
  property var corrections: []
  property string memoryText: ""
  property string userText: ""
  property string auditText: ""
  property var binds: null
  property var cua: null
  property var spendModels: []
  signal retry()
  signal talk()
  signal restart()
  signal stop()
  signal answer(string pick)
  signal saveMemory(string which, string text)
  signal startTask(string text)
  signal cancelTask(string name)

  // the theme tokens (ScrollPage.tk), under a local name
  readonly property var colors: tk
  readonly property real ts: service ? service.textScale : 1
  readonly property bool ownsLiveStates: page === "health" || page === "spend"
  readonly property string frame: Manage.pageState(heard,
    !ownsLiveStates && service.offline, !ownsLiveStates && service.stale, error)
  readonly property var subKey: ({ home: "ui.home.sub", memory: "ui.memory.sub",
    tasks: "ui.tasks.sub", spend: "ui.manage.spend.sub", audit: "ui.manage.audit.sub",
    binds: "ui.manage.binds.sub" })
  readonly property var act: service.lastAction

  function focusHeading() { heading.forceActiveFocus() }

  onPageChanged: scrollTo(0)

  SectionHeader {
    id: heading
    objectName: "heading"
    service: root.service
    first: true
    width: parent.width
    title: root.service.ui("set.cat." + root.page)
    note: root.subKey.hasOwnProperty(root.page) ? root.service.ui(root.subKey[root.page]) : ""
    activeFocusOnTab: true
  }

  Text {
    objectName: "lastAction"
    textFormat: Text.PlainText
    visible: root.act !== null && root.act !== undefined
    width: parent.width
    wrapMode: Text.Wrap
    text: !visible ? "" : root.act.pending ? root.act.verb + "..." : (root.act.message || root.service.ui("ui.noted"))
    color: visible && root.act.ok === false && !root.act.pending ? root.colors.fail : root.colors.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("caption", root.ts)
  }

  EmptyState {
    objectName: "pageState"
    visible: root.frame !== "ready"
    service: root.service
    width: parent.width
    textKey: "ui.page." + root.frame
    action: root.frame === "offline" || root.frame === "error" ? root.service.ui("ui.set.retry") : ""
    onAct: root.retry()
  }

  Loader {
    id: body
    objectName: "body"
    active: Manage.showsContent(root.frame)
    width: parent.width
    sourceComponent: ({ home: homePage, activity: activityPage, memory: memoryPage,
      tasks: tasksPage, health: healthPage, spend: spendPage, audit: auditPage,
      binds: bindsPage })[root.page] || null
  }

  Component {
    id: homePage
    HomeView {
      width: body.width
      service: root.service
      onTalk: root.talk()
      onRestart: root.restart()
      onStop: root.stop()
    }
  }
  Component {
    id: activityPage
    ActivityView {
      width: body.width
      service: root.service
      turns: root.turns
      suggestions: root.suggestions
      corrections: root.corrections
      onAnswer: (pick) => root.answer(pick)
    }
  }
  Component {
    id: memoryPage
    MemoryView {
      width: body.width
      service: root.service
      memoryText: root.memoryText
      userText: root.userText
      onSave: (which, text) => root.saveMemory(which, text)
    }
  }
  Component {
    id: tasksPage
    AgentsView {
      width: body.width
      service: root.service
      onStart: (text) => root.startTask(text)
      onCancel: (name) => root.cancelTask(name)
    }
  }
  Component {
    id: healthPage
    HealthView {
      width: body.width
      titled: false
      service: root.service
      cua: root.cua
      spendModels: root.spendModels
    }
  }
  Component {
    id: spendPage
    SpendView {
      width: body.width
      titled: false
      service: root.service
      models: root.spendModels
    }
  }
  Component {
    id: auditPage
    AuditView {
      width: body.width
      titled: false
      service: root.service
      log: root.auditText
    }
  }
  Component {
    id: bindsPage
    BindsView {
      width: body.width
      titled: false
      service: root.service
      binds: root.binds
    }
  }
}
