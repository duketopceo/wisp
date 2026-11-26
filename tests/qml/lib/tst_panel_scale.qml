import QtQuick
import QtTest
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../../../shell-plugin/lib/metrics.js" as M
import "../../../shell-plugin/components"
import "../harness"

// One type scale on the Panel (one-surface U4): Panel text follows the host
// text scale, and the Panel's controls keep their hit target at text scale
// 1 and grow to hold their words at text scale 2.
TestCase {
  id: tc
  name: "panel_scale"
  when: windowShown
  width: 480
  height: 400

  FixtureService { id: svc }
  Component { id: chipC; Chip { label: "open settings"; hint: "2" } }
  Component { id: tabC; PanelTab { text: "now" } }
  Component { id: stopC; StopControl { alwaysShow: true } }
  Component { id: noteC; RateNote { width: 340 } }
  Component { id: statusC; StatusLine {} }
  Component { id: runC; RunCard {} }

  function find(item, name) {
    if (item.objectName === name) return item;
    for (var i = 0; i < item.children.length; i++) {
      var r = find(item.children[i], name);
      if (r) return r;
    }
    return null;
  }

  function readJson(name) {
    var x = new XMLHttpRequest();
    x.open("GET", Qt.resolvedUrl("../../fixtures/states/" + name + ".json"), false);
    x.send();
    return JSON.parse(x.responseText);
  }

  function texts(item, out) {
    if (item.font !== undefined && item.text !== undefined && item.text !== "") out.push(item);
    for (var i = 0; i < item.children.length; i++) texts(item.children[i], out);
    return out;
  }

  function cleanup() { svc.textScale = 1; }

  function load(ts) {
    svc.tokens = Tokens.load("", "", "dark").tokens;
    var raw = readJson("acting");
    var mods = raw._fixture || {};
    delete raw._fixture;
    svc.load(raw, mods);
    svc.textScale = ts;
  }

  function controls() {
    return [createTemporaryObject(chipC, tc, { service: svc }),
            createTemporaryObject(tabC, tc, { service: svc }),
            createTemporaryObject(stopC, tc, { service: svc }),
            createTemporaryObject(noteC, tc, { service: svc })];
  }

  function test_controls_keep_the_hit_target_at_text_scale_1() {
    load(1);
    var c = controls();
    for (var i = 0; i < c.length; i++) compare(c[i].implicitHeight, M.size.control, "control " + i);
  }

  function test_controls_hold_their_words_at_text_scale_2() {
    load(2);
    var c = controls();
    for (var i = 0; i < c.length; i++) {
      verify(c[i].implicitHeight >= M.size.control, "control " + i);
      var t = texts(c[i], []);
      verify(t.length > 0, "control " + i + " has text");
      for (var j = 0; j < t.length; j++)
        verify(t[j].implicitHeight <= c[i].implicitHeight,
          "control " + i + " text " + t[j].implicitHeight + " in " + c[i].implicitHeight);
    }
  }

  function test_panel_text_follows_text_scale() {
    load(1);
    var s = createTemporaryObject(statusC, tc, { service: svc });
    var t1 = texts(s, []);
    verify(t1.length > 0);
    var px1 = t1[0].font.pixelSize;
    svc.textScale = 1.5;
    verify(texts(s, [])[0].font.pixelSize > px1, "status line grew");
  }

  function test_a_finished_run_keeps_its_outcome_words() {
    svc.tokens = Tokens.load("", "", "dark").tokens;
    var raw = readJson("run_done");
    var mods = raw._fixture || {};
    delete raw._fixture;
    svc.load(raw, mods);
    var card = createTemporaryObject(runC, tc, { service: svc });
    var s = find(card, "runSummary");
    verify(s !== null);
    compare(s.text, card.summary);
    verify(s.text !== "");
    verify(!s.truncated, "outcome elided: " + s.text);
  }
}
