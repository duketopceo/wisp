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
  minimumSize: Qt.size(900, 660)
  color: "#1a1b26"

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
      try { win.stateObj = JSON.parse(stateView.text()) } catch (e) {}
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
      for (var i = lines.length - 1; i >= 0 && out.length < 20; i--) {
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
  Process {
    id: tasksProc
    command: ["wispd", "task_status"]
    stdout: StdioCollector {
      onStreamFinished: {
        try { win.tasks = JSON.parse(this.text).tasks || {} }
        catch (e) {}
      }
    }
  }
  Process { id: cmdProc; command: ["wispd"]
            onExited: { cfgProc.running = true; tasksProc.running = true } }
  Process { id: svcProc
            command: ["systemctl", "--user", "status", "wispd"] }
  Process { id: writeProc; command: ["wispd"] }

  Component.onCompleted: {
    cfgProc.running = true; tasksProc.running = true;
  }
  Timer { interval: 3000; running: win.tab === 3; repeat: true
          onTriggered: tasksProc.running = true }

  // ── palette ────────────────────────────────────────────────────
  // Tokyo-Night-ish, matched to the Omarchy bar. Text contrast is
  // deliberate: fg for content, sub for secondary, faint only for
  // hints — never for body text.

  readonly property color bg: "#1a1b26"
  readonly property color card: "#23243380"
  readonly property color cardSolid: "#232433"
  readonly property color border: "#2f334d"
  readonly property color fg: "#e0e4f0"
  readonly property color sub: "#a9b1d6"
  readonly property color faint: "#6a6f92"
  readonly property color accent: "#7aa2f7"
  readonly property color ok: "#9ece6a"
  readonly property color warn: "#e0af68"
  readonly property color err: "#f7768e"

  function statusColor(s) {
    if (s === "listening") return accent;
    if (["transcribing","deciding"].indexOf(s) >= 0) return "#bb9af7";
    if (["acting","awaiting_choice"].indexOf(s) >= 0) return ok;
    if (s === "speaking") return warn;
    if (s === "error" || s === "offline") return err;
    return faint;
  }
  function statusBlurb(s) {
    if (s === "listening")
      return "Listening — recording you right now";
    if (s === "transcribing") return "Turning your speech into text";
    if (s === "deciding") return "Thinking — picking what to do";
    if (s === "acting") return "Running a tool or agent on your desktop";
    if (s === "awaiting_choice") return "Waiting for you to pick an option";
    if (s === "speaking") return "Speaking the answer out loud";
    if (s === "done") return "Idle — last turn just finished";
    if (s === "idle")
      return "Idle — press " +
          ((win.cfgObj.hotkey||{}).mod||"SUPER") + "+" +
          ((win.cfgObj.hotkey||{}).key||"D") + " to talk";
    if (s === "error") return "Something failed — check Activity";
    if (s === "offline")
      return "Daemon isn't running — hit Restart below";
    return s || "offline";
  }

  // reusable card
  component Card: Rectangle {
    property alias contentCol: inner
    default property alias kids: inner.data
    color: cardSolid; radius: 10
    border.color: border; border.width: 1
    implicitHeight: inner.implicitHeight + 24
    Column {
      id: inner
      anchors { left: parent.left; right: parent.right
                top: parent.top; margins: 12 }
      spacing: 8
    }
  }

  component Ghost: Rectangle {   // secondary button
    property string label: ""
    signal clicked()
    implicitWidth: lbl.implicitWidth + 28; implicitHeight: 32
    radius: 8; color: ma.containsMouse ? "#2f334d" : "transparent"
    border.color: border
    Text { id: lbl; anchors.centerIn: parent; text: parent.label
           color: sub; font.pixelSize: 12 }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true
                onClicked: parent.clicked() }
  }

  component Solid: Rectangle {   // primary button
    property string label: ""
    signal clicked()
    implicitWidth: lbl.implicitWidth + 28; implicitHeight: 32
    radius: 8; color: ma.containsMouse ? "#8fb0ff" : accent
    Text { id: lbl; anchors.centerIn: parent; text: parent.label
           color: "#1a1b26"; font.pixelSize: 12; font.bold: true }
    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true
                onClicked: parent.clicked() }
  }

  RowLayout {
    anchors.fill: parent
    spacing: 0

    // ── sidebar ──
    Rectangle {
      Layout.fillHeight: true
      width: 160
      color: "#14151e"
      Column {
        anchors { left: parent.left; right: parent.right; top: parent.top
                  margins: 14 }
        spacing: 4
        Text { text: "Wisp"; color: fg; font.pixelSize: 18
               font.bold: true; bottomPadding: 10 }
        Repeater {
          model: ["Home", "Activity", "Memory", "Agents", "Settings"]
          Rectangle {
            width: parent.width; height: 36; radius: 8
            color: win.tab === index ? "#2a2e45" : "transparent"
            Text { anchors { verticalCenter: parent.verticalCenter
                             left: parent.left; leftMargin: 12 }
                   text: modelData
                   color: win.tab === index ? fg : sub
                   font.pixelSize: 13 }
            MouseArea { anchors.fill: parent
                        onClicked: win.tab = index }
          }
        }
      }
    }

    // ── content ──
    StackLayout {
      Layout.fillWidth: true
      Layout.fillHeight: true
      currentIndex: win.tab

      // ════ HOME ════
      Item {
        Column {
          anchors { fill: parent; margins: 24 }
          spacing: 20

          // hero status
          Row {
            spacing: 18
            Rectangle {
              width: 52; height: 52; radius: 26
              color: win.statusColor(win.stateObj.status || "offline")
              Rectangle {
                visible: win.stateObj.status === "listening"
                anchors.centerIn: parent
                width: 52; height: 52; radius: 26
                color: "transparent"
                border.color: accent; border.width: 3
                opacity: 0.3 + (win.stateObj.level || 0) * 0.7
                Behavior on opacity { NumberAnimation { duration: 120 } }
              }
            }
            Column {
              anchors.verticalCenter: parent.verticalCenter
              spacing: 2
              Text { text: win.stateObj.status || "offline"
                     color: fg; font.pixelSize: 24; font.bold: true }
              Text { text: win.statusBlurb(win.stateObj.status || "offline")
                     color: sub; font.pixelSize: 13 }
            }
          }

          Card {
            width: parent.width
            Column {
              spacing: 10
              Text { text: "LAST THING IT HEARD"; color: faint
                     font.pixelSize: 10; font.letterSpacing: 1 }
              Text {
                text: win.stateObj.transcript || "—"
                color: fg; font.pixelSize: 15
                width: parent.width; wrapMode: Text.WordWrap }
              Rectangle { width: parent.width; height: 1; color: border }
              Text { text: "WHAT IT DID / SAID"; color: faint
                     font.pixelSize: 10; font.letterSpacing: 1 }
              Text {
                text: win.stateObj.answer || win.stateObj.result || "—"
                color: sub; font.pixelSize: 14
                width: parent.width; wrapMode: Text.WordWrap }
              Text {
                visible: (win.stateObj.error || "").length > 0
                text: "Error: " + (win.stateObj.error || "")
                color: err; font.pixelSize: 12
                width: parent.width; wrapMode: Text.WordWrap }
            }
          }

          Row {
            spacing: 10
            Solid { label: "Talk to it"
                    onClicked: win.wispd(["trigger"]) }
            Ghost { label: "Restart daemon"
                    onClicked: win.svc(["restart"]) }
            Ghost { label: "Stop daemon"
                    onClicked: win.svc(["stop"]) }
          }

          Text {
            width: parent.width
            wrapMode: Text.WordWrap
            color: faint; font.pixelSize: 12; lineHeight: 1.4
            text: "This window is the control room, not the assistant. " +
                  "Wisp lives as the orb in your bar and answers on " +
                  "SUPER+D anywhere. Close this — it keeps running."
          }
        }
      }

      // ════ ACTIVITY ════
      Item {
        Flickable {
          anchors { fill: parent }
          contentWidth: width
          contentHeight: actCol.implicitHeight + 32
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: actCol
            x: 20; y: 16
            width: parent.parent.width - 40
            spacing: 12

            Text {
              width: parent.width; wrapMode: Text.WordWrap
              color: sub; font.pixelSize: 12; lineHeight: 1.4
              text: "Every turn, replayed: what it heard, what it " +
                    "decided, how long each stage took. When Wisp does " +
                    "something weird, this is the evidence."
            }

            Repeater {
              model: win.decisions
              Card {
                width: actCol.width
                Column {
                  spacing: 8
                  Row {
                    spacing: 10
                    Text { text: modelData.turn || ""
                           color: accent; font.pixelSize: 12
                           font.bold: true }
                    Text { text: modelData.route || "?"
                           color: faint; font.pixelSize: 11 }
                    Text {
                      visible: (modelData.ms_total || 0) > 0
                      text: (modelData.ms_total || 0) + " ms"
                      color: faint; font.pixelSize: 11 }
                  }
                  Text {
                    visible: (modelData.transcript || "").length > 0
                    text: "you:  " + (modelData.transcript || "")
                    color: fg; font.pixelSize: 13
                    width: parent.width; wrapMode: Text.WordWrap }
                  Text {
                    visible: (modelData.reply || modelData.result
                              || "").length > 0
                    text: "wisp: " + (modelData.reply ||
                                      modelData.result || "")
                    color: sub; font.pixelSize: 13
                    width: parent.width; wrapMode: Text.WordWrap }
                  Flow {
                    width: parent.width; spacing: 6
                    Repeater {
                      model: modelData.stages || []
                      Rectangle {
                        width: stTxt.implicitWidth + 12; height: 18
                        radius: 4; color: "#1a1b26"
                        Text { id: stTxt; anchors.centerIn: parent
                               text: modelData[0] + " " +
                                     (modelData[1]||0) + "ms"
                               color: faint; font.pixelSize: 10 }
                      }
                    }
                  }
                }
              }
            }

            Text {
              visible: win.decisions.length === 0
              text: "Nothing yet — press SUPER+D and talk."
              color: faint; font.pixelSize: 13 }

            Column {
              visible: win.corrections.length > 0
              width: parent.width; spacing: 6
              Text {
                text: "LEARNED CORRECTIONS"
                color: faint; font.pixelSize: 10
                font.letterSpacing: 1 }
              Text {
                text: "Things you told it to do differently:"
                color: sub; font.pixelSize: 12 }
              Repeater {
                model: win.corrections
                Text { text: "• " + modelData
                       color: sub
                       font.pixelSize: 11
                       width: parent.width; elide: Text.ElideRight }
              }
            }
          }
        }
      }

      // ════ MEMORY ════
      Item {
        Flickable {
          anchors { fill: parent }
          contentWidth: width
          contentHeight: memCol.implicitHeight + 32
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: memCol
            x: 20; y: 16
            width: parent.parent.width - 40
            spacing: 14

            Text {
              width: parent.width; wrapMode: Text.WordWrap
              color: sub; font.pixelSize: 12; lineHeight: 1.4
              text: "Wisp reads these at the start of every turn — its " +
                    "long-term memory. MEMORY.md is facts it learned; " +
                    "USER.md is how you want it to behave. Save applies " +
                    "next turn."
            }

            Repeater {
              model: [["memory", "MEMORY.md", "facts it learned about you",
                       memoryView],
                      ["user",   "USER.md",   "how it should behave",
                       userView]]
              Card {
                width: memCol.width
                property var src: modelData[3]
                property string tgt: modelData[0]
                Column {
                  spacing: 8
                  Row {
                    width: parent.width; spacing: 10
                    Column {
                      width: parent.width - 90; spacing: 2
                      Text { text: modelData[1]; color: fg
                             font.pixelSize: 13; font.bold: true }
                      Text { text: modelData[2]; color: faint
                             font.pixelSize: 11 }
                    }
                    Solid {
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
                    width: parent.width; height: 160; radius: 6
                    color: "#14151e"; border.color: border
                    Flickable {
                      anchors { fill: parent; margins: 8 }
                      contentWidth: width; contentHeight: edit.height
                      clip: true
                      TextEdit {
                        id: edit
                        width: parent.width
                        color: sub; font.pixelSize: 12
                        font.family: "monospace"
                        wrapMode: TextEdit.Wrap
                        text: modelData[3].text()
                      }
                    }
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
          anchors { fill: parent; margins: 20 }
          spacing: 14

          Text {
            width: parent.width; wrapMode: Text.WordWrap
            color: sub; font.pixelSize: 12; lineHeight: 1.4
            text: "Background tasks Wisp runs for you — coding agents " +
                  "like opencode, codex, claude (pick which in Settings " +
                  "→ Brain). They keep working while you do other things."
          }

          Row {
            width: parent.width; spacing: 10
            Rectangle {
              width: parent.width - 90; height: 34; radius: 8
              color: cardSolid; border.color: border
              TextInput {
                id: taskInput
                anchors { fill: parent; margins: 8 }
                color: fg; font.pixelSize: 13; clip: true
                Text {
                  anchors { left: parent.left; right: parent.right
                            verticalCenter: parent.verticalCenter }
                  visible: !taskInput.text
                  text: "describe a task…"
                  color: faint; font.pixelSize: 13 }
              }
            }
            Solid {
              label: "Spawn"
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
              width: parent.width; spacing: 8
              Repeater {
                model: Object.keys(win.tasks)
                Card {
                  width: taskCol.width
                  property var t: win.tasks[modelData] || {}
                  Row {
                    width: parent.width; spacing: 12
                    Rectangle {
                      width: 10; height: 10; radius: 5
                      anchors.verticalCenter: parent.verticalCenter
                      color: parent.parent.t.status === "running"
                             ? ok
                           : parent.parent.t.status === "failed"
                             ? err : faint
                    }
                    Column {
                      width: parent.width - 100; spacing: 2
                      anchors.verticalCenter: parent.verticalCenter
                      Text { text: modelData; color: fg; font.pixelSize: 12
                             width: parent.width; elide: Text.ElideRight }
                      Text {
                        text: (parent.parent.t.status || "?") +
                              " — " + (parent.parent.t.task || "")
                        color: faint; font.pixelSize: 11
                        width: parent.width; elide: Text.ElideRight }
                    }
                    Ghost {
                      visible: parent.parent.t.status === "running"
                      label: "Cancel"
                      anchors.verticalCenter: parent.verticalCenter
                      onClicked: win.wispd(["task_cancel", modelData])
                    }
                  }
                }
              }
              Text {
                visible: Object.keys(win.tasks).length === 0
                text: "No tasks yet."
                color: faint; font.pixelSize: 13 }
            }
          }
        }
      }

      // ════ SETTINGS ════
      Item {
        Flickable {
          anchors { fill: parent }
          contentWidth: width
          contentHeight: setCol.implicitHeight + 32
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: setCol
            x: 20; y: 16
            width: parent.parent.width - 40
            spacing: 18

            Text {
              width: parent.width; wrapMode: Text.WordWrap
              color: sub; font.pixelSize: 12; lineHeight: 1.4
              text: "config.toml, grouped. Edits apply live — no " +
                    "restart. Blank means default."
            }

            Repeater {
              model: [
                ["Talking to it",
                 "The hotkey and how long it records after you press.",
                 [["hotkey.mod","modifier key","SUPER / ALT / CTRL"],
                  ["hotkey.key","push-to-talk key","D → SUPER+D"],
                  ["audio.seconds","recording length","seconds of mic"],
                  ["voice.enabled","speak answers","true/false — TTS replies"],
                  ["voice.cmd","TTS command","empty = espeak"]]],
                ["Hearing",
                 "Speech-to-text. 'local' = whisper.cpp on this machine " +
                 "(free, private); an API provider is faster but sends " +
                 "audio out.",
                 [["stt.provider","STT provider","local | openai"],
                  ["stt.base_url","STT endpoint","groq/openai/vllm URL"],
                  ["stt.model","STT model","whisper-large-v3-turbo"],
                  ["stt.key_env","API key env var","env var holding the key"],
                  ["stt.prompt","vocab priming","names/jargon to recognize"]]],
                ["Brain",
                 "Who thinks. Router picks what to do with a request: " +
                 "jev = decision API, chat = straight to the answer " +
                 "brain, off = ask clarifying.",
                 [["brain.router","router","jev | chat | off"],
                  ["brain.default","answer brain","provider:model"],
                  ["agent.model","jev model","typesafe/jev-1.13"],
                  ["agent.answer_model","answer model","llama-4-maverick"],
                  ["brain.agent_runtime","agent runtime",
                   "opencode | codex | claude | devin"]]],
                ["Agents & actions",
                 "What Wisp may do on your desktop. Risk threshold: " +
                 "lower = it asks you before doing more.",
                 [["agent.risk_threshold","risk threshold","lower = more asks"],
                  ["agent.allow_shell","allow shell","true/false"],
                  ["agent.screenshots","screenshots","may see your screen"],
                  ["agents.model","agent model","model for runtimes"]]],
                ["Memory & recall",
                 "Semantic recall embeds past turns so 'the thing with " +
                 "the printer' finds old context. 'none' = keyword " +
                 "search only, zero keys needed.",
                 [["recall.provider","recall embeds","none | openai"],
                  ["recall.base_url","embed endpoint","openrouter URL"],
                  ["recall.model","embed model","text-embedding-3-small"],
                  ["agent.session_turns","session memory","turns kept"]]],
                ["Debugging",
                 "Full-fidelity trace of every turn — action, decision, " +
                 "tool call, timings — for replay and fixing. Never " +
                 "logs keys.",
                 [["debug.trace","dev trace","true/false"]]]
              ]

              Column {
                width: setCol.width; spacing: 8
                property var sec: modelData

                Text { text: modelData[0]; color: fg
                       font.pixelSize: 15; font.bold: true }
                Text { text: modelData[1]; color: sub
                       font.pixelSize: 12; lineHeight: 1.35
                       width: setCol.width; wrapMode: Text.WordWrap }

                Repeater {
                  model: parent.sec[2]
                  Rectangle {
                    width: setCol.width; height: 46; radius: 8
                    color: cardSolid; border.color: border
                    Row {
                      anchors { fill: parent; margins: 10 }
                      spacing: 12
                      Column {
                        width: setCol.width - 320; spacing: 1
                        anchors.verticalCenter: parent.verticalCenter
                        Text { text: modelData[1]; color: fg
                               font.pixelSize: 12 }
                        Text { text: modelData[2]; color: faint
                               font.pixelSize: 10 }
                      }
                      Rectangle {
                        width: 200; height: 28; radius: 6
                        color: "#14151e"; border.color: border
                        anchors.verticalCenter: parent.verticalCenter
                        TextInput {
                          id: sinput
                          anchors { fill: parent; margins: 6 }
                          color: fg; font.pixelSize: 12; clip: true
                          text: {
                            var parts = modelData[0].split(".");
                            var sec = win.cfgObj[parts[0]] || {};
                            var v = sec[parts.slice(1).join(".")];
                            if (v === undefined && parts.length > 2)
                              v = (sec[parts[1]] || {})[parts[2]];
                            v === undefined ? "" : String(v);
                          }
                        }
                      }
                      Ghost {
                        label: "Set"
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: win.wispd(["config", "set",
                                             modelData[0], sinput.text])
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
