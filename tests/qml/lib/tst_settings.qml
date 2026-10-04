import QtQuick
import QtTest
import "../../../shell-plugin/lib/settings.js" as S
import "../../../shell-plugin/lib/health.js" as H
import "../../../shell-plugin/components"
import "../harness"

// Settings editor (W22): validation, the `wispd config set` argv, stderr
// parsing, and SettingsTab against a mock service (the harness
// FixtureService): choice chips and the save chip emit save(key, value),
// invalid drafts show an inline error and cannot be saved.
TestCase {
  name: "settings"
  width: 400
  height: 400
  when: windowShown

  FixtureService { id: svc }

  SignalSpy { id: saves; target: tab; signalName: "save" }
  SettingsTab {
    id: tab
    service: svc
    width: 360
    values: ({ "budget.daily_usd": "2.00", "cua.dry_run": "false",
               "cua.max_per_turn": "12", "pointer.mode": "guide" })
  }

  function init() { saves.clear(); tab.draft = ({}); tab.errors = ({}) }

  function find(item, name) {
    if (item.objectName === name) return item
    var kids = item.children
    for (var i = 0; i < kids.length; i++) {
      var r = find(kids[i], name)
      if (r) return r
    }
    return null
  }

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
    compare(S.validate("keys.submap", "x"), "ui.err.unknown")
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
    compare(S.group("budget").length, 2)
  }

  function test_choice_chip_saves_immediately() {
    var chip = find(tab, "opt:pointer.mode:drive")
    verify(chip !== null)
    chip.clicked()
    compare(saves.count, 1)
    compare(saves.signalArguments[0][0], "pointer.mode")
    compare(saves.signalArguments[0][1], "drive")
  }

  function test_text_edit_saves_only_when_valid_and_changed() {
    var chip = find(tab, "save:budget.daily_usd")
    verify(chip !== null)
    verify(!chip.enabled)               // not edited yet
    tab.setDraft("budget.daily_usd", "two")
    verify(!chip.enabled)               // invalid
    compare(tab.problem("budget.daily_usd"), "enter a plain number")
    tab.setDraft("budget.daily_usd", "3.50")
    verify(chip.enabled)
    compare(tab.problem("budget.daily_usd"), "")
    chip.clicked()
    compare(saves.signalArguments[0][0], "budget.daily_usd")
    compare(saves.signalArguments[0][1], "3.50")
  }

  function test_daemon_error_shows_inline() {
    tab.errors = { "budget.daily_usd": "The daemon rejected it: bad." }
    compare(tab.problem("budget.daily_usd"), "The daemon rejected it: bad.")
    // a draft error wins over a stale daemon error
    tab.setDraft("budget.daily_usd", "x")
    compare(tab.problem("budget.daily_usd"), "enter a plain number")
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
