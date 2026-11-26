import QtQuick
import QtTest
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../../../shell-plugin/lib/metrics.js" as M
import "../../../shell-plugin/components"
import "../harness"

// One type scale on the overlay (one-surface U4): the answer bubble's text
// follows the host text scale, and the bubble never grows past the screen;
// overlay controls keep their hit target at text scale 1 and grow to hold
// their words at text scale 2.
TestCase {
  id: tc
  name: "overlay_scale"
  when: windowShown
  width: 480
  height: 400

  FixtureService { id: svc }
  Component { id: overlayC; OverlayLayer { width: 480; height: 400 } }
  Component { id: chipsC; AskChips {} }
  Component { id: rateC; RateRow {} }
  Component { id: teachC; TeachChip {} }
  Component { id: composerC; Composer { width: 400 } }

  function readJson(name) {
    var x = new XMLHttpRequest();
    x.open("GET", Qt.resolvedUrl("../../fixtures/states/" + name + ".json"), false);
    x.send();
    return JSON.parse(x.responseText);
  }

  function find(item, name) {
    if (item.objectName === name) return item;
    for (var i = 0; i < item.children.length; i++) {
      var r = find(item.children[i], name);
      if (r) return r;
    }
    return null;
  }

  function cleanup() { svc.textScale = 1; }

  function test_bubble_stays_inside_the_overlay_at_text_scale_2() {
    var raw = readJson("long_answer");
    var mods = raw._fixture || {};
    delete raw._fixture;
    svc.tokens = Tokens.load("", "", "dark").tokens;
    svc.load(raw, mods);
    var layer = createTemporaryObject(overlayC, tc, { service: svc });
    var bubble = find(layer, "bubble");
    verify(bubble !== null);
    verify(layer.bubbleShown);
    var w1 = bubble.implicitWidth;
    svc.textScale = 2;
    verify(bubble.implicitWidth > w1, "the answer columns grew");
    verify(bubble.width <= 480 - 2 * M.scale.space.xl, "bubble " + bubble.width);
  }

  function texts(item, out) {
    if (item.font !== undefined && item.text !== undefined && item.text !== "") out.push(item);
    for (var i = 0; i < item.children.length; i++) texts(item.children[i], out);
    return out;
  }

  // every Text inside a control box fits that box; the box never drops
  // under the compact hit target
  function checkControls(boxes, label) {
    verify(boxes.length > 0, label + " has controls");
    for (var i = 0; i < boxes.length; i++) {
      var b = boxes[i];
      verify(b.height >= M.controlHeight(true), label + " hit target " + b.height);
      var t = texts(b, []);
      for (var j = 0; j < t.length; j++)
        verify(t[j].implicitHeight <= b.height, label + " text " + t[j].implicitHeight + " in " + b.height);
    }
  }

  function overlayControls(ts) {
    svc.tokens = Tokens.load("", "", "dark").tokens;
    var raw = readJson("done");
    var mods = raw._fixture || {};
    delete raw._fixture;
    svc.load(raw, mods);
    svc.textScale = ts;
    var chips = createTemporaryObject(chipsC, tc, { service: svc, motion: "off",
      chips: { app: "kitty", seq: 1, asks: ["How do I open a new tab?"] } });
    var rate = createTemporaryObject(rateC, tc, { service: svc });
    var teach = createTemporaryObject(teachC, tc, { service: svc,
      step: { chip: "night light", counter: "1 of 3", visible: true } });
    var comp = createTemporaryObject(composerC, tc, { service: svc });
    var rateBtns = [];
    for (var i = 0; i < rate.children.length; i++) {
      var r = rate.children[i];
      for (var k = 0; k < r.children.length; k++)
        if (r.children[k].Accessible.role === Accessible.Button) rateBtns.push(r.children[k]);
    }
    checkControls([find(chips, "askChip")], "AskChips " + ts);
    checkControls(rateBtns, "RateRow " + ts);
    checkControls([find(teach, "teachChip"), find(teach, "teachCounter")], "TeachChip " + ts);
    checkControls([comp], "Composer " + ts);
    return { chip: find(chips, "askChip").height, comp: comp.height };
  }

  function test_overlay_controls_hold_their_words_at_text_scale_2() {
    var one = overlayControls(1);
    compare(one.chip, M.size.control);
    compare(one.comp, M.size.control);
    overlayControls(2);
  }
}
