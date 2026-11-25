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
      svc.load({ status: "idle", tasks: {} }, {})
    }

    function readJson(path) {
      var x = new XMLHttpRequest()
      x.open("GET", Qt.resolvedUrl(path), false)
      x.send()
      return JSON.parse(x.responseText)
    }

    // the snapshot scenes are the list of states a surface has; the scan
    // walks each one, so a control that only shows in one state is seen
    function scene(name) { return readJson("../harness/scenes.json")[name] }

    // load a variant's state fixture (and its fixture mods) into the service
    function loadState(variant) {
      var raw = readJson("../../fixtures/states/" + (variant._state || "idle") + ".json")
      var mods = raw._fixture || {}
      delete raw._fixture
      var extra = variant._fixture || {}
      for (var k in extra) mods[k] = extra[k]
      svc.load(raw, mods)
    }

    // set a variant's own props on the item; harness keys start with "_"
    function applyProps(item, variant, defaults) {
      for (var d in defaults) item[d] = defaults[d]
      for (var k in variant)
        if (k[0] !== "_" && k !== "width" && k !== "height") item[k] = variant[k]
    }

    function auditVariants(item, names, defaults, label, extra) {
      var bad = []
      for (var n = 0; n < names.length; n++) {
        var variants = scene(names[n]).variants
        for (var v in variants) {
          var variant = variants[v]
          if (extra) variant = extra(variant)
          loadState(variant)
          applyProps(item, variant, defaults)
          if (item.page && item.page.scrollTo) item.page.scrollTo(0)
          waitForRendering(item)
          bad = bad.concat(audit(item, label + "/" + names[n] + "__" + v).bad)
        }
      }
      return bad
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

    // every control in the scene: named, and focus changes its pixels.
    // Returns the failures and the object names the scan saw.
    function audit(scene, label) {
      var list = scan.controls(scene)
      var bad = scan.nameless(list).map(function (d) { return label + ": unnamed " + d })
      var seen = []
      for (var i = 0; i < list.length; i++) {
        var c = list[i]
        if (c.objectName) seen.push(c.objectName)
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
      return { bad: bad, seen: seen, focusable: list.filter(scan.focusable).length }
    }

    // floor: the scan saw every name in `want`, so it is not blind
    function missed(seen, want, prefix, label) {
      return want.filter(function (k) { return seen.indexOf(prefix + k) < 0 })
                 .map(function (k) { return label + ": scan missed " + prefix + k })
    }

    function finish(bad) {
      if (bad.length) console.log("A11Y\n" + bad.join("\n"))
      compare(bad, [])
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
        var label = "panel/" + body.tabKeys[t]
        var r = audit(body, label)
        bad = bad.concat(r.bad, missed(r.seen, body.tabKeys, "tab:", label))
      }
      finish(bad)
    }

    // every PanelBody scene, and every Now tab state scene, under its own
    // state: questions, choices, confirms, rate prompts and banners
    function test_panel_scenes() {
      body.visible = true
      var defaults = { tab: 0, whatsnew: null, onboard: null, skills: [],
                       decisions: [], skippedSteps: [],
                       tabKeys: ["now", "agents", "memory", "quick", "devtab"],
                       devPanelOn: true }
      var bad = auditVariants(body, ["PanelBody"], defaults, "panel")
      bad = bad.concat(auditVariants(body, ["NowTab", "RunCard"], defaults, "panel",
        function (v) { var o = {}; for (var k in v) o[k] = v[k]; o.tab = 0; return o }))
      finish(bad)
    }

    // every SettingsHost scene (search, offline, unreadable, connectors...)
    function test_settings_window_scenes() {
      host.visible = true
      var defaults = { query: "", values: ({}), saveStates: ({}), errors: ({}),
                       loaded: false, readError: "", offline: false,
                       connectors: [], connectorState: "loading",
                       connectorError: "", connectorRunning: "",
                       connectorErrors: ({}), heard: false, pageError: "",
                       turns: [], suggestions: [], corrections: [],
                       memoryText: "", userText: "", auditText: "",
                       binds: null, cua: null, spendModels: [] }
      finish(auditVariants(host, ["SettingsHost", "SettingsHostMinimum"],
                           defaults, "settings"))
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
      // the search box, the sidebar and the page heading take focus on
      // every page; a page with controls of its own has more
      var chrome = 3
      var bad = []
      for (var i = 0; i < S.SIDEBAR.length; i++) {
        var page = S.SIDEBAR[i]
        var label = "settings/" + page
        host.category = page
        waitForRendering(host)
        var r = audit(host, label)
        bad = bad.concat(r.bad, missed(r.seen, S.SIDEBAR, "cat:", label))
        // floor: every page but the read-only Status pages has a control
        // of its own to focus
        if (S.STATUS_PAGES.indexOf(page) < 0 && r.focusable <= chrome)
          bad.push(label + ": only " + r.focusable + " focusable controls")
      }
      finish(bad)
    }
  }
}
