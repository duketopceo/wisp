import QtQuick
import QtTest
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../../../shell-plugin/lib/metrics.js" as M
import "../../../shell-plugin/components"
import "../harness"

// Bar pill (U3) against the harness service: states by fixture, the error
// that persists, the done rating window (collapses when the service's
// single-shot timer fires, paused by hover), and the thumbs rating the turn.
TestCase {
  id: tc
  name: "bar_pill"
  when: windowShown
  width: 480
  height: 200

  FixtureService { id: svc }
  property var tokens: Tokens.load("", "", "dark").tokens

  function readJson(name) {
    var x = new XMLHttpRequest();
    x.open("GET", Qt.resolvedUrl("../../fixtures/states/" + name + ".json"), false);
    x.send();
    return JSON.parse(x.responseText);
  }

  function loadFx(name, mods) {
    var raw = readJson(name);
    var m = raw._fixture || {};
    delete raw._fixture;
    for (var k in (mods || {})) m[k] = mods[k];
    svc.tokens = tokens;
    svc.load(raw, m);
  }

  function find(item, name) {
    if (item.objectName === name) return item;
    for (var i = 0; i < item.children.length; i++) {
      var r = find(item.children[i], name);
      if (r) return r;
    }
    return null;
  }

  function mk(props) {
    var o = { service: svc };
    for (var k in (props || {})) o[k] = props[k];
    var p = createTemporaryObject(comp, tc, o);
    verify(p !== null);
    return p;
  }

  function init() { svc.pillHover = false; svc.labelCalls = []; svc.textScale = 1; }
  function cleanup() { svc.textScale = 1; }

  function test_idle_and_offline_collapse_to_nothing() {
    loadFx("idle");
    var p = mk();
    compare(p.implicitWidth, 0);
    compare(p.info.kind, "idle");
    loadFx("offline");
    compare(p.implicitWidth, 0);
    compare(p.info.kind, "offline");
  }

  function test_words_for_each_busy_state() {
    var rows = [["listening", "listening"], ["transcribing", "hearing"], ["deciding", "thinking"],
      ["speaking", "speaking"], ["acting", "working"],
      ["awaiting_choice", "your call"], ["error", "that failed"]];
    for (var i = 0; i < rows.length; i++) {
      loadFx(rows[i][0]);
      var p = mk();
      verify(p.implicitWidth > 0, rows[i][0]);
      compare(find(p, "word").text, rows[i][1], rows[i][0]);
      p.destroy();
    }
  }

  function test_error_names_a_cause_and_persists_past_the_old_hold() {
    loadFx("error");
    var p = mk();
    compare(find(p, "cause").text, "model");
    wait(3000);
    compare(p.info.kind, "error");
    verify(p.implicitWidth > 0);
    // the next turn clears it
    loadFx("listening");
    compare(p.info.kind, "listening");
  }

  function test_done_window_collapses_when_the_service_timer_fires() {
    loadFx("done");
    var p = mk();
    verify(svc.ratingWindowOpen);
    compare(p.info.kind, "done");
    verify(find(p, "thumbUp") !== null);
    verify(p.info.thumbs);
    verify(svc.ratingTimer.running);
    svc.ratingTimer.triggered();
    verify(!svc.ratingWindowOpen);
    compare(p.info.kind, "idle");
    compare(p.implicitWidth, 0);
  }

  function test_hover_pauses_the_window() {
    loadFx("done");
    var p = mk();
    verify(svc.ratingTimer.running);
    svc.pillHover = true;
    verify(!svc.ratingTimer.running);
    svc.pillHover = false;
    verify(svc.ratingTimer.running);
    compare(svc.ratingTimer.interval, 8000);
    verify(!svc.ratingTimer.repeat);
  }

  function test_new_turn_stops_the_window_and_timer() {
    loadFx("done");
    var p = mk();
    verify(svc.ratingTimer.running);
    loadFx("listening");
    verify(!svc.ratingWindowOpen);
    verify(!svc.ratingTimer.running);
  }

  function test_no_window_offline_or_for_a_cancelled_turn() {
    loadFx("done", { offline: true });
    verify(!svc.ratingWindowOpen);
    loadFx("done", { patch: { result: "CANCELLED" } });
    verify(!svc.ratingWindowOpen);
    var p = mk();
    verify(!p.info.thumbs);
  }

  function test_thumbs_rate_this_turn_with_accessible_names() {
    loadFx("done");
    var p = mk();
    var up = find(p, "thumbUp"), down = find(p, "thumbDown");
    verify(up !== null && down !== null);
    compare(up.Accessible.name, "good");
    compare(down.Accessible.name, "wrong");
    up.activate();
    compare(svc.labelCalls.length, 1);
    compare(svc.labelCalls[0].verdict, "correct");
    compare(svc.labelCalls[0].turn, "t-done");
    down.activate();
    compare(svc.labelCalls[1].verdict, "incorrect");
  }

  function test_listening_waveform_follows_the_mic_level() {
    loadFx("listening", { patch: { level: 1 } });
    var p = mk();
    var hi = find(p, "bar2").height;
    loadFx("listening", { patch: { level: 0 } });
    verify(hi > find(p, "bar2").height);
  }

  function test_word_follows_text_scale_and_the_thumbs_do_not() {
    loadFx("done");
    var p = mk({ barHeight: 40 });
    compare(find(p, "word").font.pixelSize, M.fontSize("label", 1));
    var thumb = find(p, "thumbUp").width;
    svc.textScale = 1.25;
    compare(find(p, "word").font.pixelSize, M.fontSize("label", 1.25));
    compare(find(p, "thumbUp").width, thumb);
  }

  function test_pill_stays_inside_the_bar_at_text_scale_2() {
    var rows = ["acting", "error", "done", "awaiting_choice"];
    for (var i = 0; i < rows.length; i++) {
      svc.textScale = 2;
      loadFx(rows[i]);
      var p = mk({ barHeight: 28 });
      var pill = find(p, "pill");
      verify(pill.height <= 28, rows[i] + " pill " + pill.height);
      var word = find(p, "word");
      verify(word.implicitHeight <= pill.height, rows[i] + " word " + word.implicitHeight);
      verify(word.font.pixelSize > M.fontSize("label", 1), rows[i] + " grew");
      p.destroy();
    }
  }

  Component { id: comp; BarPill { } }
}
