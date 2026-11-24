import QtQuick
import QtTest
import "../../../shell-plugin/lib/settings.js" as S
import "../../../shell-plugin/components"
import "../harness"

// Panel body (one-surface U2): the page scrolls under a fixed header, a
// hidden tab adds no height, scroll resets on a tab switch, the keys
// scroll; the Quick tab lists every quick field and writes once through
// configSet; "Open settings" from every tab and the health summary; the
// offline, read-failed and failed-write states; banners only on Now.
Item {
  id: root
  width: 480
  height: 360

  FixtureService {
    id: svc
    tokens: ({ canvas: "#101010", surface: "#181818", raised: "#202020",
               keyline: "#303030", keylineStrong: "#505050", ink: "#eeeeee",
               inkMuted: "#999999", accent: "#4488ff", selection: "#223355",
               fail: "#ff5555", ok: "#55ff55", ember: "#ff8800",
               needsYou: "#ffcc00" })
  }

  PanelBody {
    id: body
    service: svc
    width: root.width
    height: root.height
    onPickTab: function (i) { body.tab = i }
  }
  SignalSpy { id: opens; target: body; signalName: "openSettings" }
  SignalSpy { id: dismisses; target: body; signalName: "whatsnewDismiss" }

  TestCase {
    name: "panel"
    when: windowShown

    function init() {
      body.height = root.height
      show(0)
      body.whatsnew = null
      svc.offline = false
      svc.stale = false
      svc.health = ({})
      svc.configLoaded = true
      svc.configReadError = ""
      svc.configValues = ({ "cua.dry_run": "false" })
      svc.configState = ({})
      svc.configErrors = ({})
      svc.configSetCalls = []
      svc.loadConfigCalls = 0
      body.page.scrollTo(0)
      opens.clear()
      dismisses.clear()
      waitForRendering(body)
    }

    // Column layout runs at polish time: let it settle after a switch
    function show(t) {
      body.tab = t
      waitForRendering(body)
    }
    function row(key) { return findChild(body, "row:" + key) }
    function tap(item) {
      body.page.ensureVisible(item)
      waitForRendering(body)
      mouseClick(item)
    }

    function test_tall_page_scrolls_and_header_stays() {
      show(3)
      var page = body.page
      verify(page.contentHeight > page.height, "quick tab taller than the card")
      var chip = findChild(body, "openSettings")
      var before = chip.mapToItem(body, 0, 0).y
      page.scrollTo(page.maxY)
      verify(page.contentY > 0)
      compare(chip.mapToItem(body, 0, 0).y, before)
    }

    function test_hidden_tab_adds_no_height() {
      show(0)
      var now = body.implicitHeight
      show(3)
      var quick = body.implicitHeight
      verify(quick > now, "quick " + quick + " now " + now)
      show(0)
      compare(body.implicitHeight, now)
    }

    function test_tab_switch_resets_scroll() {
      show(3)
      body.page.scrollTo(body.page.maxY)
      verify(body.page.contentY > 0)
      mouseClick(findChild(body, "tab:now"))
      compare(body.tab, 0)
      compare(body.page.contentY, 0)
    }

    function test_keys_scroll_the_page() {
      show(3)
      body.focusPage()
      keyClick(Qt.Key_PageDown)
      verify(body.page.contentY > 0)
      keyClick(Qt.Key_End)
      compare(body.page.contentY, body.page.maxY)
      keyClick(Qt.Key_Home)
      compare(body.page.contentY, 0)
    }

    function test_quick_tab_shows_every_quick_field() {
      show(3)
      var n = 0
      for (var i = 0; i < S.FIELDS.length; i++) {
        if (!S.FIELDS[i].quick) continue
        verify(row(S.FIELDS[i].key) !== null, S.FIELDS[i].key)
        n++
      }
      verify(n >= 10)
      compare(row("hotkey.key"), null)   // not a quick field
    }

    function test_toggle_writes_once_through_config_set() {
      show(3)
      tap(row("cua.dry_run").control)
      compare(svc.configSetCalls.length, 1)
      compare(svc.configSetCalls[0].key, "cua.dry_run")
      compare(svc.configSetCalls[0].value, "true")
    }

    function test_open_settings_from_every_tab_and_the_summary() {
      for (var t = 0; t < 4; t++) {
        show(t)
        mouseClick(findChild(body, "openSettings"))
      }
      compare(opens.count, 4)
      show(3)
      tap(findChild(body, "healthSummary"))
      compare(opens.count, 5)
    }

    function test_health_summary_words() {
      show(3)
      var word = findChild(body, "healthWord")
      compare(word.text, svc.ui("ui.bar.ok"))
      svc.health = ({ jev: { ok: false }, stt: { ok: false }, cua: { ok: true } })
      compare(word.text, "2 " + svc.ui("ui.bar.down"))
      svc.offline = true
      compare(word.text, svc.wordView.word)
    }

    function test_offline_keeps_fields_enabled_with_a_note() {
      show(3)
      svc.offline = true
      waitForRendering(body)
      verify(findChild(body, "offlineNote").visible)
      verify(row("cua.dry_run").control.enabled)
      tap(row("cua.dry_run").control)
      compare(svc.configSetCalls.length, 1)
    }

    function test_loading_line_until_config_arrives() {
      show(3)
      svc.configLoaded = false
      verify(findChild(body, "loadingLine").visible)
      compare(row("cua.dry_run"), null)
      svc.configLoaded = true
      verify(!findChild(body, "loadingLine").visible)
      verify(row("cua.dry_run") !== null)
    }

    function test_read_failed_shows_retry_and_hides_fields() {
      show(3)
      svc.configReadError = "config.toml: bad line 3"
      waitForRendering(body)
      verify(findChild(body, "readError").visible)
      compare(row("cua.dry_run"), null)
      tap(findChild(body, "retry"))
      compare(svc.loadConfigCalls, 1)
    }

    function test_failed_write_shows_error_and_keeps_saved_value() {
      show(3)
      svc.configState = ({ "cua.dry_run": "error" })
      svc.configErrors = ({ "cua.dry_run": "The daemon rejected it: no." })
      var r = row("cua.dry_run")
      compare(findChild(r, "strip").text, "The daemon rejected it: no.")
      compare(r.control.checked, false)
    }

    function test_banners_only_on_now() {
      body.whatsnew = ({ title: "v1", date: "", lines: ["a line"], more: 0, url: "" })
      show(0)
      var card = findChild(body, "whatsnewTitle")
      verify(card !== null)
      verify(findChild(body, "nowPage").visible)
      show(1)
      verify(!findChild(body, "nowPage").visible)
      show(0)
      tap(findChild(body, "whatsnewDismiss"))
      compare(dismisses.count, 1)
    }
  }
}
