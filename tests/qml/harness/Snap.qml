import QtQuick
import QtQuick.Window

// Snapshot renderer (scripts/ui/snap.py drives it):
//   qml Snap.qml -- <manifest.json> <out-dir>
// For each case in the manifest it builds one component against a
// FixtureService (state view from lib/state.js, theme tokens, fixed font,
// motion off), grabs the item to <out-dir>/<case id>.png and quits. It is
// headless by contract: it exits 2 unless Qt runs on the offscreen platform,
// so a stray Wayland or X session can never get a window from the tests.
Window {
  id: win
  visible: true
  width: 640
  height: 480
  color: "#00000000"

  property var cases: []
  property string outDir: ""
  property int next: 0
  property int failed: 0

  FontLoader { source: "../fonts/LiberationMono-Regular.ttf" }
  FontLoader { source: "../fonts/LiberationMono-Bold.ttf" }

  FixtureService { id: svc }

  Item {
    id: stage
    x: 0
    y: 0
  }

  function readJson(path) {
    var x = new XMLHttpRequest();
    x.open("GET", "file://" + path, false);
    x.send();
    return JSON.parse(x.responseText);
  }

  function fail(msg) {
    console.log("SNAP-FAIL " + msg);
    failed += 1;
  }

  function finish() {
    console.log("SNAP-DONE " + cases.length + " failed " + failed);
    Qt.exit(failed > 0 ? 1 : 0);
  }

  function renderCase(c) {
    for (var k in stage.children) stage.children[k].destroy();
    svc.tokens = c.tokens;
    svc.load(c.snapshot, c.mods);
    var comp = Qt.createComponent("../../../shell-plugin/components/" + c.component + ".qml");
    if (comp.status !== Component.Ready) {
      fail(c.id + " " + comp.errorString());
      return null;
    }
    var host = Qt.createQmlObject(
      'import QtQuick; Rectangle { }', stage, "host");
    host.color = c.on === "desktop" ? c.tokens.raised : c.tokens.canvas;
    var props = {};
    for (var k in c.props) props[k] = c.props[k];
    props.service = svc;
    var item = comp.createObject(host, props);
    if (item === null) {
      fail(c.id + " create failed");
      return null;
    }
    if (c.width) item.width = c.width;
    item.x = c.pad;
    item.y = c.pad;
    host.width = Math.ceil(item.width) + 2 * c.pad;
    host.height = Math.max(Math.ceil(item.height), 8) + 2 * c.pad;
    return host;
  }

  Timer {
    id: step
    interval: 0
    repeat: false
    onTriggered: win.advance()
  }

  function advance() {
    if (next >= cases.length) { finish(); return; }
    var c = cases[next];
    var host = renderCase(c);
    if (host === null) { next += 1; step.restart(); return; }
    host.grabToImage(function (res) {
      if (!res.saveToFile(outDir + "/" + c.id + ".png"))
        fail(c.id + " save failed");
      next += 1;
      step.restart();
    });
  }

  Component.onCompleted: {
    var args = Qt.application.arguments;
    var i = args.indexOf("--");
    if (Qt.platform.pluginName !== "offscreen") {
      console.log("SNAP-FAIL platform " + Qt.platform.pluginName);
      Qt.exit(2);
      return;
    }
    if (i < 0 || args.length < i + 3) {
      console.log("SNAP-FAIL usage: Snap.qml -- manifest out");
      Qt.exit(2);
      return;
    }
    cases = readJson(args[i + 1]).cases;
    outDir = args[i + 2];
    step.start();
  }
}
