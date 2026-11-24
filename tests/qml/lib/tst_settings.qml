import QtQuick
import QtTest
import "../../../shell-plugin/lib/settings.js" as S
import "../../../shell-plugin/lib/health.js" as H

// Settings editor (W22): validation, the `wispd config set` argv, stderr
// parsing, the Panel's quick groups and the health rows. The Panel's
// Quick tab itself is tested in tst_panel.qml.
TestCase {
  name: "settings"
  width: 400
  height: 400
  when: windowShown

  function test_validate_budget() {
    compare(S.validate("budget.daily_usd", "2.50"), "")
    compare(S.validate("budget.daily_usd", ""), "")
    compare(S.validate("budget.daily_usd", " 3 "), "")
    compare(S.validate("budget.daily_usd", "two"), "ui.err.number")
    compare(S.validate("budget.daily_usd", "-1"), "ui.err.number")
    compare(S.validate("budget.daily_usd", "1e3"), "ui.err.number")
    compare(S.validate("budget.daily_usd", "999999"), "ui.err.range")
    compare(S.validate("budget.monthly_usd", "5#"), "ui.err.chars")
  }

  function test_validate_cua_and_pointer() {
    compare(S.validate("cua.max_per_turn", "12"), "")
    compare(S.validate("cua.max_per_turn", "0"), "ui.err.range")
    compare(S.validate("cua.max_per_turn", "900"), "ui.err.range")
    compare(S.validate("cua.max_clicks_per_min", "x"), "ui.err.number")
    compare(S.validate("cua.dry_run", "true"), "")
    compare(S.validate("cua.dry_run", "yes"), "ui.err.choice")
    compare(S.validate("pointer.mode", "drive"), "")
    compare(S.validate("pointer.mode", "fly"), "ui.err.choice")
    compare(S.validate("cua.confirm", "always"), "")
    compare(S.validate("keys.submap", "x"), "ui.err.choice")   // every schema key validates
    compare(S.validate("keys.submap", "true"), "")
    compare(S.validate("hotkey.mod", "SUPER"), "")
    compare(S.validate("brain.default", "ollama:lfm2-vl"), "")
    compare(S.validate("brain.default", "no-colon"), "ui.err.format")
    compare(S.validate("made.up_key", "x"), "ui.err.unknown")
  }

  function test_command_and_parsing() {
    compare(S.setCommand("/bin/wispd", "budget.daily_usd", " 3.00 "),
            ["/bin/wispd", "config", "set", "budget.daily_usd", "3.00"])
    compare(S.errorText("E_BAD_CONFIG: The daemon rejected it: nope.\nTry: wispd config show"),
            "The daemon rejected it: nope.")
    compare(S.errorText("plain failure"), "plain failure")
    var flat = S.flatten({ data: { config: { budget: { daily_usd: "2.00" },
      cua: { dry_run: "false", nested: {} } } } })
    compare(flat["budget.daily_usd"], "2.00")
    compare(flat["cua.dry_run"], "false")
    compare(flat["cua.nested"], undefined)
  }

  function test_every_field_has_a_group() {
    var seen = {}
    for (var i = 0; i < S.FIELDS.length; i++) seen[S.FIELDS[i].key] = true
    verify(seen["budget.daily_usd"] && seen["budget.monthly_usd"])
    verify(seen["cua.dry_run"] && seen["cua.kill_switch"])
    compare(S.group("budget").length, 2)   // the Panel only sees quick fields
    compare(S.group("hotkey").length, 0)
  }




  function test_health_sections() {
    var s = H.sections({ jev: { ok: false, code: "jev_down" }, stt: { ok: true },
      cua: { ok: true }, spend: { ok: false, code: "budget_exceeded" },
      brain_ollama: { ok: true, latency_ms: 40 } })
    compare(s.endpoints.length, 2)
    compare(s.errors.length, 2)
    verify(s.stt.ok)
    var sp = H.spendView({ today_usd: 2, cap_usd: 2, month_usd: 5, monthly_cap_usd: null, blocked: true })
    compare(sp.today, "$2.00")
    compare(sp.monthCap, "")
    compare(sp.ratio, 1)
    verify(sp.blocked)
    compare(H.cuaView(null), null)
    compare(H.cuaView({ state: "dry_run", dry_run: true }).dryRun, true)
  }
}
