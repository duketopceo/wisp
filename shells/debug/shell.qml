import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import "components"

// Wisp: management app. Open/close from the launcher (the desktop entry's
// Panel action opens it); the daemon stays resident. Views: Home (what it is
// doing + controls), Activity (turn replay), Memory (editable notes it reads
// every turn), Agents (background tasks), Health (W22 section), Spend (W14
// ledger), Audit (cua.jsonl, read only), Binds (hotkey + Hyprland binds),
// Settings (config.toml, grouped + explained).
//
// One reader: WispService (the W17 reader, shared with the shell plugin)
// owns state, theme tokens and the one-shot wispd reads. This file opens no
// state.json, runs no timers, and polls nothing: files that change while a
// view is open (decisions, corrections, notes, the cua audit log) are
// watched, and wispd results are read once when a view opens.

FloatingWindow {
  id: win
  title: "Wisp"
  minimumSize: Qt.size(900, 640)
  color: bg

  readonly property string dataDir:
      Quickshell.env("HOME") + "/.local/share/wisp"
  readonly property string auditPath: {
    var base = Quickshell.env("XDG_STATE_HOME");
    if (!base || base.length === 0)
      base = Quickshell.env("HOME") + "/.local/state";
    return base + "/wisp/cua.jsonl";
  }

  WispService { id: svc }

  property var decisions: []
  property var corrections: []
  property var suggestions: []
  property string auditText: ""
  property var bindsData: null
  property int tab: 0

  readonly property var tabs: ["home", "activity", "memory", "agents",
                               "health", "spend", "audit", "binds",
                               "settings"]

  function wispd(args) {
    if (cmdProc.running) return;
    cmdProc.command = [svc.wispd].concat(args);
    cmdProc.running = true;
  }
  function svcCtl(args) {
    if (svcProc.running) return;
    svcProc.command =
        ["systemctl", "--user"].concat(args).concat(["wispd"]);
    svcProc.running = true;
  }
  // a task is {status, task, ...}; older daemons publish just the status
  function taskOf(name) {
    var t = svc.tasks[name];
    if (t === null || t === undefined) return {};
    return typeof t === "string" ? { status: t, task: "" } : t;
  }

  // One-shot reads when a view opens (never on a timer).
  function enter(key) {
    if (key === "health" || key === "spend" || key === "settings")
      svc.loadSettings();
    if (key === "binds" && !bindsProc.running) bindsProc.running = true;
  }
  onTabChanged: enter(tabs[tab])
  Component.onCompleted: svc.loadSettings()

  // ── data plumbing: watched files ───────────────────────────────

  FileView {
    id: decisionsView
    path: win.dataDir + "/decisions.jsonl"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var out = [];
      var lines = decisionsView.text().split("\n");
      for (var i = lines.length - 1; i >= 0 && out.length < 30; i--) {
        var l = lines[i].trim();
        if (!l) continue;
        try { out.unshift(JSON.parse(l)) } catch (e) {}
      }
      win.decisions = out;
    }
  }

  FileView {
    id: corrView
    path: win.dataDir + "/corrections.jsonl"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var lines = corrView.text().split("\n")
          .filter(function(l) { return l.trim() });
      win.corrections = lines.slice(-6).reverse();
    }
  }

  FileView {
    id: suggView
    path: win.dataDir + "/suggestions.jsonl"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      // latest record per key wins: the file appends status updates
      var latest = {};
      var lines = suggView.text().split("\n");
      for (var i = 0; i < lines.length; i++) {
        var l = lines[i].trim();
        if (!l) continue;
        try {
          var r = JSON.parse(l);
          if (r.key) {
            var prev = latest[r.key] || {};
            for (var k in r) prev[k] = r[k];
            latest[r.key] = prev;
          }
        } catch (e) {}
      }
      var out = [];
      for (var key in latest) {
        if (latest[key].status === "new") out.push(latest[key]);
      }
      win.suggestions = out.reverse();  // newest first
    }
  }

  FileView { id: memoryView; path: win.dataDir + "/MEMORY.md" }
  FileView { id: userView;    path: win.dataDir + "/USER.md" }

  // cua audit log (wisp/cua_safety.audit_default_path()): read only.
  FileView {
    id: auditView
    path: win.auditPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: win.auditText = auditView.text()
    onLoadFailed: win.auditText = ""
  }

  Process {
    id: bindsProc
    command: [svc.wispd, "binds", "--json"]
    stdout: StdioCollector {
      onStreamFinished: {
        try { win.bindsData = JSON.parse(this.text).data }
        catch (e) { win.bindsData = null }
      }
    }
  }
  Process { id: cmdProc; command: [svc.wispd] }
  Process { id: svcProc
            command: ["systemctl", "--user", "status", "wispd"] }
  Process { id: writeProc; command: [svc.wispd] }

  // ── design tokens ──────────────────────────────────────────────
  // Omarchy theme tokens come from the service (lib/tokens.js over the
  // current theme's colors.toml, re-read when the theme swaps, see the
  // Commons shim beside this file). Fewer boxes, hairline separators,
  // mono for labels + data, sans for prose.

  readonly property var tk: svc.tokens
  readonly property color bg: tk.canvas
  readonly property color raised: tk.raised
  readonly property color hairline: tk.keyline
  readonly property color fg: tk.ink
  readonly property color sub: tk.inkMuted
  readonly property color faint: tk.inkMuted
  readonly property color accent: tk.accent
  readonly property color ember: tk.ember
  readonly property color ok: tk.ok
  readonly property color warn: tk.needsYou
  readonly property color err: tk.fail

  readonly property string mono: svc.fontFamily
  readonly property string serif: svc.fontFamily

  // tone -> color; `fail` is failed only, `needsYou` is waiting only
  function toneColor(tone) {
    if (tone === "ember") return ember;
    if (tone === "needsYou") return warn;
    if (tone === "fail") return err;
    if (tone === "ok") return ok;
    return sub;
  }
  function statusBlurb(s) {
    if (s === "listening") return "Recording. Release the key to send.";
    if (s === "transcribing") return "Turning your speech into text.";
    if (s === "deciding") return "Thinking about what to do.";
    if (s === "acting") return "Running a tool or agent.";
    if (s === "awaiting_choice") return "Waiting for you to pick an option.";
    if (s === "speaking") return "Speaking the answer.";
    if (s === "done") return "The last turn just finished.";
    if (s === "idle")
      return "Ready. Hold " +
          (svc.configValues["hotkey.mod"] || "SUPER") + "+" +
          (svc.configValues["hotkey.key"] || "D") + " to talk.";
    if (s === "error") return "Something failed. See Activity.";
    if (s === "offline") return "The daemon is not running. Restart it below.";
    return svc.statusWord;
  }

  // small mono section label
  component Sect: Text {
    property string label: ""
    text: label
    color: faint; font.pixelSize: 10; font.family: mono
    font.letterSpacing: 1.4
  }

  component Hairline: Rectangle {
    width: parent.width; height: 1; color: hairline
  }

  component Btn: Rectangle {
    property string label: ""
    property bool primary: false
    signal clicked()
    implicitWidth: lbl.implicitWidth + 26; implicitHeight: 30
    radius: 6
    color: primary ? (ma.containsMouse ? Qt.lighter(accent, 1.15)
                                          : accent)
                   : (ma.containsMouse ? raised : "transparent")
    border.color: primary ? "transparent" : hairline
    Text { id: lbl; anchors.centerIn: parent; text: parent.label
           color: parent.primary ? bg : sub
           font.pixelSize: 12
           font.bold: parent.primary }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true
                onClicked: parent.clicked() }
  }

  RowLayout {
    anchors.fill: parent
    spacing: 0

    // ── sidebar ──
    Item {
      Layout.fillHeight: true
      width: 148
      Column {
        anchors { left: parent.left; right: parent.right; top: parent.top
                  margins: 18 }
        spacing: 2
        Row {
          spacing: 8
          bottomPadding: 18
          Rectangle {
            width: 8; height: 8; radius: 4
            anchors.verticalCenter: parent.verticalCenter
            color: win.toneColor(svc.statusTone)
            SequentialAnimation on opacity {
              running: svc.busy && svc.motionMode !== "off"
              loops: Animation.Infinite
              NumberAnimation { to: 0.3; duration: 800 }
              NumberAnimation { to: 1.0; duration: 800 }
            }
          }
          Text { text: "Wisp"; color: fg; font.pixelSize: 15
                 font.family: serif; font.bold: true }
        }
        Repeater {
          model: win.tabs
          Item {
            width: parent.width; height: 30
            Rectangle {
              visible: win.tab === index
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              width: 2; height: 16; color: accent
            }
            Text {
              anchors { verticalCenter: parent.verticalCenter
                        left: parent.left; leftMargin: 12 }
              text: svc.ui("ui.manage." + modelData)
              color: win.tab === index ? fg : faint
              font.pixelSize: 13
              Behavior on color { ColorAnimation { duration: 120 } }
            }
            MouseArea { anchors.fill: parent
                        hoverEnabled: true
                        onClicked: win.tab = index }
          }
        }
      }
    }

    Rectangle { Layout.fillHeight: true; width: 1; color: hairline }

    // ── content ──
    StackLayout {
      Layout.fillWidth: true
      Layout.fillHeight: true
      currentIndex: win.tab

      // ════ HOME ════
      Flickable {
        contentWidth: width
        contentHeight: homeCol.implicitHeight + 48
        clip: true; boundsBehavior: Flickable.StopAtBounds
        Column {
          id: homeCol
          x: 32; y: 32
          width: parent.parent.width - 64
          spacing: 18

          // status: the hero, plain type
          Text {
            text: svc.statusWord
            color: win.toneColor(svc.statusTone)
            font.pixelSize: 34; font.family: mono; font.bold: true
            font.letterSpacing: -0.5
          }
          Text {
            visible: svc.notice !== ""
            text: svc.notice
            color: warn; font.pixelSize: 12; font.family: mono
          }
          Text {
            text: win.statusBlurb(svc.status)
            color: sub; font.pixelSize: 13
          }

          Hairline {}

          Sect { label: "LAST TURN" }
          Text {
            visible: svc.transcript.length > 0
            text: "“" + svc.transcript + "”"
            color: fg; font.pixelSize: 16; font.family: serif
            width: parent.width; wrapMode: Text.WordWrap
          }
          Text {
            visible: (svc.answer || svc.resultView.text).length > 0
            text: svc.answer || svc.resultView.text
            color: sub; font.pixelSize: 14
            width: parent.width; wrapMode: Text.WordWrap
            lineHeight: 1.35
          }
          Text {
            visible: (svc.errorMessage || svc.error).length > 0
            text: svc.errorMessage || svc.error
            color: err; font.pixelSize: 12; font.family: mono
            width: parent.width; wrapMode: Text.WordWrap
          }

          Row {
            spacing: 8; topPadding: 6
            Btn { label: "Talk"; primary: true
                  onClicked: svc.trigger() }
            Btn { label: "Restart daemon"
                  onClicked: win.svc(["restart"]) }
            Btn { label: "Stop"
                  onClicked: win.svc(["stop"]) }
          }

          Text {
            topPadding: 8
            width: parent.width
            wrapMode: Text.WordWrap
            color: faint; font.pixelSize: 11; lineHeight: 1.4
            text: "This is the control room, not the assistant. Wisp " +
                  "lives as the orb bottom-right and on SUPER+D. " +
                  "Closing this window keeps it running."
          }
        }
      }

      // ════ ACTIVITY ════
      Flickable {
        contentWidth: width
        contentHeight: actCol.implicitHeight + 48
        clip: true; boundsBehavior: Flickable.StopAtBounds
        Column {
          id: actCol
          x: 32; y: 28
          width: parent.parent.width - 64
          spacing: 0

          Column {
            visible: win.suggestions.length > 0
            width: parent.width; spacing: 4
            bottomPadding: 14
            Sect { label: "SUGGESTIONS" }
            Repeater {
              model: win.suggestions
              Column {
                width: actCol.width; spacing: 2
                Text {
                  text: modelData.title || ""
                  color: warn; font.pixelSize: 13; font.bold: true
                  width: parent.width; elide: Text.ElideRight }
                Text {
                  visible: (modelData.evidence || "").length > 0
                  text: modelData.evidence || ""
                  color: sub; font.pixelSize: 11
                  width: parent.width; elide: Text.ElideRight }
                Row {
                  spacing: 8; topPadding: 2
                  Btn { label: "automate"
                        onClicked: svc.sendChoice(
                          "suggestion:automate:" + modelData.key) }
                  Btn { label: "not now"
                        onClicked: svc.sendChoice(
                          "suggestion:not now:" + modelData.key) }
                  Btn { label: "never"
                        onClicked: svc.sendChoice(
                          "suggestion:never:" + modelData.key) }
                }
              }
            }
            Hairline {}
          }

          Row {
            bottomPadding: 14
            spacing: 12
            Sect { label: "TURN LOG"; anchors.verticalCenter:
                   parent.verticalCenter }
            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "what it heard, decided and did, with timings per stage"
              color: faint; font.pixelSize: 11 }
          }

          Repeater {
            model: win.decisions
            Column {
              width: actCol.width
              Rectangle { width: parent.width; height: 1
                          color: hairline }
              Item { width: 1; height: 10 }
              Row {
                width: parent.width; spacing: 12
                Text {
                  text: (modelData.ts || "").slice(11, 19)
                  color: faint; font.pixelSize: 11; font.family: mono
                  anchors.verticalCenter: parent.verticalCenter }
                Text {
                  text: ((modelData.answers || {}).route || {})
                        .choice || "?"
                  color: accent; font.pixelSize: 11; font.family: mono
                  anchors.verticalCenter: parent.verticalCenter }
                Text {
                  property int tms:
                      ((modelData.timing_ms || {}).act_ms || 0)
                  visible: tms > 0
                  text: tms + "ms"
                  color: faint; font.pixelSize: 10; font.family: mono
                  anchors.verticalCenter: parent.verticalCenter }
              }
              Text {
                visible: (modelData.transcript || "").length > 0
                text: "you   " + (modelData.transcript || "")
                color: fg; font.pixelSize: 13
                width: parent.width; wrapMode: Text.WordWrap }
              Text {
                visible: (modelData.reply || modelData.result
                          || "").length > 0
                text: "wisp  " + (modelData.reply ||
                                  modelData.result || "")
                color: sub; font.pixelSize: 13
                width: parent.width; wrapMode: Text.WordWrap }
              Item { width: 1; height: 10 }
            }
          }

          Text {
            visible: win.decisions.length === 0
            topPadding: 8
            text: "Nothing yet: hold SUPER+D and talk."
            color: faint; font.pixelSize: 13 }

          Column {
            visible: win.corrections.length > 0
            width: parent.width; spacing: 4; topPadding: 16
            Sect { label: "LEARNED CORRECTIONS" }
            Repeater {
              model: win.corrections
              Text { text: modelData
                     color: sub; font.pixelSize: 11; font.family: mono
                     width: parent.width; elide: Text.ElideRight }
            }
          }
        }
      }

      // ════ MEMORY ════
      Flickable {
        contentWidth: width
        contentHeight: memCol.implicitHeight + 48
        clip: true; boundsBehavior: Flickable.StopAtBounds
        Column {
          id: memCol
          x: 32; y: 28
          width: parent.parent.width - 64
          spacing: 14

          Row {
            spacing: 12; bottomPadding: 4
            Sect { label: "MEMORY"; anchors.verticalCenter:
                   parent.verticalCenter }
            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "read at the start of every turn"
              color: faint; font.pixelSize: 11 }
          }

          Repeater {
            model: [["memory", "MEMORY.md", "facts it learned",
                     memoryView],
                    ["user",   "USER.md",   "how it should behave",
                     userView]]
            Column {
              width: memCol.width; spacing: 8
              Row {
                width: parent.width; spacing: 10
                Column {
                  width: parent.width - 80; spacing: 1
                  Text { text: modelData[1]; color: fg
                         font.pixelSize: 12; font.family: mono;
                         font.bold: true }
                  Text { text: modelData[2]; color: faint
                         font.pixelSize: 11 }
                }
                Btn {
                  label: "Save"
                  onClicked: {
                    writeProc.command =
                        [svc.wispd, "memory", "write", modelData[0],
                         Qt.btoa(edit.text)];
                    writeProc.running = true;
                  }
                }
              }
              Rectangle {
                width: parent.width; height: 180; radius: 6
                color: raised; border.color: hairline
                Flickable {
                  anchors { fill: parent; margins: 10 }
                  contentWidth: width; contentHeight: edit.height
                  clip: true
                  TextEdit {
                    id: edit
                    width: parent.width
                    color: sub; font.pixelSize: 12
                    font.family: mono
                    wrapMode: TextEdit.Wrap
                    text: modelData[3].text()
                  }
                }
              }
            }
          }
        }
      }

      // ════ AGENTS ════
      Item {
        Column {
          anchors { fill: parent; margins: 32 }
          spacing: 16

          Row {
            spacing: 12
            Sect { label: "BACKGROUND AGENTS"; anchors.verticalCenter:
                   parent.verticalCenter }
            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "long-running tasks: they work while you do"
              color: faint; font.pixelSize: 11 }
          }

          Row {
            width: parent.width; spacing: 8
            Rectangle {
              width: parent.width - 84; height: 34; radius: 6
              color: raised; border.color: hairline
              TextInput {
                id: taskInput
                anchors { fill: parent; margins: 9 }
                color: fg; font.pixelSize: 13; clip: true
                Text {
                  anchors { left: parent.left; right: parent.right
                            verticalCenter: parent.verticalCenter }
                  visible: !taskInput.text
                  text: "describe a task…"
                  color: faint; font.pixelSize: 13 }
              }
            }
            Btn {
              label: "Spawn"; primary: true
              onClicked: {
                if (taskInput.text.trim().length === 0) return;
                win.wispd(["task", "run", taskInput.text.trim()]);
                taskInput.text = "";
              }
            }
          }

          Flickable {
            width: parent.width
            height: parent.height - y
            contentWidth: width
            contentHeight: taskCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
              id: taskCol
              width: parent.width; spacing: 0
              Repeater {
                model: Object.keys(svc.tasks)
                Column {
                  width: taskCol.width
                  property var t: win.taskOf(modelData)
                  Rectangle { width: parent.width; height: 1
                              color: hairline }
                  Row {
                    width: parent.width; spacing: 12
                    topPadding: 10; bottomPadding: 10
                    Rectangle {
                      width: 8; height: 8; radius: 4
                      anchors.verticalCenter: parent.verticalCenter
                      color: parent.parent.t.status === "running"
                             ? ok
                           : parent.parent.t.status === "failed"
                             ? err : faint
                    }
                    Column {
                      width: parent.width - 120; spacing: 1
                      anchors.verticalCenter: parent.verticalCenter
                      Text {
                        text: modelData
                        color: fg; font.pixelSize: 12
                        font.family: mono
                        elide: Text.ElideMiddle
                        width: parent.width }
                      Text {
                        text: parent.parent.t.status + " · " +
                              (parent.parent.t.task || "")
                        color: faint; font.pixelSize: 11
                        elide: Text.ElideRight
                        width: parent.width }
                    }
                    Btn {
                      visible: parent.parent.t.status === "running"
                      label: "Cancel"
                      onClicked: win.wispd(["task", "cancel", modelData])
                    }
                  }
                }
              }
              Text {
                visible: Object.keys(svc.tasks).length === 0
                topPadding: 8
                text: "No agents running. Say \"agent, …\" or spawn one."
                color: faint; font.pixelSize: 13 }
            }
          }
        }
      }

      // ════ HEALTH ════
      Flickable {
        contentWidth: width
        contentHeight: healthView.implicitHeight + 56
        clip: true; boundsBehavior: Flickable.StopAtBounds
        HealthView {
          id: healthView
          x: 32; y: 28
          width: parent.width - 64
          service: svc
          cua: svc.cuaStatus
          spendModels: svc.spendModels
        }
      }

      // ════ SPEND ════
      Flickable {
        contentWidth: width
        contentHeight: spendView.implicitHeight + 56
        clip: true; boundsBehavior: Flickable.StopAtBounds
        SpendView {
          id: spendView
          x: 32; y: 28
          width: parent.width - 64
          service: svc
          models: svc.spendModels
        }
      }

      // ════ AUDIT ════
      Flickable {
        contentWidth: width
        contentHeight: auditViewList.implicitHeight + 56
        clip: true; boundsBehavior: Flickable.StopAtBounds
        AuditView {
          id: auditViewList
          x: 32; y: 28
          width: parent.width - 64
          service: svc
          log: win.auditText
        }
      }

      // ════ BINDS ════
      Flickable {
        contentWidth: width
        contentHeight: bindsView.implicitHeight + 56
        clip: true; boundsBehavior: Flickable.StopAtBounds
        BindsView {
          id: bindsView
          x: 32; y: 28
          width: parent.width - 64
          service: svc
          binds: win.bindsData
        }
      }

      // ════ SETTINGS ════
      Flickable {
        contentWidth: width
        contentHeight: setCol.implicitHeight + 48
        clip: true; boundsBehavior: Flickable.StopAtBounds
        Column {
          id: setCol
          x: 32; y: 28
          width: parent.parent.width - 64
          spacing: 16

          Row {
            spacing: 12; bottomPadding: 2
            Sect { label: "SETTINGS"; anchors.verticalCenter:
                   parent.verticalCenter }
            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "config.toml: changes apply next turn. A rejected value shows a red border and nothing is written."
              color: faint; font.pixelSize: 11 }
          }

          Repeater {
            model: [
              ["Talking to it",
               "hotkey.mod / hotkey.key: the hold-to-talk chord. " +
               "audio.seconds: max record length, a safety cap not " +
               "the limit (release the key to stop).",
               [["hotkey.mod","hotkey mod"],
                ["hotkey.key","hotkey key"],
                ["audio.seconds","max record secs"]]],
              ["Hearing",
               "stt.provider: local = whisper.cpp offline; openai = " +
               "any /audio/transcriptions endpoint (Groq, OpenAI…): " +
               "audio leaves the machine. stt.prompt primes jargon.",
               [["stt.provider","provider"],
                ["stt.base_url","base_url"],
                ["stt.model","model"],
                ["stt.prompt","vocab prompt"]]],
              ["Brain",
               "brain.router: jev routes via typed decisions; chat " +
               "sends transcript straight to the answer model; off " +
               "always asks. brain.default: provider:model for " +
               "answers. agent_runtime: opencode/codex/claude/devin.",
               [["brain.router","router"],
                ["brain.default","answer provider"],
                ["brain.agent_runtime","agent runtime"],
                ["agent.model","jev model"],
                ["agent.answer_model","answer model"],
                ["agent.screenshots","screenshots"]]],
              ["Actions & safety",
               "risk_threshold: auto-run when Jev's risk score is at " +
               "or below it; higher scores ask first. allow_shell " +
               "lets the act loop run shell commands (denylisted " +
               "patterns still refuse).",
               [["agent.risk_threshold","risk threshold"],
                ["agent.allow_shell","allow shell"],
                ["agent.confidence_instant","instant conf"],
                ["agent.confidence_ambiguous","ambiguous conf"]]],
              ["Memory & recall",
               "recall.provider: none = FTS5 keyword search only " +
               "(zero keys); openai = semantic embeddings via any " +
               "OpenAI-compatible endpoint.",
               [["recall.provider","provider"],
                ["recall.model","embed model"],
                ["recall.base_url","base_url"],
                ["agent.session_turns","context turns"]]],
              ["Debugging & voice",
               "debug.trace: full per-turn event log to " +
               "trace.jsonl. voice.enabled: spoken replies via " +
               "espeak; voice.cmd for a custom TTS like piper.",
               [["debug.trace","trace"],
                ["voice.enabled","voice"],
                ["voice.cmd","tts cmd"]]]
            ]
            Column {
              width: setCol.width; spacing: 6
              Rectangle { width: parent.width; height: 1
                          color: hairline }
              Item { width: 1; height: 4 }
              Text { text: modelData[0]; color: fg
                     font.pixelSize: 13; font.bold: true }
              Text {
                text: modelData[1]
                color: faint; font.pixelSize: 11; lineHeight: 1.35
                width: parent.width; wrapMode: Text.WordWrap }
              Grid {
                columns: 2
                columnSpacing: 24; rowSpacing: 4
                width: parent.width
                Repeater {
                  model: modelData[2]
                  Row {
                    spacing: 8
                    width: (setCol.width - 24) / 2
                    property string k: modelData[0]
                    Text {
                      text: modelData[1]
                      color: sub; font.pixelSize: 11
                      anchors.verticalCenter: parent.verticalCenter
                      width: 130 }
                    Rectangle {
                      width: parent.width - 138; height: 24; radius: 4
                      color: hov.hovered || valEdit.activeFocus
                             ? raised : "transparent"
                      border.color: svc.configErrors[parent.k] !== undefined ? err
                                    : valEdit.activeFocus ? accent
                                                          : hairline
                      HoverHandler { id: hov }
                      TextInput {
                        id: valEdit
                        anchors { fill: parent; leftMargin: 7
                                  rightMargin: 7 }
                        verticalAlignment: TextInput.AlignVCenter
                        clip: true
                        selectByMouse: true
                        color: fg; font.pixelSize: 11; font.family: mono
                        text: {
                          var v = svc.configValues[parent.parent.k];
                          return (v === undefined || v === null)
                                 ? "" : String(v);
                        }
                        onEditingFinished:
                          svc.configSet(parent.parent.k, text)
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
