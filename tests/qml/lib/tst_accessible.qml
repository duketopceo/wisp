import QtQuick
import QtTest
import "../../../shell-plugin/lib/settings.js" as S
import "../../../shell-plugin/lib/metrics.js" as M
import "../../../shell-plugin/components"
import "../harness"

// Construction rules (one-surface U7): every interactive control in the
// Panel (each tab, Dev included) and the settings window (each sidebar
// page and category) has an accessible name, and shows a visible change
// when it takes focus. The scan (harness/A11yScan.qml) is tested on a
// fixture first, so a blind scan cannot pass. Both grabs of a focus
// check come from the same run; nothing is compared with stored pixels.
Item {
  id: root
  width: 960
  height: 700

  FixtureService {
    id: svc
    devPanel: true
    tokens: ({ canvas: "#101010", surface: "#181818", raised: "#202020",
               keyline: "#303030", keylineStrong: "#505050", ink: "#eeeeee",
               inkMuted: "#999999", accent: "#4488ff", selection: "#223355",
               fail: "#ff5555", ok: "#55ff55", ember: "#ff8800",
               needsYou: "#ffcc00" })
  }

  A11yScan { id: scan }

  // takes focus between checks, so every "before" grab is unfocused
  Item { id: sink; width: 1; height: 1; activeFocusOnTab: false }

  PanelBody {
    id: body
    visible: false
    service: svc
    width: 480
    height: 560
    tabKeys: ["now", "agents", "memory", "quick", "devtab"]
    devPanelOn: true
    onPickTab: function (i) { body.tab = i }
  }

  SettingsHost {
    id: host
    visible: false
    service: svc
    width: 960
    height: 700
    loaded: true
  }

  // fixture: one named and one unnamed control
  Item {
    id: fixture
    visible: false
    width: 100; height: 40
    Rectangle {
      id: namedCtl; objectName: "namedCtl"; width: 40; height: 20
      activeFocusOnTab: true
      Accessible.role: Accessible.Button; Accessible.name: "Go"
    }
    Rectangle {
      id: bareCtl; objectName: "bareCtl"; x: 50; width: 40; height: 20
      activeFocusOnTab: true
    }
    Rectangle { x: 0; y: 25; width: 40; height: 10 }   // not a control
    Rectangle {                                       // named, not focusable
      objectName: "tabCtl"; x: 50; y: 25; width: 40; height: 10
      Accessible.role: Accessible.PageTab; Accessible.name: "Now"
    }
  }

  TestCase {
    name: "accessible"
    when: windowShown

    function cleanup() {
      body.visible = false
      host.visible = false
      fixture.visible = false
      bareCtl.Accessible.name = ""
    }

    // scroll the nearest scrolling page so the control is on screen
    function reveal(item) {
      for (var p = item.parent; p; p = p.parent) {
        if (typeof p.ensureVisible === "function") { p.ensureVisible(item); break }
      }
    }

    function onScreen(scene, item) {
      var r = item.mapToItem(scene, 0, 0, item.width, item.height)
      return r.width > 0 && r.height > 0 && r.x >= 0 && r.y >= 0
          && r.x + r.width <= scene.width && r.y + r.height <= scene.height
    }

    // true when any pixel in the control's rect, inflated by the focus
    // ring width, differs between the two grabs
    function changed(before, after, scene, item) {
      var pad = M.scale.focusRing + 1
      var r = item.mapToItem(scene, 0, 0, item.width, item.height)
      var x0 = Math.max(0, Math.floor(r.x - pad))
      var y0 = Math.max(0, Math.floor(r.y - pad))
      var x1 = Math.min(before.width, Math.ceil(r.x + r.width + pad))
      var y1 = Math.min(before.height, Math.ceil(r.y + r.height + pad))
      for (var y = y0; y < y1; y++)
        for (var x = x0; x < x1; x++)
          if (!Qt.colorEqual(before.pixel(x, y), after.pixel(x, y))) return true
      return false
    }

    // every control in the scene: named, and focus changes its pixels
    function audit(scene, label) {
      var bad = scan.unnamed(scene).map(function (d) { return label + ": unnamed " + d })
      var list = scan.controls(scene)
      for (var i = 0; i < list.length; i++) {
        var c = list[i]
        if (!scan.focusable(c)) continue
        // grabImage renders the window synchronously, so no frame wait
        // is needed (waitForRendering blocks when nothing changes)
        reveal(c)
        if (!onScreen(scene, c)) {
          bad.push(label + ": off screen " + scan.describe(c))
          continue
        }
        sink.forceActiveFocus()
        var before = grabImage(scene)
        c.forceActiveFocus()
        if (!c.activeFocus) {
          bad.push(label + ": cannot take focus " + scan.describe(c))
          continue
        }
        var after = grabImage(scene)
        if (!changed(before, after, scene, c))
          bad.push(label + ": no visible focus " + scan.describe(c))
      }
      return { bad: bad, controls: list }
    }

    function test_scan_flags_an_unnamed_control() {
      fixture.visible = true
      compare(scan.controls(fixture).length, 3)
      compare(scan.unnamed(fixture), [scan.describe(bareCtl)])
      verify(scan.describe(bareCtl).indexOf("bareCtl") === 0)
      bareCtl.Accessible.name = "Stop"
      compare(scan.unnamed(fixture), [])
    }

    function test_scan_skips_hidden_and_disabled_controls() {
      fixture.visible = true
      bareCtl.visible = false
      compare(scan.controls(fixture).length, 2)
      bareCtl.visible = true
      bareCtl.enabled = false
      compare(scan.controls(fixture).length, 2)
      bareCtl.enabled = true
    }

    function test_focus_rule_applies_to_tab_focus_only() {
      fixture.visible = true
      verify(scan.focusable(namedCtl))
      verify(!scan.focusable(findChild(fixture, "tabCtl")))
    }

    function test_panel_tabs() {
      body.visible = true
      var bad = []
      for (var t = 0; t < body.tabKeys.length; t++) {
        body.tab = t
        body.page.scrollTo(0)
        waitForRendering(body)
        var r = audit(body, "panel/" + body.tabKeys[t])
        bad = bad.concat(r.bad)
        // floor: the scan sees every tab button, so it is not blind
        var names = scan.named(body)
        for (var k = 0; k < body.tabKeys.length; k++)
          if (names.indexOf("tab:" + body.tabKeys[k]) < 0)
            bad.push("panel/" + body.tabKeys[t] + ": scan missed tab:" + body.tabKeys[k])
      }
      if (bad.length) console.log("A11Y\n" + bad.join("\n"))
      compare(bad, [])
    }

    function test_settings_window_pages_and_categories() {
      // every page shows its loaded body, with data, so its controls exist
      svc.load({ status: "idle", tasks: {
        "weekly report": { task: "weekly report", status: "running",
                           line: "reading", seconds: 12 } } }, {})
      host.heard = true
      host.turns = [{ time: "08:12:01", route: "act", ms: 812,
                      you: "turn on night light", wisp: "Night light is on." }]
      host.suggestions = [{ key: "night-light", title: "Night light every evening",
                            evidence: "asked 5 evenings in a row", status: "new" }]
      host.corrections = ["\"nite lite\" -> \"night light\""]
      host.memoryText = "- prefers dark themes\n"
      host.userText = "Answer briefly.\n"
      host.visible = true
      var bad = []
      for (var i = 0; i < S.SIDEBAR.length; i++) {
        host.category = S.SIDEBAR[i]
        waitForRendering(host)
        var r = audit(host, "settings/" + S.SIDEBAR[i])
        bad = bad.concat(r.bad)
        // floor: past the search box, sidebar and heading, every page but
        // the read-only Status pages has a control of its own to focus
        var own = r.controls.filter(scan.focusable).length
        if (S.STATUS_PAGES.indexOf(S.SIDEBAR[i]) < 0 && own < 4) bad.push("settings/" + S.SIDEBAR[i] + ": only " + own + " focusable controls")
        // floor: the scan sees every sidebar row
        var names = scan.named(host)
        for (var k = 0; k < S.SIDEBAR.length; k++)
          if (names.indexOf("cat:" + S.SIDEBAR[k]) < 0)
            bad.push("settings/" + S.SIDEBAR[i] + ": scan missed cat:" + S.SIDEBAR[k])
      }
      if (bad.length) console.log("A11Y\n" + bad.join("\n"))
      compare(bad, [])
    }
  }
}
