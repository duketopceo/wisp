import QtQuick
import QtTest
import "../../../shell-plugin/lib/bar.js" as B
import "../../../shell-plugin/components"

// Bar mark (Ember U10): mouse button -> action, tooltip lines, with a mock
// service. BarActions is non-visual and takes any object with
// trigger() and interrupt().
TestCase {
  name: "bar"

  QtObject {
    id: mock
    property int talks: 0
    property int stops: 0
    property bool offline: false
    property int starts: 0
    function startDaemon() { starts += 1 }
    function trigger() { talks += 1 }
    function interrupt() { stops += 1 }
  }

  SignalSpy { id: panelSpy; target: actions; signalName: "panelRequested" }
  BarActions { id: actions; service: mock }

  function init() { mock.talks = 0; mock.stops = 0; mock.starts = 0; mock.offline = false; panelSpy.clear() }

  function test_left_click_starts_the_daemon_while_offline() {
    mock.offline = true
    compare(actions.press(Qt.LeftButton), "start")
    compare(mock.starts, 1); compare(mock.talks, 0)
  }

  function ui(k) {
    var t = { "ui.bar.ok": "ok", "ui.bar.down": "down", "ui.more": "more",
      "ui.bar.spend": "spent today", "ui.bar.hint": "hint", "ui.bar.hint.offline": "hint" }
    return t[k]
  }

  function test_left_click_toggles_listen_only() {
    compare(actions.press(Qt.LeftButton), "talk")
    compare(mock.talks, 1); compare(mock.stops, 0); compare(panelSpy.count, 0)
  }

  function test_middle_click_stops_only() {
    compare(actions.press(Qt.MiddleButton), "stop")
    compare(mock.stops, 1); compare(mock.talks, 0); compare(panelSpy.count, 0)
  }

  function test_right_click_opens_panel_only() {
    compare(actions.press(Qt.RightButton), "panel")
    compare(panelSpy.count, 1); compare(mock.talks, 0); compare(mock.stops, 0)
  }

  function test_other_buttons_do_nothing() {
    compare(actions.press(Qt.BackButton), "")
    compare(actions.press(0), "")
    compare(mock.talks + mock.stops + panelSpy.count, 0)
  }

  function test_no_service_is_safe_and_panel_still_opens() {
    actions.service = null
    compare(actions.press(Qt.LeftButton), "")
    compare(actions.press(Qt.MiddleButton), "")
    compare(actions.press(Qt.RightButton), "panel")
    compare(panelSpy.count, 1)
    actions.service = mock
  }

  function test_button_codes_match_qt() {
    compare(B.LEFT, Qt.LeftButton)
    compare(B.RIGHT, Qt.RightButton)
    compare(B.MIDDLE, Qt.MiddleButton)
  }

  function test_tooltip_health_down_first_with_cua_and_spend() {
    var view = { health: { jev: { ok: true }, cua: { ok: false, code: "no_display" },
      stt: { ok: true } }, raw: { spend: { today_usd: 0.1234, cap_usd: 5 } } }
    var l = B.tooltipLines(view, { word: "ready", notice: "", stale: false,
      offline: false, ui: ui })
    compare(l[0], "wisp: ready")
    compare(l[1], "cua down (no_display)")
    compare(l[2], "jev ok")
    compare(l[3], "stt ok")
    compare(l[4], "spent today $0.12 / $5.00")
    compare(l[5], "hint")
  }

  function test_tooltip_degrades_without_health_cua_or_spend() {
    var l = B.tooltipLines({ health: {}, raw: {} }, { word: "ready", notice: "",
      stale: false, offline: false, ui: ui })
    compare(l.length, 2)
    l = B.tooltipLines({ health: null, raw: null }, { word: "ready", notice: "",
      stale: false, offline: false, ui: ui })
    compare(l.length, 2)
    l = B.tooltipLines({ health: { odd: "x", n: null, j: { ok: true } } }, { word: "ready",
      notice: "", stale: false, offline: false, ui: ui })
    compare(l.length, 3)
  }

  function test_offline_hides_rows_and_stale_keeps_them() {
    var view = { health: { jev: { ok: true } }, raw: { spend: { today_usd: 1 } } }
    var off = B.tooltipLines(view, { word: "offline", notice: "wisp is not running",
      stale: false, offline: true, ui: ui })
    compare(off, ["wisp: offline", "wisp is not running", "hint"])
    var st = B.tooltipLines(view, { word: "working", notice: "out of date",
      stale: true, offline: false, ui: ui })
    compare(st[1], "out of date")
    compare(st[2], "jev ok")
  }

  function test_row_cap() {
    var h = {}
    for (var i = 0; i < 9; i++) h["e" + i] = { ok: true }
    var l = B.tooltipLines({ health: h, raw: {} }, { word: "ready", notice: "",
      stale: false, offline: false, ui: ui })
    compare(l.length, 1 + 6 + 1 + 1)
    compare(l[7], "+3 more")
  }

  function test_dimmed_and_badge() {
    verify(B.dimmed(true, false)); verify(B.dimmed(false, true)); verify(!B.dimmed(false, false))
    verify(!B.badge("awaiting_choice", false)); verify(B.badge("suggestion", false)); verify(B.badge("idle", true)); verify(!B.badge("idle", false))
  }
}
