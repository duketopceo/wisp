import QtQuick
import QtTest
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../../../shell-plugin/lib/metrics.js" as M
import "../../../shell-plugin/components"
import "../harness"

// One type scale in the settings window (one-surface U4): every word on
// the Spend, Audit and Binds pages follows the host text scale, from the
// same scene data the snapshot harness renders.
TestCase {
  id: tc
  name: "settings_scale"
  when: windowShown
  width: 720
  height: 600

  FixtureService { id: svc }
  Component { id: spendC; SpendView { width: 700 } }
  Component { id: auditC; AuditView { width: 700 } }
  Component { id: bindsC; BindsView { width: 700 } }

  function json(path) {
    var x = new XMLHttpRequest();
    x.open("GET", Qt.resolvedUrl(path), false);
    x.send();
    return JSON.parse(x.responseText);
  }

  function texts(item, out) {
    if (item.font !== undefined && item.text !== undefined && item.text !== "") out.push(item);
    for (var i = 0; i < item.children.length; i++) texts(item.children[i], out);
    return out;
  }

  function cleanup() { svc.textScale = 1; }

  // the scene's own props, without the harness-only keys
  function sceneProps(scene, variant) {
    var v = json("../harness/scenes.json")[scene].variants[variant];
    var raw = json("../../fixtures/states/" + (v._state || "idle") + ".json");
    var mods = raw._fixture || {};
    delete raw._fixture;
    var extra = v._fixture || {};
    for (var k in extra) mods[k] = extra[k];
    svc.tokens = Tokens.load("", "", "dark").tokens;
    svc.load(raw, mods);
    var props = { service: svc };
    for (var p in v) if (p.charAt(0) !== "_") props[p] = v[p];
    return props;
  }

  function check(comp, scene, variant) {
    svc.textScale = 1;
    var view = createTemporaryObject(comp, tc, sceneProps(scene, variant));
    verify(view !== null, scene);
    var t = texts(view, []);
    verify(t.length >= 4, scene + " words " + t.length);
    var before = t.map(function (x) { return x.font.pixelSize; });
    for (var i = 0; i < before.length; i++)
      verify(before[i] >= M.scale.minimum.secondary, scene + " " + t[i].text + " " + before[i]);
    svc.textScale = 1.5;
    for (var j = 0; j < t.length; j++)
      verify(t[j].font.pixelSize > before[j], scene + " " + t[j].text + " stayed " + before[j]);
  }

  function test_spend_follows_text_scale() { check(spendC, "SpendView", "ok"); }
  function test_audit_follows_text_scale() { check(auditC, "AuditView", "rows"); }
  function test_binds_follows_text_scale() { check(bindsC, "BindsView", "submap"); }
}
