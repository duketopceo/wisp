import QtQuick
import QtTest
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../../../shell-plugin/lib/metrics.js" as M
import "../../../shell-plugin/components"
import "../harness"

// Table-driven: every state fixture through the real reducer and the real
// Pill; the pill's status word and tone must match the copy table
// (wisp/copy.py), with the one rewrite: a done turn whose result is BLOCKED
// reads "blocked" in the needs-you tone, never "done".
TestCase {
  id: tc
  name: "pill"
  when: windowShown
  width: 480
  height: 200

  FixtureService { id: svc }

  property var tokens: Tokens.load("", "", "dark").tokens

  function readJson(name) {
    var x = new XMLHttpRequest();
    x.open("GET", Qt.resolvedUrl("../../fixtures/states/" + name + ".json"), false);
    x.send();
    return JSON.parse(x.responseText);
  }

  // fixture -> [word, tone]
  function table() {
    return [
      ["idle", "ready", "muted"],
      ["listening", "listening", "ember"],
      ["transcribing", "hearing you", "ember"],
      ["deciding", "thinking", "ember"],
      ["acting", "working", "ember"],
      ["speaking", "speaking", "ember"],
      ["awaiting_choice", "your call", "needsYou"],
      ["suggestion", "idea", "ember"],
      ["done", "done", "ok"],
      ["long_answer", "speaking", "ember"],
      ["error", "that failed", "fail"],
      ["blocked", "blocked", "needsYou"],
      ["stale", "working", "ember"],
      ["offline", "offline", "muted"]
    ];
  }

  function findWord(item) {
    if (item.objectName === "word") return item;
    for (var i = 0; i < item.children.length; i++) {
      var r = findWord(item.children[i]);
      if (r) return r;
    }
    return null;
  }

  function test_every_fixture_label_and_tone() {
    svc.tokens = tokens;
    var rows = table();
    for (var i = 0; i < rows.length; i++) {
      var name = rows[i][0];
      var raw = readJson(name);
      var mods = raw._fixture || {};
      delete raw._fixture;
      svc.load(raw, mods);
      var pill = createTemporaryObject(pillComp, tc, { service: svc });
      verify(pill !== null, name + " created");
      var w = findWord(pill);
      verify(w !== null, name + " word item");
      compare(w.text, rows[i][1], name + " label");
      compare(String(w.color), String(tokens[M.toneToken(rows[i][2])]), name + " tone");
      pill.destroy();
    }
  }

  Component { id: pillComp; Pill { } }
}
