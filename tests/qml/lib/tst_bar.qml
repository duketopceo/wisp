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
      "ui.bar.spend": "today", "ui.bar.turns": "turns", "ui.bar.turn": "turn",
      "ui.bar.voice": "voice", "ui.bar.hint": "click talk · middle stop · right panel",
      "ui.bar.hint.offline": "hint off" }
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

  function test_tooltip_health_spend_turns_voice_and_mouse_map() {
    var view = { health: { jev: { ok: true }, cua: { ok: false, code: "no_display" },
      stt: { ok: true } }, raw: { spend: { today_usd: 0.1234, cap_usd: 5, turns_today: 4 } } }
    var l = B.tooltipLines(view, { word: "ready", notice: "", stale: false,
      offline: false, voice: "hannah", ui: ui })
    compare(l[0], "wisp: ready")
    compare(l[1], "cua down (no_display)")
    compare(l[2], "jev ok")
    compare(l[3], "stt ok")
    compare(l[4], "today $0.12 · 4 turns")
    compare(l[5], "voice hannah")
    compare(l[6], "click talk · middle stop · right panel")
    compare(l.length, 7)
  }

  function test_tooltip_one_turn_and_no_turn_count() {
    var one = B.tooltipLines({ health: {}, raw: { spend: { today_usd: 1, turns_today: 1 } } },
      { word: "ready", notice: "", offline: false, ui: ui })
    compare(one[1], "today $1.00 · 1 turn")
    var none = B.tooltipLines({ health: {}, raw: { spend: { today_usd: 1 } } },
      { word: "ready", notice: "", offline: false, ui: ui })
    compare(none[1], "today $1.00")
  }

  function test_tooltip_degrades_without_health_spend_or_voice() {
    var l = B.tooltipLines({ health: {}, raw: {} }, { word: "ready", notice: "",
      stale: false, offline: false, ui: ui })
    compare(l.length, 2)
    l = B.tooltipLines({ health: null, raw: null }, { word: "ready", notice: "",
      stale: false, offline: false, ui: ui })
    compare(l.length, 2)
  }

  function test_offline_hides_rows_and_stale_keeps_them() {
    var view = { health: { jev: { ok: true } }, raw: { spend: { today_usd: 1 } } }
    var off = B.tooltipLines(view, { word: "offline", notice: "wisp is not running",
      stale: false, offline: true, ui: ui })
    compare(off, ["wisp: offline", "wisp is not running", "hint off"])
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

  // ---- pill state map (U3) -------------------------------------------
  function ps(o) {
    var base = { status: "idle", result: "", errorCode: "", offline: false,
      confirm: false, windowOpen: false, rateable: false, run: null }
    for (var k in o) base[k] = o[k]
    return B.pillState(base)
  }

  // dev session badge (U5): idle shows it alone, live states keep their pill
  function test_dev_badge_only_while_the_session_is_on() {
    verify(!ps({ status: "idle" }).visible)
    verify(!ps({ status: "idle" }).dev)
    var idle = ps({ status: "idle", dev: true })
    verify(idle.visible); verify(idle.dev); compare(idle.glyph, ""); compare(idle.wordKey, "")
    var act = ps({ status: "acting", dev: true })
    compare(act.kind, "acting"); verify(act.dev)
    verify(!ps({ status: "acting" }).dev)
    var err = ps({ status: "error", errorCode: "timeout", dev: true })
    compare(err.border, "fail"); verify(err.dev)
    verify(!ps({ offline: true, dev: true }).visible)
  }

  function test_every_status_maps_to_a_state_word_and_token() {
    var rows = [
      [{ status: "idle" }, "idle", "", false],
      [{ status: "suggestion" }, "idle", "", false],
      [{ status: "listening" }, "listening", "ui.bar.state.listening", true],
      [{ status: "transcribing" }, "thinking", "ui.bar.state.thinking", true],
      [{ status: "deciding" }, "thinking", "ui.bar.state.thinking", true],
      [{ status: "speaking" }, "speaking", "ui.bar.state.speaking", true],
      [{ status: "acting" }, "acting", "ui.bar.state.acting", true],
      [{ status: "awaiting_choice" }, "needsYou", "ui.bar.state.needs", true],
      [{ status: "acting", confirm: true }, "needsYou", "ui.bar.state.needs", true],
      [{ status: "done", result: "BLOCKED: policy" }, "needsYou", "ui.bar.state.needs", true],
      [{ status: "error", errorCode: "jev_down" }, "error", "ui.bar.state.error", true],
      [{ status: "offline", offline: true }, "offline", "", false],
      [{ status: "done" }, "idle", "", false]
    ]
    for (var i = 0; i < rows.length; i++) {
      var s = ps(rows[i][0])
      compare(s.kind, rows[i][1], JSON.stringify(rows[i][0]))
      compare(s.wordKey, rows[i][2], JSON.stringify(rows[i][0]))
      compare(s.visible, rows[i][3], JSON.stringify(rows[i][0]))
    }
  }

  function test_glyphs_and_tokens() {
    compare(ps({ status: "listening" }).glyph, "waveform")
    compare(ps({ status: "deciding" }).glyph, "arc")
    compare(ps({ status: "speaking" }).glyph, "triangle")
    compare(ps({ status: "acting" }).glyph, "act")
    compare(ps({ status: "awaiting_choice" }).glyph, "warning")
    compare(ps({ status: "error", errorCode: "x" }).glyph, "cross")
    compare(ps({ status: "listening" }).token, "ember")
    compare(ps({ status: "awaiting_choice" }).token, "needsYou")
    compare(ps({ status: "awaiting_choice" }).border, "needsYou")
    compare(ps({ status: "awaiting_choice" }).wordToken, "needsYou")
    compare(ps({ status: "error", errorCode: "x" }).border, "fail")
    compare(ps({ status: "error", errorCode: "x" }).wordToken, "fail")
    compare(ps({ status: "acting" }).border, "keyline")
  }

  function test_acting_step_count_only_when_known() {
    compare(ps({ status: "acting", run: { steps: 4, stepAt: 2 } }).step, "2/4")
    compare(ps({ status: "acting", run: { steps: 0, stepAt: 0 } }).step, "")
    compare(ps({ status: "acting" }).step, "")
    compare(ps({ status: "listening", run: { steps: 4, stepAt: 2 } }).step, "")
  }

  function test_error_carries_one_cause_word() {
    compare(ps({ status: "error", errorCode: "jev_down" }).cause, "model")
    compare(ps({ status: "error", errorCode: "stt_down" }).cause, "speech")
    compare(ps({ status: "error", errorCode: "internal" }).cause, "")
    compare(ps({ status: "error", errorCode: "" }).cause, "")
    compare(ps({ status: "acting" }).cause, "")
  }

  function test_done_window_shows_check_and_thumbs_only_when_open_and_rateable() {
    var d = ps({ status: "done", windowOpen: true, rateable: true })
    compare(d.kind, "done"); verify(d.visible); verify(d.thumbs)
    compare(d.glyph, "check"); compare(d.token, "ok"); compare(d.wordKey, "ui.bar.state.done")
    verify(!ps({ status: "done", windowOpen: false, rateable: true }).visible)
    var cancelled = ps({ status: "done", windowOpen: true, rateable: false })
    verify(!cancelled.thumbs)
    verify(!cancelled.visible)
    // hidden while offline
    verify(!ps({ status: "done", windowOpen: true, rateable: true, offline: true }).visible)
    // a new turn ends the window even if the flag is still up
    verify(!ps({ status: "listening", windowOpen: true, rateable: true }).thumbs)
  }

  function test_window_action_edges() {
    var w = B.windowAction
    compare(w("speaking", "done", "t1", "t1", false, true), "open")
    compare(w("acting", "done", "t1", "t1", false, true), "open")
    compare(w("done", "done", "t1", "t1", false, true), "keep")
    compare(w("offline", "done", "t1", "t1", false, true), "keep")   // snapshot of an old turn
    compare(w("speaking", "done", "t1", "t1", false, false), "keep")  // cancelled or errored
    compare(w("done", "listening", "t1", "t2", false, false), "close")
    compare(w("done", "done", "t1", "t2", false, true), "close")
    compare(w("speaking", "done", "t1", "t1", true, true), "close")
    compare(B.WINDOW_MS, 8000)
  }

  function test_wave_bars_follow_level() {
    var lo = B.waveBars(0), hi = B.waveBars(1)
    compare(lo.length, 5); compare(hi.length, 5)
    for (var i = 0; i < 5; i++) verify(hi[i] > lo[i])
    verify(hi[2] > hi[0])
    compare(B.waveBars(7).join(), B.waveBars(1).join())
    compare(B.waveBars("x").join(), B.waveBars(0).join())
  }

  function test_dimmed_and_badge() {
    verify(B.dimmed(true, false)); verify(B.dimmed(false, true)); verify(!B.dimmed(false, false))
    verify(!B.badge("awaiting_choice", false)); verify(B.badge("suggestion", false)); verify(B.badge("idle", true)); verify(!B.badge("idle", false))
  }
}
