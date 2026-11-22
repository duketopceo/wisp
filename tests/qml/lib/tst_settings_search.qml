import QtQuick
import QtTest
import "../../../shell-plugin/lib/settings.js" as S
import "../../../shell-plugin/lib/copy.js" as Copy
import "../../../shell-plugin/components"
import "../harness"

// Settings window model (overhaul U5), pure helpers in lib/settings.js:
// search, grouping, value formatting and the one-write-at-a-time queue
// rules the service runs, plus the secret-kind guard.
TestCase {
  name: "settings_search"
  width: 400
  height: 200
  when: windowShown

  FixtureService {
    id: svc
    tokens: ({ canvas: "#101010", raised: "#202020", keyline: "#303030",
               keylineStrong: "#505050", ink: "#eeeeee", inkMuted: "#999999",
               accent: "#4488ff", selection: "#223355", fail: "#ff5555",
               ok: "#55ff55" })
  }

  Component { id: rowC; SettingRow { service: svc; width: 400 } }

  function keys(rows) { return rows.map(function (r) { return r.key }) }

  function test_search_tts_finds_the_voice_row() {
    var rows = S.search("tts")
    verify(keys(rows).indexOf("voice.tts_voice") >= 0)
    var hit = rows.filter(function (r) { return r.key === "voice.tts_voice" })[0]
    compare(hit.category, "voice")
    compare(hit.def.key, "voice.tts_voice")
  }

  function test_search_by_key_returns_the_same_row() {
    var rows = S.search("voice.tts_voice")
    compare(keys(rows), ["voice.tts_voice"])
    compare(rows[0].category, "voice")
  }

  function test_search_no_match_and_empty() {
    compare(S.search("zzzqqq").length, 0)
    compare(S.search("").length, 0)
    compare(S.search("   ").length, 0)
  }

  function test_search_is_case_insensitive_and_needs_every_word() {
    compare(keys(S.search("TTS_VOICE")), ["voice.tts_voice"])
    verify(S.search("daily cap").length >= 1)
    compare(S.search("daily zzzqqq").length, 0)
  }

  function test_search_matches_label_and_help_text() {
    // label text comes from the copy table, not the label key
    var label = Copy.string("ui.set.daily")
    var rows = S.search(label)
    verify(keys(rows).indexOf("budget.daily_usd") >= 0)
    var help = Copy.string(S.field("budget.daily_usd").help)
    verify(keys(S.search(help)).indexOf("budget.daily_usd") >= 0)
  }

  function test_formatValue_by_kind() {
    compare(S.formatValue("budget.daily_usd", "8"), "8.00")
    compare(S.formatValue("budget.daily_usd", "8.5"), "8.50")
    compare(S.formatValue("budget.daily_usd", " 8.00 "), "8.00")
    compare(S.formatValue("agents.act_max_usd", "0"), "0.00")
    compare(S.formatValue("agents.act_max_usd", ""), "")
    compare(S.formatValue("agents.act_max_usd", "abc"), "abc")
    compare(S.formatValue("budget.daily_usd", "8.005"), "8.005")
    compare(S.formatValue("cua.max_per_turn", "012"), "12")
    compare(S.formatValue("cua.max_per_turn", " 12 "), "12")
    compare(S.formatValue("cua.max_per_turn", "x"), "x")
    compare(S.formatValue("cua.dry_run", "true"), "true")
    compare(S.formatValue("cua.dry_run", "False"), "false")
    compare(S.formatValue("cua.dry_run", "maybe"), "maybe")
    compare(S.formatValue("pointer.mode", " drive "), "drive")
    compare(S.formatValue("not.a.key", " x "), "x")
  }

  function test_flatten_formats_values() {
    var flat = S.flatten({ data: { config: { budget: { daily_usd: "8" },
      agents: { act_max_usd: 0 }, cua: { dry_run: true } } } })
    compare(flat["budget.daily_usd"], "8.00")
    compare(flat["agents.act_max_usd"], "0.00")
    compare(flat["cua.dry_run"], "true")
  }

  function test_every_default_is_already_formatted_or_formats_stably() {
    for (var i = 0; i < S.FIELDS.length; i++) {
      var f = S.FIELDS[i]
      if (f.kind === "secret") continue
      var once = S.formatValue(f.key, f.default)
      compare(S.formatValue(f.key, once), once, f.key)
      compare(S.validate(f.key, once), "", f.key)
    }
  }

  function test_every_category_has_rows() {
    var by = S.byCategory()
    for (var i = 0; i < S.CATEGORIES.length; i++) {
      var c = S.CATEGORIES[i]
      verify(by[c] && by[c].length > 0, c)
      compare(S.categoryFields(c).length, by[c].length)
    }
  }

  function test_no_key_is_on_two_pages() {
    var seen = {}
    var by = S.byCategory()
    var total = 0
    for (var c in by)
      for (var i = 0; i < by[c].length; i++) {
        verify(!seen[by[c][i].key], by[c][i].key)
        seen[by[c][i].key] = c
        total++
      }
    compare(total, S.FIELDS.length)
    compare(seen["voice.tts_voice"], "voice")
  }

  function test_models_page_holds_the_model_keys() {
    var k = keys(S.categoryFields("models"))
    verify(k.indexOf("brain.router") >= 0)
    verify(k.indexOf("brain.default") >= 0)
    verify(k.indexOf("brain.fallback") >= 0)
    verify(k.indexOf("ground.vlm_brain") >= 0)
    verify(k.indexOf("brain.allow_paid") >= 0)
    verify(k.indexOf("local.enabled") >= 0)
    verify(k.indexOf("web.search") >= 0)
  }

  function test_secret_kind_renders_no_value() {
    var secret = { key: "keys.demo", kind: "secret", label: "ui.set.secret.set", help: "" }
    var row = rowC.createObject(this, { def: secret, value: "sk-live-123456" })
    waitForRendering(row)
    function texts(item, out) {
      if (item.text !== undefined) out.push(String(item.text))
      for (var i = 0; i < item.children.length; i++) texts(item.children[i], out)
      return out
    }
    var all = texts(row, []).join("|")
    compare(all.indexOf("sk-live-123456"), -1)
    verify(all.indexOf(svc.ui("ui.set.secret.set")) >= 0)
    // and the schema has none that could leak through a page
    for (var i = 0; i < S.FIELDS.length; i++)
      if (S.FIELDS[i].kind === "secret") compare(S.FIELDS[i].default, undefined)
    row.destroy()
  }

  // --- the write queue: one `wispd config set` at a time ------------------

  function test_enqueue_runs_first_write_and_queues_the_rest() {
    var st = { queue: [], states: {} }
    var a = S.enqueueWrite(st.queue, st.states, "cua.dry_run", "true")
    verify(a.accepted)
    compare(a.states["cua.dry_run"], "queued")
    var b = S.enqueueWrite(a.queue, a.states, "agent.autonomy", "guided")
    verify(b.accepted)
    compare(b.queue.length, 2)
    var n1 = S.nextWrite(b.queue, b.states)
    compare(n1.write.key, "cua.dry_run")
    compare(n1.states["cua.dry_run"], "saving")
    compare(n1.states["agent.autonomy"], "queued")
    compare(n1.queue.length, 1)
    var done = S.finishWrite(n1.states, "cua.dry_run", true)
    compare(done["cua.dry_run"], "saved")
    var n2 = S.nextWrite(n1.queue, done)
    compare(n2.write.key, "agent.autonomy")
    compare(n2.write.value, "guided")
    compare(n2.queue.length, 0)
    compare(S.nextWrite(n2.queue, n2.states).write, null)
  }

  function test_write_for_a_queued_or_saving_key_is_ignored() {
    var a = S.enqueueWrite([], {}, "cua.dry_run", "true")
    var again = S.enqueueWrite(a.queue, a.states, "cua.dry_run", "false")
    verify(!again.accepted)
    compare(again.queue.length, 1)
    compare(again.queue[0].value, "true")
    var run = S.nextWrite(a.queue, a.states)
    var third = S.enqueueWrite(run.queue, run.states, "cua.dry_run", "false")
    verify(!third.accepted)
    compare(third.states["cua.dry_run"], "saving")
  }

  function test_queue_keeps_one_entry_per_key_newest_value_wins() {
    var q = S.enqueue([{ key: "a", value: "1" }, { key: "b", value: "2" }], "a", "3")
    compare(q.length, 2)
    compare(q[0].key, "a")
    compare(q[0].value, "3")
  }

  function test_error_state_allows_another_attempt_and_saved_clears() {
    var a = S.enqueueWrite([], {}, "cua.dry_run", "true")
    var run = S.nextWrite(a.queue, a.states)
    var failed = S.finishWrite(run.states, "cua.dry_run", false)
    compare(failed["cua.dry_run"], "error")
    var retry = S.enqueueWrite(run.queue, failed, "cua.dry_run", "true")
    verify(retry.accepted)
    // a new write clears the older "saved" mark
    var ok = S.finishWrite({}, "cua.dry_run", true)
    var next = S.enqueueWrite([], ok, "agent.autonomy", "guided")
    compare(next.states["cua.dry_run"], undefined)
  }
}
