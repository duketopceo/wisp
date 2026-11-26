import QtQuick
import QtTest
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../../../shell-plugin/lib/metrics.js" as M
import "../../../shell-plugin/components"
import "../harness"

// One type scale on the overlay (one-surface U4): the answer bubble's text
// follows the host text scale, and the bubble never grows past the screen.
TestCase {
  id: tc
  name: "overlay_scale"
  when: windowShown
  width: 480
  height: 400

  FixtureService { id: svc }
  Component { id: overlayC; OverlayLayer { width: 480; height: 400 } }

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
}
