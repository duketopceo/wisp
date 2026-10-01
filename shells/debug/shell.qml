import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

// Wisp — management app. Open/close from the launcher; the daemon stays
// resident. Tabs: Home (what it's doing + controls), Activity (turn
// replay), Memory (editable notes it reads every turn), Agents
// (background tasks), Settings (config.toml, grouped + explained).
// Everything reads files/IPC — zero coupling to daemon internals.

FloatingWindow {
  id: win
  title: "Wisp"
  minimumSize: Qt.size(900, 640)
  color: "#16161e"

  readonly property string rtDir: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    if (!rd || rd.length === 0) rd = "/tmp";
    return rd + "/wisp";
  }
  readonly property string dataDir:
      Quickshell.env("HOME") + "/.local/share/wisp"

  property var stateObj: ({})
  property var decisions: []
  property var corrections: []
  property var suggestions: []
  property var cfgObj: ({})
  property var tasks: ({})
  property int tab: 0

  function wispd(args) {
    if (cmdProc.running) return;
    cmdProc.command = ["wispd"].concat(args);
    cmdProc.running = true;
  }
  function svc(args) {
    if (svcProc.running) return;
    svcProc.command =
        ["systemctl", "--user"].concat(args).concat(["wispd"]);
    svcProc.running = true;
  }

  // ── data plumbing ──────────────────────────────────────────────

  FileView {
    id: stateView
    path: win.rtDir + "/state.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try {
        var s = JSON.parse(stateView.text());
        win.stateObj = s;
        win.tasks = s.tasks || {};  // state publishes task liveness
      } catch (e) {}
    }
  }
  Timer { interval: 400; running: true; repeat: true
          onTriggered: stateView.reload() }

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
      // latest record per key wins — the file appends status updates
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

  Process {
    id: cfgProc
    command: ["wispd", "config"]
    stdout: StdioCollector {
      onStreamFinished: {
        try { win.cfgObj = JSON.parse(this.text) } catch (e) {}
      }
    }
  }
  Process { id: cmdProc; command: ["wispd"]
            onExited: { cfgProc.running = true } }
  Process { id: svcProc
            command: ["systemctl", "--user", "status", "wispd"] }
  Process { id: writeProc; command: ["wispd"] }

  Component.onCompleted: {
    cfgProc.running = true;
  }

  // ── design tokens ──────────────────────────────────────────────
  // Tokyo Night, flattened: fewer boxes, hairline separators, mono
  // for labels + data, sans for prose.

  readonly property color bg: "#16161e"
  readonly property color raised: "#1f202e"
  readonly property color hairline: "#2a2c3f"
  readonly property color fg: "#e0e4f0"
  readonly property color sub: "#9aa5ce"
  readonly property color faint: "#565f89"
  readonly property color accent: "#7aa2f7"
  readonly property color ok: "#9ece6a"
  readonly property color warn: "#e0af68"
  readonly property color err: "#f7768e"

  readonly property string mono: "JetBrainsMono NF"
  readonly property string serif: "iA Writer Mono S"

  function statusColor(s) {
    if (s === "listening") return accent;
    if (["transcribing","deciding"].indexOf(s) >= 0) return "#bb9af7";
    if (["acting","awaiting_choice"].indexOf(s) >= 0) return ok;
    if (s === "speaking") return warn;
    if (s === "error" || s === "offline") return err;
    return faint;
  }
  function statusBlurb(s) {
    if (s === "listening") return "Recording — release the key to send";
    if (s === "transcribing") return "Turning your speech into text";
    if (s === "deciding") return "Thinking — picking what to do";
    if (s === "acting") return "Running a tool or agent";
    if (s === "awaiting_choice") return "Waiting for you to pick an option";
    if (s === "speaking") return "Speaking the answer";
    if (s === "done") return "Done — last turn just finished";
    if (s === "idle")
      return "Idle — hold " +
          ((win.cfgObj.hotkey||{}).mod||"SUPER") + "+" +
          ((win.cfgObj.hotkey||{}).key||"D") + " to talk";
    if (s === "error") return "Something failed — see Activity";
    if (s === "offline") return "Daemon not running — restart it below";
    return s || "offline";
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
    color: primary ? (ma.containsMouse ? "#8fb0ff" : accent)
                   : (ma.containsMouse ? "#262839" : "transparent")
    border.color: primary ? "transparent" : hairline
    Text { id: lbl; anchors.centerIn: parent; text: parent.label
           color: parent.primary ? "#16161e" : sub
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
            color: win.statusColor(win.stateObj.status || "offline")
            SequentialAnimation on opacity {
              running: ["listening","transcribing","deciding",
                        "acting"].indexOf(win.stateObj.status || "") >= 0
              loops: Animation.Infinite
              NumberAnimation { to: 0.3; duration: 800 }
              NumberAnimation { to: 1.0; duration: 800 }
            }
          }
          Text { text: "Wisp"; color: fg; font.pixelSize: 15
                 font.family: serif; font.bold: true }
        }
        Repeater {
          model: ["Home", "Activity", "Memory", "Agents", "Settings"]
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
              text: modelData
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

          // status — the hero, plain type
          Text {
            text: win.stateObj.status || "offline"
            color: win.statusColor(win.stateObj.status || "offline")
            font.pixelSize: 34; font.family: mono; font.bold: true
            font.letterSpacing: -0.5
          }
          Text {
            text: win.statusBlurb(win.stateObj.status || "offline")
            color: sub; font.pixelSize: 13
          }

          Hairline {}

          Sect { label: "LAST TURN" }
          Text {
            visible: (win.stateObj.transcript || "").length > 0
            text: "“" + (win.stateObj.transcript || "") + "”"
            color: fg; font.pixelSize: 16; font.family: serif
            width: parent.width; wrapMode: Text.WordWrap
          }
          Text {
            visible: (win.stateObj.answer || win.stateObj.result
                      || "").length > 0
            text: win.stateObj.answer || win.stateObj.result || ""
            color: sub; font.pixelSize: 14
            width: parent.width; wrapMode: Text.WordWrap
            lineHeight: 1.35
          }
          Text {
            visible: (win.stateObj.error || "").length > 0
            text: "error — " + (win.stateObj.error || "")
            color: err; font.pixelSize: 12; font.family: mono
            width: parent.width; wrapMode: Text.WordWrap
          }

          Row {
            spacing: 8; topPadding: 6
            Btn { label: "Talk"; primary: true
                  onClicked: win.wispd(["trigger"]) }
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
                  text: "✦ " + (modelData.title || "")
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
                        onClicked: win.wispd(["choice",
                          "suggestion:automate:" + modelData.key]) }
                  Btn { label: "not now"
                        onClicked: win.wispd(["choice",
                          "suggestion:not now:" + modelData.key]) }
                  Btn { label: "never"
                        onClicked: win.wispd(["choice",
                          "suggestion:never:" + modelData.key]) }
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
              text: "what it heard, decided, did — per stage timings"
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
            text: "Nothing yet — hold SUPER+D and talk."
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
                        ["wispd", "memory-write", modelData[0],
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
              text: "long-running tasks — they work while you do"
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
                win.wispd(["agent", taskInput.text.trim()]);
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
                model: Object.keys(win.tasks)
                Column {
                  width: taskCol.width
                  property var t: win.tasks[modelData] || {}
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
                      onClicked: win.wispd(["task_cancel", modelData])
                    }
                  }
                }
              }
              Text {
                visible: Object.keys(win.tasks).length === 0
                topPadding: 8
                text: "No agents running. Say \"agent, …\" or spawn one."
                color: faint; font.pixelSize: 13 }
            }
          }
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
              text: "config.toml — changes apply next turn"
              color: faint; font.pixelSize: 11 }
          }

          Repeater {
            model: [
              ["Talking to it",
               "hotkey.mod / hotkey.key — the hold-to-talk chord. " +
               "audio.seconds — max record length, a safety cap not " +
               "the limit (release the key to stop).",
               [["hotkey.mod","hotkey mod"],
                ["hotkey.key","hotkey key"],
                ["audio.seconds","max record secs"]]],
              ["Hearing",
               "stt.provider — local = whisper.cpp offline; openai = " +
               "any /audio/transcriptions endpoint (Groq, OpenAI…) — " +
               "audio leaves the machine. stt.prompt primes jargon.",
               [["stt.provider","provider"],
                ["stt.base_url","base_url"],
                ["stt.model","model"],
                ["stt.prompt","vocab prompt"]]],
              ["Brain",
               "brain.router — jev routes via typed decisions; chat " +
               "sends transcript straight to the answer model; off " +
               "always asks. brain.default — provider:model for " +
               "answers. agent_runtime — opencode/codex/claude/devin.",
               [["brain.router","router"],
                ["brain.default","answer provider"],
                ["brain.agent_runtime","agent runtime"],
                ["agent.model","jev model"],
                ["agent.answer_model","answer model"],
                ["agent.screenshots","screenshots"]]],
              ["Actions & safety",
               "risk_threshold — auto-run when Jev's risk score is at " +
               "or below it; higher scores ask first. allow_shell " +
               "lets the act loop run shell commands (denylisted " +
               "patterns still refuse).",
               [["agent.risk_threshold","risk threshold"],
                ["agent.allow_shell","allow shell"],
                ["agent.confidence_instant","instant conf"],
                ["agent.confidence_ambiguous","ambiguous conf"]]],
              ["Memory & recall",
               "recall.provider — none = FTS5 keyword search only " +
               "(zero keys); openai = semantic embeddings via any " +
               "OpenAI-compatible endpoint.",
               [["recall.provider","provider"],
                ["recall.model","embed model"],
                ["recall.base_url","base_url"],
                ["agent.session_turns","context turns"]]],
              ["Debugging & voice",
               "debug.trace — full per-turn event log to " +
               "trace.jsonl. voice.enabled — spoken replies via " +
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
                      border.color: valEdit.activeFocus ? accent
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
                          var parts = parent.parent.k.split(".");
                          var v = win.cfgObj;
                          for (var i = 0; i < parts.length && v; i++)
                            v = v[parts[i]];
                          return (v === undefined || v === null)
                                 ? "" : String(v);
                        }
                        onEditingFinished: {
                          win.wispd(["config", "set",
                                     parent.parent.k, text]);
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
}
