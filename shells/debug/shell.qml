import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

// Dim — management app. Open/close from the launcher; the daemon stays
// resident. Tabs: Status (live state + controls), Logs (decisions with
// per-stage timing bars + session/corrections tails), Settings (live
// config editing via `dimd config`), Tasks (agent registry).
// Everything reads files/IPC — zero coupling to daemon internals.

FloatingWindow {
  id: win
  title: "Dim"
  minimumSize: Qt.size(820, 620)
  color: "#16161e"

  readonly property string rtDir: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    if (!rd || rd.length === 0) rd = "/tmp";
    return rd + "/dim-agent";
  }
  readonly property string dataDir: Quickshell.env("HOME") + "/.local/share/dim-agent"

  property var stateObj: ({})
  property var decisions: []
  property var sessionLines: []
  property var corrections: []
  property var cfgObj: ({})
  property int tab: 0

  function dimd(args) {
    if (cmdProc.running) return;
    cmdProc.command = ["dimd"].concat(args);
    cmdProc.running = true;
  }

  function svc(args) {
    if (svcProc.running) return;
    svcProc.command = ["systemctl", "--user"].concat(args).concat(["dimd"]);
    svcProc.running = true;
  }

  Process { id: cmdProc; command: ["dimd", "status"]
            onExited: if (command[1] === "config" && command[2] === "set"
                          && !cfgProc.running) cfgProc.running = true; }
  Process { id: svcProc; command: ["systemctl", "--user", "status", "dimd"] }

  // config fetch: dimd config prints JSON when daemon up; parse stdout
  Process {
    id: cfgProc
    command: ["dimd", "config"]
    stdout: StdioCollector {
      onStreamFinished: {
        try { win.cfgObj = JSON.parse(this.text); } catch (e) {}
      }
    }
  }

  FileView {
    id: stateView
    path: win.rtDir + "/state.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try { win.stateObj = JSON.parse(stateView.text()); } catch (e) {}
    }
  }
  FileView {
    id: decisionsView
    path: win.dataDir + "/decisions.jsonl"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var out = [];
      var lines = decisionsView.text().split("\n");
      for (var i = lines.length - 1; i >= 0 && out.length < 40; i--) {
        if (!lines[i].trim()) continue;
        try { out.push(JSON.parse(lines[i])); } catch (e) {}
      }
      win.decisions = out;
    }
  }
  FileView {
    id: sessionView
    path: win.dataDir + "/session.jsonl"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var out = [];
      var lines = sessionView.text().split("\n");
      for (var i = lines.length - 1; i >= 0 && out.length < 40; i--) {
        if (!lines[i].trim()) continue;
        try { out.push(JSON.parse(lines[i])); } catch (e) {}
      }
      win.sessionLines = out;
    }
  }
  FileView {
    id: corrView
    path: win.dataDir + "/corrections.jsonl"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      var out = [];
      var lines = corrView.text().split("\n");
      for (var i = lines.length - 1; i >= 0 && out.length < 40; i--) {
        if (!lines[i].trim()) continue;
        try { out.push(JSON.parse(lines[i])); } catch (e) {}
      }
      win.corrections = out;
    }
  }

  FileView {
    id: memoryView
    path: win.dataDir + "/MEMORY.md"
    watchChanges: true
    onFileChanged: reload()
  }
  FileView {
    id: userView
    path: win.dataDir + "/USER.md"
    watchChanges: true
    onFileChanged: reload()
  }
  property string skillsList: ""
  Process {
    id: skillsProc
    command: ["sh", "-c", "for d in \"$HOME/.local/share/dim-agent/skills\"/*/; do [ -f \"$d/SKILL.md\" ] && echo \"== $d\" && cat \"$d/SKILL.md\"; done"]
    stdout: StdioCollector {
      onStreamFinished: win.skillsList = this.text
    }
  }
  // All FileViews already watch+reload on change; timers only cover
  // things that aren't file-watched — the skills listing (only while
  // the Memory tab is visible) and a slow config refresh.
  Timer {
    interval: 2000; running: win.tab === 4; repeat: true
    onTriggered: if (!skillsProc.running) skillsProc.running = true;
  }
  Timer {
    interval: 10000; running: true; repeat: true
    onTriggered: if (!cfgProc.running) cfgProc.running = true;
  }
  Component.onCompleted: { cfgProc.running = true; skillsProc.running = true; }

  readonly property color fg: "#c0caf5"
  readonly property color dim: "#9aa5ce"
  readonly property color faint: "#565f89"
  readonly property color accent: "#7aa2f7"
  readonly property color card: "#1f2335"
  readonly property color border: "#292e42"

  function statusColor(s) {
    if (s === "error") return "#e05555";
    if (s === "listening") return accent;
    if (["transcribing","deciding"].indexOf(s) >= 0) return "#bb9af7";
    if (["acting","awaiting_choice","speaking"].indexOf(s) >= 0) return "#9ece6a";
    return faint;
  }

  RowLayout {
    anchors.fill: parent
    spacing: 0

    // ── Sidebar ──
    Rectangle {
      Layout.fillHeight: true
      width: 150
      color: card
      Column {
        anchors.fill: parent
        anchors.topMargin: 12
        spacing: 2
        Text { text: "  DIM"; color: accent; font.pixelSize: 15
               font.bold: true; bottomPadding: 12 }
        Repeater {
          model: ["Status", "Logs", "Graphs", "Session", "Memory",
                  "Tasks", "Settings"]
          Rectangle {
            width: 150; height: 34
            color: win.tab === index ? "#283457" : "transparent"
            Text { anchors.verticalCenter: parent.verticalCenter
                   anchors.left: parent.left; anchors.leftMargin: 14
                   text: modelData
                   color: win.tab === index ? fg : dim; font.pixelSize: 13 }
            MouseArea { anchors.fill: parent
                        onClicked: win.tab = index }
          }
        }
      }
    }

    // ── Content ──
    StackLayout {
      Layout.fillWidth: true
      Layout.fillHeight: true
      currentIndex: win.tab

      // STATUS
      Item {
        Column {
          anchors.fill: parent; anchors.margins: 16; spacing: 12
          Row {
            spacing: 14
            Rectangle { width: 18; height: 18; radius: 9
                        color: win.statusColor(win.stateObj.status || "offline") }
            Text { text: win.stateObj.status || "offline"
                   color: fg; font.pixelSize: 20; font.bold: true }
            Item { width: 20 }
            Repeater {
              model: ["listen", "learn", "harness"]
              Rectangle {
                height: 30; width: bl.implicitWidth + 20; radius: 7
                color: "#283457"
                Text { id: bl; anchors.centerIn: parent; text: modelData
                       color: fg; font.pixelSize: 12 }
                MouseArea { anchors.fill: parent
                            onClicked: win.dimd([modelData]) }
              }
            }
          }
          Row {
            spacing: 14
            Text { text: "daemon:"; color: faint; font.pixelSize: 11
                   anchors.verticalCenter: parent.verticalCenter }
            Repeater {
              model: [["start", "start"], ["stop", "stop"],
                      ["restart", "restart"], ["enable", "enable"],
                      ["disable", "disable"]]
              Rectangle {
                height: 26; width: sbl.implicitWidth + 16; radius: 6
                color: "#232736"
                Text { id: sbl; anchors.centerIn: parent
                       text: modelData[0]; color: dim; font.pixelSize: 11 }
                MouseArea { anchors.fill: parent
                            onClicked: win.svc([modelData[1]]) }
              }
            }
            Text { text: "GUI closes; daemon stays resident"
                   color: faint; font.pixelSize: 10
                   anchors.verticalCenter: parent.verticalCenter }
          }
          Rectangle { width: parent.width; height: 1; color: border }
          Grid {
            columns: 2; spacing: 8; width: parent.width
            Repeater {
              model: [
                ["transcript", win.stateObj.transcript || "—"],
                ["answer", win.stateObj.answer || "—"],
                ["result", win.stateObj.result || "—"],
                ["error", win.stateObj.error || "—"],
                ["choices", JSON.stringify(win.stateObj.choices || [])],
                ["level", (win.stateObj.level || 0).toFixed(3)],
                ["started", win.stateObj.started_at || "—"],
              ]
              Rectangle {
                width: (parent.width - 8) / 2
                height: kv.implicitHeight + 16
                color: card; radius: 8
                Column {
                  id: kv; anchors.fill: parent; anchors.margins: 8
                  spacing: 2
                  Text { text: modelData[0]; color: faint; font.pixelSize: 10 }
                  Text { text: modelData[1]; color: fg; font.pixelSize: 12
                         width: kv.width; wrapMode: Text.Wrap }
                }
              }
            }
          }
        }
      }

      // LOGS — decisions with per-stage timing bars
      Flickable {
        contentHeight: logCol.implicitHeight; clip: true
        Column {
          id: logCol; width: parent.width; padding: 16; spacing: 6
          // aggregate stats over the loaded window
          Text {
            color: faint; font.pixelSize: 11; bottomPadding: 6
            text: {
              var d = win.decisions;
              if (!d.length) return "decisions.jsonl — no entries yet";
              var routes = {}, errs = 0, tot = 0;
              for (var i = 0; i < d.length; i++) {
                var r = (d[i].result || "");
                if (r.indexOf("ERROR") === 0) errs++;
                var rt = (d[i].answers || {}).route || {};
                var c = rt.choice || "n/a";
                routes[c] = (routes[c] || 0) + 1;
                if (d[i].timing_ms) tot += d[i].timing_ms.act_ms || 0;
              }
              var parts = [];
              for (var k in routes) parts.push(k + ":" + routes[k]);
              return "decisions.jsonl — " + d.length + " shown · " +
                     errs + " errors · routes " + parts.join(" ") +
                     " · avg pipeline " + Math.round(tot / d.length) + "ms";
            }
          }
          Repeater {
            model: win.decisions
            Rectangle {
              width: logCol.width - 32
              height: dcol.implicitHeight + 12
              color: card; radius: 6
              Column {
                id: dcol; anchors.fill: parent; anchors.margins: 6; spacing: 3
                Text {
                  text: (modelData.ts || "").slice(11, 19) + "  " +
                        (modelData.transcript || "") + "  →  " +
                        (modelData.result || "")
                  color: fg; font.pixelSize: 11; width: dcol.width
                  wrapMode: Text.Wrap
                }
                Row {
                  spacing: 4; visible: !!modelData.timing_ms
                  Repeater {
                    model: modelData.timing_ms ?
                      [["rec", modelData.timing_ms.record_ms, "#7aa2f7"],
                       ["stt", modelData.timing_ms.stt_ms, "#bb9af7"],
                       ["jev", modelData.timing_ms.jev_ms, "#e0af68"],
                       ["act", modelData.timing_ms.act_ms, "#9ece6a"]] : []
                    Rectangle {
                      width: Math.max(14, Math.min(120,
                        (modelData[1] || 0) / 80))
                      height: 14; radius: 3; color: modelData[2]
                      Text { anchors.centerIn: parent
                             text: modelData[0] + " " + (modelData[1]||0) + "ms"
                             color: "#16161e"; font.pixelSize: 8 }
                    }
                  }
                }
              }
            }
          }
        }
      }

      // GRAPHS — history derived from decisions.jsonl (no new store):
      // stacked per-stage latency bars per turn + route mix strip +
      // error/blocked counts. Canvas charts — no QtCharts dep.
      Item {
        Column {
          anchors.fill: parent; anchors.margins: 16; spacing: 14
          Text { text: "per-turn pipeline latency (newest right)"
                 color: faint; font.pixelSize: 11 }
          Canvas {
            id: latencyChart
            width: parent.width; height: 160
            onPaint: {
              var ctx = getContext("2d");
              ctx.reset();
              var ds = win.decisions.slice().reverse(); // old→new
              var stages = [["record_ms","#7aa2f7"],["stt_ms","#bb9af7"],
                            ["jev_ms","#e0af68"],["act_ms","#9ece6a"]];
              var max = 1;
              for (var i = 0; i < ds.length; i++) {
                var t = ds[i].timing_ms || {}, s = 0;
                for (var j = 0; j < stages.length; j++)
                  s += t[stages[j][0]] || 0;
                if (s > max) max = s;
              }
              var bw = Math.max(3, (width - 20) / Math.max(1, ds.length));
              for (i = 0; i < ds.length; i++) {
                t = ds[i].timing_ms || {};
                var y = height;
                for (j = 0; j < stages.length; j++) {
                  var v = t[stages[j][0]] || 0;
                  var h = v / max * (height - 14);
                  ctx.fillStyle = stages[j][1];
                  ctx.fillRect(i * bw + 10, y - h, bw - 2, h);
                  y -= h;
                }
              }
            }
          }
          Row {
            spacing: 10
            Repeater {
              model: [["record","#7aa2f7"],["stt","#bb9af7"],
                      ["jev","#e0af68"],["act","#9ece6a"]]
              Row {
                spacing: 4
                Rectangle { width: 10; height: 10; radius: 2
                            color: modelData[1] }
                Text { text: modelData[0]; color: dim; font.pixelSize: 10 }
              }
            }
          }
          Text { text: "route mix"; color: faint; font.pixelSize: 11 }
          Canvas {
            id: routeStrip
            width: parent.width; height: 34
            onPaint: {
              var ctx = getContext("2d");
              ctx.reset();
              var routes = {}, n = 0, errs = 0, blocked = 0;
              for (var i = 0; i < win.decisions.length; i++) {
                var d = win.decisions[i];
                var c = ((d.answers||{}).route||{}).choice || "n/a";
                routes[c] = (routes[c]||0)+1; n++;
                var r = d.result || "";
                if (r.indexOf("ERROR") === 0) errs++;
                if (r.indexOf("BLOCKED") === 0) blocked++;
              }
              var pal = {"answer":"#7aa2f7","launch":"#9ece6a",
                         "act":"#e0af68","dictation":"#bb9af7",
                         "agent":"#f7768e","tool":"#449dab",
                         "clarify":"#565f89","none":"#292e42",
                         "n/a":"#292e42"};
              var x = 0, keys = Object.keys(routes);
              for (i = 0; i < keys.length; i++) {
                var w = routes[keys[i]] / Math.max(1,n) * width;
                ctx.fillStyle = pal[keys[i]] || "#414868";
                ctx.fillRect(x, 4, w, 26);
                x += w;
              }
            }
          }
          Text {
            color: dim; font.pixelSize: 11
            text: {
              var routes = {}, n = 0, errs = 0, blocked = 0;
              for (var i = 0; i < win.decisions.length; i++) {
                var d = win.decisions[i];
                var c = ((d.answers||{}).route||{}).choice || "n/a";
                routes[c] = (routes[c]||0)+1; n++;
                var r = d.result || "";
                if (r.indexOf("ERROR") === 0) errs++;
                if (r.indexOf("BLOCKED") === 0) blocked++;
              }
              var parts = [];
              for (var k in routes)
                parts.push(k + " " + Math.round(routes[k]/Math.max(1,n)*100) + "%");
              return n + " turns · " + parts.join(" · ") +
                     " — " + errs + " errors, " + blocked + " blocked";
            }
          }
          Text { text: "window: last " + win.decisions.length +
                       " decisions.jsonl entries"
                 color: faint; font.pixelSize: 10 }
        }
        Connections {
          target: win
          function onDecisionsChanged() {
            latencyChart.requestPaint(); routeStrip.requestPaint();
          }
        }
        Component.onCompleted: {
          latencyChart.requestPaint(); routeStrip.requestPaint();
        }
      }

      // SESSION + CORRECTIONS
      Flickable {
        contentHeight: sessCol.implicitHeight; clip: true
        Column {
          id: sessCol; width: parent.width; padding: 16; spacing: 6
          Text { text: "session.jsonl"; color: faint; font.pixelSize: 11 }
          Repeater {
            model: win.sessionLines
            Text {
              text: (modelData.ts || "").slice(5, 16) + "  " +
                    (modelData.transcript || "") +
                    (modelData.reply ? "  → " + modelData.reply : "")
              color: dim; font.pixelSize: 11; width: sessCol.width - 32
              wrapMode: Text.Wrap
            }
          }
          Text { text: "corrections.jsonl"; color: faint
                 font.pixelSize: 11; topPadding: 12 }
          Repeater {
            model: win.corrections
            Text {
              text: "heard " + (modelData.heard || "") + " → picked " +
                    (modelData.picked || "")
              color: "#e0af68"; font.pixelSize: 11
              width: sessCol.width - 32; wrapMode: Text.Wrap
            }
          }
        }
      }

      // MEMORY — curated memory + recall store + skills
      Flickable {
        contentHeight: memCol.implicitHeight; clip: true
        Column {
          id: memCol; width: parent.width; padding: 16; spacing: 8
          // Editable MEMORY/USER — saves go through `dimd memory-write`
          // → IPC `memory` cmd → memory.edit("write") — the same
          // budgeted, headered path the tools use, not a raw write.
          Repeater {
            model: [["memory", "MEMORY.md", memoryView],
                    ["user", "USER.md", userView]]
            Column {
              id: memCard
              width: memCol.width - 32; spacing: 4
              property var src: modelData[2]
              property string tgt: modelData[0]
              Row {
                spacing: 8
                Text { text: modelData[1]; color: faint; font.pixelSize: 11
                       anchors.verticalCenter: parent.verticalCenter }
                Rectangle {
                  width: 46; height: 20; radius: 4; color: "#283457"
                  Text { anchors.centerIn: parent; text: "save"
                         color: fg; font.pixelSize: 10 }
                  MouseArea {
                    anchors.fill: parent
                    onClicked: win.dimd(["memory-write", memCard.tgt,
                                         Qt.btoa(ed.text)])
                  }
                }
                Text { text: "edit applies via the memory tool (bounded)"
                       color: faint; font.pixelSize: 9
                       anchors.verticalCenter: parent.verticalCenter }
              }
              Rectangle {
                width: parent.width; height: Math.max(60, ed.implicitHeight + 16)
                color: "#16161e"; radius: 6; border.color: border
                TextEdit {
                  id: ed
                  anchors.fill: parent; anchors.margins: 8
                  color: fg; font.pixelSize: 11; wrapMode: TextEdit.Wrap
                  text: memCard.src.text()
                  property string lastLoaded: ""
                  Connections {
                    target: memCard.src
                    function onLoaded() {
                      // reload file→editor only when not dirty
                      if (memCard.src.text() !== ed.lastLoaded) {
                        ed.text = memCard.src.text();
                        ed.lastLoaded = ed.text;
                      }
                    }
                  }
                  onTextChanged: lastLoaded = text
                }
              }
            }
          }
          Text { text: "skills/ — self-authored SKILL.md files"
                 color: faint; font.pixelSize: 11; topPadding: 6 }
          Rectangle {
            width: memCol.width - 32; height: skTxt.implicitHeight + 16
            color: card; radius: 6
            Text { id: skTxt; anchors.fill: parent; anchors.margins: 8
                   text: win.skillsList || "(no skills yet — say \"Dim, learn …\")"
                   color: dim; font.pixelSize: 10
                   font.family: "monospace"; wrapMode: Text.Wrap }
          }
        }
      }

      // TASKS
      Flickable {
        contentHeight: taskCol.implicitHeight; clip: true
        Column {
          id: taskCol; width: parent.width; padding: 16; spacing: 6
          Text { text: "spawn a background agent task — runs through \
[brain] agent_runtime"; color: faint; font.pixelSize: 11 }
          Row {
            spacing: 8
            Rectangle {
              width: taskCol.width - 140; height: 30
              color: "#16161e"; radius: 6; border.color: border
              TextInput {
                id: taskInput
                anchors.fill: parent; anchors.margins: 8
                color: fg; font.pixelSize: 12; clip: true
                property string placeholder: "describe the task…"
                Text { visible: !taskInput.text; text: taskInput.placeholder
                       color: faint; font.pixelSize: 12
                       anchors.verticalCenter: parent.verticalCenter }
              }
            }
            Rectangle {
              width: 70; height: 30; radius: 6; color: "#283457"
              Text { anchors.centerIn: parent; text: "spawn"
                     color: fg; font.pixelSize: 12 }
              MouseArea {
                anchors.fill: parent
                onClicked: {
                  if (taskInput.text.trim().length > 0) {
                    win.dimd(["agent"].concat(
                      taskInput.text.trim().split(" ")));
                    taskInput.text = "";
                  }
                }
              }
            }
          }
          Text { text: "agent tasks (from state.json)"; color: faint
                 font.pixelSize: 11; topPadding: 6 }
          Repeater {
            model: Object.keys(win.stateObj.tasks || {})
            Rectangle {
              width: taskCol.width - 32; height: trow.implicitHeight + 14
              color: card; radius: 6
              Row {
                id: trow; anchors.fill: parent; anchors.margins: 7
                spacing: 8
                Column {
                  width: trow.width - 74; spacing: 2
                  Text { text: modelData + "  [" +
                         (win.stateObj.tasks[modelData].status || "?") + "]"
                         color: fg; font.pixelSize: 12; font.bold: true }
                  Text { text: win.stateObj.tasks[modelData].task || ""
                         color: dim; font.pixelSize: 11
                         width: parent.width; wrapMode: Text.Wrap }
                }
                Rectangle {
                  width: 58; height: 22; radius: 5; color: "#3d2233"
                  visible: (win.stateObj.tasks[modelData].status || "")
                           === "running"
                  anchors.verticalCenter: parent.verticalCenter
                  Text { anchors.centerIn: parent; text: "cancel"
                         color: "#f7768e"; font.pixelSize: 10 }
                  MouseArea { anchors.fill: parent
                              onClicked: win.dimd(["task_cancel",
                                                   modelData]) }
                }
              }
            }
          }
          Text { visible: Object.keys(win.stateObj.tasks || {}).length === 0
                 text: "no agent tasks yet — spawn above or say \
\"Dim, agent …\""
                 color: faint; font.pixelSize: 11 }
        }
      }

      // SETTINGS
      Flickable {
        contentHeight: setCol.implicitHeight; clip: true
        Column {
          id: setCol; width: parent.width; padding: 16; spacing: 10
          Text { text: "config.toml — edits apply live via IPC"
                 color: faint; font.pixelSize: 11 }
          Repeater {
            model: [
              ["agent.answer_model", "answer model"],
              ["agent.model", "jev model"],
              ["brain.router", "router (jev|chat|off)"],
              ["brain.default", "answer brain (name:model)"],
              ["brain.agent_runtime", "agent runtime (opencode|codex|claude|devin)"],
              ["voice.enabled", "voice_out (true|false)"],
              ["voice.cmd", "tts cmd override (empty=espeak)"],
              ["stt.provider", "stt (local|openai)"],
              ["stt.base_url", "stt base url (groq/openai/vllm)"],
              ["stt.model", "stt model"],
              ["stt.key_env", "stt api key env var"],
              ["stt.prompt", "stt vocab priming (names/jargon)"],
              ["recall.provider", "recall embeds (none|openai)"],
              ["recall.model", "recall embed model"],
              ["audio.seconds", "record seconds"],
              ["agent.risk_threshold", "risk threshold"],
              ["agent.allow_shell", "allow_shell (true|false)"],
              ["agent.screenshots", "screenshots (true|false)"],
              ["agents.model", "agent runtime model (ori opencode)"],
            ]
            Rectangle {
              width: setCol.width - 32; height: 40
              color: card; radius: 6
              Row {
                anchors.fill: parent; anchors.margins: 8; spacing: 10
                Text { text: modelData[1]; color: dim; font.pixelSize: 12
                       width: 190; anchors.verticalCenter: parent.verticalCenter }
                Rectangle {
                  width: 300; height: 26; radius: 4; color: "#16161e"
                  anchors.verticalCenter: parent.verticalCenter
                  border.color: border
                  TextInput {
                    id: input
                    anchors.fill: parent; anchors.margins: 5
                    color: fg; font.pixelSize: 12; clip: true
                    text: {
                      var parts = modelData[0].split(".");
                      var v = (win.cfgObj[parts[0]] || {})[parts[1]];
                      v === undefined ? "" : String(v);
                    }
                  }
                }
                Rectangle {
                  width: 60; height: 26; radius: 4; color: "#283457"
                  anchors.verticalCenter: parent.verticalCenter
                  Text { anchors.centerIn: parent; text: "set"
                         color: fg; font.pixelSize: 11 }
                  MouseArea {
                    anchors.fill: parent
                    onClicked: win.dimd(["config", "set", modelData[0],
                                         input.text])
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
