import QtQuick
import QtTest
import "../../../shell-plugin/lib/settings.js" as S
import "../../../shell-plugin/components"
import "../harness"

// Settings window body (overhaul U4, U5): the sidebar lists every schema
// category, a click or Up/Down picks one (emitting picked), unknown names
// are ignored, and the page shows that category's rows. Search replaces the
// page with chip-tagged rows and dims the sidebar; Ctrl+F and Esc; the
// loading, offline, could-not-read and empty states; writes leave as
// commit(key, value) in schema format; connector rows; minimum window size.
// One-surface U3: the sidebar also holds the management pages before the
// categories and the Status group after them; Home is the default, a page
// key never names a category, Up/Down walk the whole order, a page change
// focuses the page heading, and page actions leave as signals.
Item {
  id: root
  width: 960
  height: 700

  FixtureService {
    id: svc
    tokens: ({ canvas: "#101010", raised: "#202020", keyline: "#303030",
               keylineStrong: "#505050", ink: "#eeeeee", inkMuted: "#999999",
               accent: "#4488ff", selection: "#223355", fail: "#ff5555",
               ok: "#55ff55" })
  }

  SettingsHost { id: host; service: svc; anchors.fill: parent }
  SignalSpy { id: picks; target: host; signalName: "picked" }
  SignalSpy { id: commits; target: host; signalName: "commit" }
  SignalSpy { id: retries; target: host; signalName: "retry" }
  SignalSpy { id: connRetries; target: host; signalName: "retryConnectors" }
  SignalSpy { id: connects; target: host; signalName: "connectAlias" }
  SignalSpy { id: restarts; target: host; signalName: "restart" }
  SignalSpy { id: stops; target: host; signalName: "stop" }
  SignalSpy { id: pageRetries; target: host; signalName: "retryPage" }
  SignalSpy { id: tasksStarted; target: host; signalName: "startTask" }
  SignalSpy { id: tasksCancelled; target: host; signalName: "cancelTask" }
  SignalSpy { id: saves; target: host; signalName: "saveMemory" }

  TestCase {
    name: "settingshost"
    when: windowShown

    function init() {
      root.width = 960; root.height = 700
      host.clearSearch()
      host.category = S.CATEGORIES[0]
      host.values = ({}); host.saveStates = ({}); host.errors = ({})
      host.loaded = true; host.readError = ""; host.offline = false
      host.connectors = []; host.connectorState = "loading"; host.connectorError = ""
      host.connectorRunning = ""; host.connectorErrors = ({})
      page().contentY = 0
      host.heard = true; host.pageError = ""
      svc.load({ status: "idle", tasks: {} }, {})
      picks.clear(); commits.clear(); retries.clear(); connRetries.clear(); connects.clear()
      restarts.clear(); stops.clear(); pageRetries.clear(); tasksStarted.clear()
      tasksCancelled.clear(); saves.clear()
    }

    function page() { return find(host, "page") }
    // scroll the item into view first, so focus moving to it mid-click
    // cannot scroll the page under the pointer
    function tap(item) {
      page().ensureVisible(item)
      waitForRendering(host)
      mouseClick(item)
    }
    function row(key) { return find(host, "row:" + key) }
    function search() { return find(host, "search") }
    function rowCount() {
      var n = 0
      var rows = S.search(host.query)
      var cat = S.categoryFields(host.category)
      var want = host.query === "" ? cat : rows
      for (var i = 0; i < want.length; i++) if (row(want[i].key)) n++
      return n
    }
    function type(text) {
      search().forceActiveFocus()
      for (var i = 0; i < text.length; i++) keyClick(text[i])
    }

    function find(item, name) {
      if (item.objectName === name) return item
      for (var i = 0; i < item.children.length; i++) {
        var r = find(item.children[i], name)
        if (r) return r
      }
      return null
    }

    function test_sidebar_lists_every_category() {
      for (var i = 0; i < S.CATEGORIES.length; i++)
        verify(find(host, "cat:" + S.CATEGORIES[i]), S.CATEGORIES[i])
    }

    function test_click_picks_a_category() {
      mouseClick(find(host, "cat:budget"))
      compare(host.category, "budget")
      compare(picks.count, 1)
      compare(picks.signalArguments[0][0], "budget")
    }

    function test_arrow_keys_move_and_stop_at_the_ends() {
      host.category = S.SIDEBAR[0]
      find(host, "sidebar").forceActiveFocus()
      keyClick(Qt.Key_Up)
      compare(host.category, S.SIDEBAR[0])
      keyClick(Qt.Key_Down)
      compare(host.category, S.SIDEBAR[1])
      // the whole order: pages, categories, then the Status group
      for (var i = 0; i < S.SIDEBAR.length + 2; i++) keyClick(Qt.Key_Down)
      compare(host.category, S.SIDEBAR[S.SIDEBAR.length - 1])
      compare(picks.count, S.SIDEBAR.length - 1)
    }

    // --- management and Status pages (one-surface U3) ------------------

    function managePage() { return find(host, "managePage") }

    function test_default_entry_is_home() {
      var fresh = Qt.createComponent("../../../shell-plugin/components/SettingsHost.qml")
        .createObject(root, { service: svc, visible: false })
      compare(fresh.category, "home")
      compare(S.startPage(""), "home")
      compare(S.startPage("nope"), "home")
      compare(S.startPage("health"), "health")
      fresh.destroy()
    }

    function test_sidebar_holds_pages_groups_and_categories_in_order() {
      for (var i = 0; i < S.SIDEBAR.length; i++)
        verify(find(host, "cat:" + S.SIDEBAR[i]), S.SIDEBAR[i])
      verify(find(host, "group:settings").visible)
      verify(find(host, "group:status").visible)
      var y = -1
      for (var j = 0; j < S.SIDEBAR.length; j++) {
        var it = find(host, "cat:" + S.SIDEBAR[j])
        var at = it.mapToItem(host, 0, 0).y
        verify(at > y, S.SIDEBAR[j])
        y = at
      }
    }

    function test_tasks_and_agents_open_different_entries() {
      host.select("tasks")
      verify(managePage().visible)
      verify(!page().visible)
      compare(managePage().page, "tasks")
      host.select("agents")
      verify(!managePage().visible)
      verify(page().visible)
      compare(page().category, "agents")
    }

    function test_selecting_health_shows_the_health_page() {
      host.select("health")
      verify(managePage().visible)
      compare(managePage().page, "health")
      compare(find(managePage(), "heading").title, svc.ui("set.cat.health"))
    }

    function test_focus_lands_on_the_page_heading_after_a_page_change() {
      // a click elsewhere: the sidebar keeps focus while arrows walk it
      page().forceActiveFocus()
      host.select("home")
      host.select("activity")
      verify(find(managePage(), "heading").activeFocus)
      // Tab from the sidebar reaches the page heading too
      find(host, "sidebar").forceActiveFocus()
      keyClick(Qt.Key_Tab)
      verify(find(managePage(), "heading").activeFocus)
    }

    function test_page_states_loading_offline_stale_error() {
      host.select("tasks")
      var st = find(managePage(), "pageState")
      host.heard = false
      verify(st.visible)
      compare(st.textKey, "ui.page.loading")
      verify(!find(managePage(), "body").active)
      host.heard = true
      verify(!st.visible)
      verify(find(managePage(), "body").active)
      svc.load({}, { offline: true })
      compare(st.textKey, "ui.page.offline")
      verify(find(managePage(), "body").active)
      waitForRendering(host)
      mouseClick(find(st, "action"))
      compare(pageRetries.count, 1)
      svc.load({ status: "acting", transcript: "x", tasks: {} }, { stale: true })
      compare(st.textKey, "ui.page.stale")
      verify(!find(st, "action").visible)
      host.select("binds")
      host.pageError = "exit"
      compare(st.textKey, "ui.page.error")
      verify(!find(managePage(), "body").active)
    }

    function test_health_and_spend_show_offline_in_their_own_rows() {
      svc.load({}, { offline: true })
      host.select("health")
      verify(!find(managePage(), "pageState").visible)
      host.select("tasks")
      verify(find(managePage(), "pageState").visible)
    }

    function test_restart_and_stop_leave_as_signals() {
      host.select("home")
      waitForRendering(host)
      mouseClick(find(managePage(), "restart"))
      mouseClick(find(managePage(), "stop"))
      compare(restarts.count, 1)
      compare(stops.count, 1)
    }

    function test_tasks_page_starts_and_cancels() {
      svc.load({ status: "idle", tasks: { "sum inbox": { status: "running", task: "sum inbox" },
                                          "old": { status: "done", task: "old" } } }, {})
      host.select("tasks")
      waitForRendering(host)
      var input = find(managePage(), "taskInput")
      input.text = "tidy downloads"
      mouseClick(find(managePage(), "start"))
      compare(tasksStarted.count, 1)
      compare(tasksStarted.signalArguments[0][0], "tidy downloads")
      compare(input.text, "")
      mouseClick(find(find(managePage(), "task:sum inbox"), "cancel"))
      compare(tasksCancelled.count, 1)
      compare(tasksCancelled.signalArguments[0][0], "sum inbox")
      verify(!find(find(managePage(), "task:old"), "cancel").visible)
    }

    function test_memory_save_carries_the_edit() {
      host.memoryText = "a fact"
      host.select("memory")
      waitForRendering(host)
      var note = find(managePage(), "note:memory")
      find(note, "edit").text = "a fact\nanother"
      mouseClick(find(note, "save"))
      compare(saves.count, 1)
      compare(saves.signalArguments[0][0], "memory")
      compare(saves.signalArguments[0][1], "a fact\nanother")
    }

    function test_sidebar_scrolls_to_the_status_group_at_minimum_size() {
      root.width = 720; root.height = 520
      waitForRendering(host)
      var sc = find(host, "sidebarScroll")
      verify(sc.contentHeight > sc.height)
      host.select("binds")
      wait(0)
      var it = find(host, "cat:binds")
      var y = it.mapToItem(sc, 0, 0).y
      verify(y >= 0 && y + it.height <= sc.height + 0.5, "binds in view at " + y)
      host.select("home")
      wait(0)
      compare(sc.contentY, 0)
    }

    function test_audit_with_50_rows_scrolls_at_minimum_size() {
      root.width = 720; root.height = 520
      var lines = []
      for (var i = 0; i < 50; i++)
        lines.push(JSON.stringify({ ts: 1759579200 + i, tool: "click", app: "firefox",
                                    decision: "allow", dry_run: false, result: "OK", ms: 40 + i }))
      host.auditText = lines.join("\n")
      host.select("audit")
      waitForRendering(host)
      var mp = managePage()
      verify(mp.contentHeight > mp.height)
      mp.scrollTo(mp.maxY)
      compare(mp.contentY, mp.maxY)
      // every row fits the page: nothing runs past the right edge
      var view = find(mp, "body").item
      verify(view.appWidth >= 48)
      verify(view.timeWidth + view.decisionWidth + view.appWidth + view.toolWidth + view.msWidth
             + 4 * view.gap <= view.width + 0.5)
    }

    function test_select_ignores_unknown_and_same() {
      host.select("nope")
      host.select(host.category)
      compare(host.category, S.CATEGORIES[0])
      compare(picks.count, 0)
    }

    // --- pages ---------------------------------------------------------

    function test_page_shows_the_selected_categorys_rows() {
      var want = S.categoryFields("voice")
      verify(want.length > 0)
      for (var i = 0; i < want.length; i++) verify(row(want[i].key), want[i].key)
      verify(!row("budget.daily_usd"))
      host.select("budget")
      verify(row("budget.daily_usd"))
      verify(!row("voice.tts_voice"))
    }

    function test_loading_line_until_the_config_read_exits() {
      host.loaded = false
      verify(find(host, "loading").visible)
      verify(!row("voice.tts_voice"))
      host.loaded = true
      verify(!find(host, "loading").visible)
      verify(row("voice.tts_voice"))
    }

    function test_search_replaces_the_page_and_tags_rows_with_chips() {
      host.select("budget")
      type("tts")
      compare(host.query, "tts")
      verify(host.searching)
      verify(row("voice.tts_voice"))
      verify(!row("budget.daily_usd"))
      var chip = find(host, "chip:voice.tts_voice")
      verify(chip.visible)
      compare(chip.label, svc.ui("set.cat.voice"))
      // the sidebar dims; the chosen category stays chosen
      verify(find(host, "sidebar").opacity < 1)
      compare(host.category, "budget")
    }

    function test_no_search_means_no_chips_and_a_full_sidebar() {
      verify(!find(host, "chip:voice.tts_voice").visible)
      compare(find(host, "sidebar").opacity, 1)
    }

    function test_search_with_no_match_shows_the_empty_sentence() {
      type("zzzqqq")
      var empty = find(host, "empty")
      verify(empty.visible)
      compare(empty.text, svc.ui("ui.set.search.empty"))
      compare(rowCount(), 0)
    }

    function test_a_page_without_rows_shows_the_empty_sentence() {
      var p = pageC.createObject(root, { category: "nope", loaded: true })
      var empty = find(p, "empty")
      verify(empty.visible)
      compare(empty.text, svc.ui("ui.set.empty"))
      p.destroy()
    }

    function test_chip_selects_its_category_and_clears_the_search() {
      type("tts")
      tap(find(host, "chip:voice.tts_voice"))
      compare(host.category, "voice")
      compare(host.query, "")
      compare(search().text, "")
      verify(!host.searching)
      verify(row("voice.tts_voice"))
      compare(picks.count, 0)  // voice was already chosen
      host.select("budget")
      type("tts")
      tap(find(host, "chip:voice.tts_voice"))
      compare(host.category, "voice")
      compare(picks.count, 2)
    }

    function test_search_row_edits_in_place() {
      type("dry run")
      var r = row("cua.dry_run")
      verify(r)
      tap(r.control)
      compare(commits.count, 1)
      compare(commits.signalArguments[0][0], "cua.dry_run")
      compare(commits.signalArguments[0][1], "true")
    }

    function test_ctrl_f_focuses_the_search_field() {
      find(host, "sidebar").forceActiveFocus()
      verify(!search().activeFocus)
      keyClick(Qt.Key_F, Qt.ControlModifier)
      verify(search().activeFocus)
    }

    function test_escape_clears_the_search_and_restores_the_category() {
      host.select("budget")
      type("tts")
      verify(host.searching)
      keyClick(Qt.Key_Escape)
      compare(host.query, "")
      compare(search().text, "")
      compare(host.category, "budget")
      verify(row("budget.daily_usd"))
      verify(!row("voice.tts_voice"))
      compare(find(host, "sidebar").opacity, 1)
    }

    function test_escape_outside_the_field_also_clears_the_search() {
      host.select("budget")
      type("tts")
      find(host, "sidebar").forceActiveFocus()
      keyClick(Qt.Key_Escape)
      compare(host.query, "")
      compare(host.category, "budget")
    }

    function test_escape_in_a_result_field_reverts_the_draft_and_keeps_the_search() {
      type("daily")
      var input = find(host, "input:budget.daily_usd")
      verify(input)
      var before = input.text
      input.forceActiveFocus()
      input.selectAll()
      keyClick(Qt.Key_5)
      keyClick(Qt.Key_Escape)
      compare(input.text, before)
      compare(host.query, "daily")
    }

    function test_sidebar_click_leaves_the_search() {
      type("tts")
      mouseClick(find(host, "cat:agents"))
      compare(host.category, "agents")
      compare(host.query, "")
    }

    // --- read states ---------------------------------------------------

    function test_could_not_read_banner_has_retry_and_hides_rows() {
      host.readError = "wispd: command not found"
      var b = find(host, "unreadableBanner")
      verify(b.visible)
      verify(find(b, "retry"))
      compare(b.children[0].text, svc.ui("ui.set.unreadable") + ": wispd: command not found")
      verify(!find(host, "loading").visible)
      compare(rowCount(), 0)
      tap(find(b, "retry"))
      compare(retries.count, 1)
    }

    function test_offline_banner_keeps_rows_editable_and_retries() {
      host.offline = true
      var b = find(host, "offlineBanner")
      verify(b.visible)
      compare(b.children[0].text, svc.ui("ui.set.offline"))
      verify(row("voice.tts_voice"))
      tap(find(b, "retry"))
      compare(retries.count, 1)
      host.offline = false
      verify(!b.visible)
    }

    // --- values and writes ---------------------------------------------

    function test_row_reading_8_shows_8_00_and_no_changed_note() {
      host.select("budget")
      host.values = ({ "budget.daily_usd": "8" })
      var r = row("budget.daily_usd")
      var input = find(r.control, "input:budget.daily_usd")
      compare(input.text, "8.00")
      verify(!find(r, "reset").visible)
      compare(find(r, "strip").text, "")
    }

    function test_act_max_usd_zero_shows_0_00_and_reset_sends_0_00() {
      host.select("agents")
      host.values = ({ "agents.act_max_usd": "0" })
      var r = row("agents.act_max_usd")
      compare(find(r.control, "input:agents.act_max_usd").text, "0.00")
      verify(!find(r, "reset").visible)
      host.values = ({ "agents.act_max_usd": "5.00" })
      verify(find(r, "reset").visible)
      waitForRendering(r)
      tap(find(r, "reset"))
      compare(commits.count, 1)
      compare(commits.signalArguments[0][0], "agents.act_max_usd")
      compare(commits.signalArguments[0][1], "0.00")
    }

    function test_toggle_commits_once_in_schema_format() {
      host.select("pointer")
      host.values = ({ "cua.dry_run": "false" })
      tap(row("cua.dry_run").control)
      compare(commits.count, 1)
      compare(commits.signalArguments[0][0], "cua.dry_run")
      compare(commits.signalArguments[0][1], "true")
    }

    function test_usd_edit_leaves_formatted() {
      host.select("budget")
      var input = find(row("budget.daily_usd").control, "input:budget.daily_usd")
      input.forceActiveFocus()
      input.selectAll()
      keyClick(Qt.Key_9)
      keyClick(Qt.Key_Return)
      compare(commits.count, 1)
      compare(commits.signalArguments[0][1], "9.00")
    }

    function test_saving_key_locks_its_control_and_queued_key_shows_the_strip() {
      host.select("pointer")
      host.saveStates = ({ "cua.dry_run": "saving", "cua.kill_switch": "queued" })
      var saving = row("cua.dry_run")
      var queued = row("cua.kill_switch")
      verify(!saving.control.enabled)
      verify(!queued.control.enabled)
      compare(find(saving, "strip").text, svc.ui("ui.set.saving"))
      compare(find(queued, "strip").text, svc.ui("ui.set.saving"))
      tap(saving.control)
      tap(queued.control)
      compare(commits.count, 0)
      // another key is untouched
      verify(row("pointer.mode").control.enabled)
      host.saveStates = ({ "cua.dry_run": "saved" })
      verify(saving.control.enabled)
      compare(find(saving, "strip").text, svc.ui("ui.set.saved"))
    }

    function test_daemon_error_appears_on_that_row() {
      host.select("pointer")
      host.saveStates = ({ "cua.dry_run": "error" })
      host.errors = ({ "cua.dry_run": "The daemon rejected it: nope." })
      compare(find(row("cua.dry_run"), "strip").text, "The daemon rejected it: nope.")
      compare(find(row("cua.kill_switch"), "strip").text, "")
    }

    // --- connectors ----------------------------------------------------

    function test_connectors_page_lists_browser_rows_then_connectors() {
      host.select("connectors")
      host.connectorState = "ready"
      host.connectors = [{ alias: "github", name: "GitHub", connected: true },
                         { alias: "notion", name: "Notion", connected: false }]
      verify(row("browser.lane"))
      verify(row("browser.port"))
      var gh = find(host, "connector:github")
      var nt = find(host, "connector:notion")
      verify(gh && nt)
      compare(find(gh, "name").text, "GitHub")
      compare(find(gh, "status").text, svc.ui("ui.set.conn.on"))
      compare(find(nt, "status").text, svc.ui("ui.set.conn.off"))
      verify(!find(gh, "connect:github").visible)
      verify(find(nt, "connect:notion").visible)
      waitForRendering(host)
      verify(row("browser.port").mapToItem(page(), 0, 0).y < nt.mapToItem(page(), 0, 0).y)
    }

    function test_connect_runs_per_row_and_disables_while_running() {
      host.select("connectors")
      host.connectorState = "ready"
      host.connectors = [{ alias: "notion", name: "Notion", connected: false },
                         { alias: "linear", name: "Linear", connected: false }]
      var b = find(host, "connect:notion")
      compare(b.label, svc.ui("ui.set.conn.go"))
      tap(b)
      compare(connects.count, 1)
      compare(connects.signalArguments[0][0], "notion")
      host.connectorRunning = "notion"
      compare(b.label, svc.ui("ui.set.conn.running"))
      verify(!b.enabled)
      compare(find(host, "connect:linear").label, svc.ui("ui.set.conn.go"))
      verify(!find(host, "connect:linear").enabled)
      tap(b)
      compare(connects.count, 1)
      host.connectorRunning = ""
      verify(b.enabled)
    }

    function test_connect_failure_shows_the_sentence_on_that_row() {
      host.select("connectors")
      host.connectorState = "ready"
      host.connectors = [{ alias: "notion", name: "Notion", connected: false },
                         { alias: "linear", name: "Linear", connected: false }]
      host.connectorErrors = ({ "notion": "The gateway refused the sign in." })
      var p = find(find(host, "connector:notion"), "problem")
      verify(p.visible)
      compare(p.text, "The gateway refused the sign in.")
      verify(!find(find(host, "connector:linear"), "problem").visible)
    }

    function test_connector_list_states() {
      host.select("connectors")
      host.connectorState = "loading"
      verify(find(host, "connectorsLoading").visible)
      verify(!find(host, "connectorsEmpty").visible)
      host.connectorState = "failed"
      host.connectorError = "E_GATEWAY: no route"
      var f = find(host, "connectorsFailed")
      verify(f.visible)
      verify(!find(host, "connectorsLoading").visible)
      tap(find(f, "retry"))
      compare(connRetries.count, 1)
      host.connectorState = "ready"
      host.connectors = []
      verify(find(host, "connectorsEmpty").visible)
      compare(find(host, "connectorsEmpty").text, svc.ui("ui.set.conn.empty"))
      verify(!f.visible)
    }

    function test_connectors_list_is_hidden_on_other_pages_and_in_search() {
      host.connectorState = "failed"
      verify(!find(host, "connectorsFailed").visible)
      host.select("connectors")
      verify(find(host, "connectorsFailed").visible)
      type("tts")
      verify(!find(host, "connectorsFailed").visible)
    }

    // --- minimum size ----------------------------------------------------

    function texts(item, out) {
      if (item.visible === false) return out
      if (item.text !== undefined && item.contentWidth !== undefined && item.text !== "") out.push(item)
      for (var i = 0; i < item.children.length; i++) texts(item.children[i], out)
      return out
    }

    function test_no_horizontal_clipping_at_minimum_size() {
      root.width = 720
      root.height = 520
      host.connectorState = "ready"
      host.connectors = [{ alias: "a-long-connector-alias", name: "A rather long connector name", connected: false }]
      host.connectorErrors = ({ "a-long-connector-alias": "A long error sentence that has to wrap on a narrow page." })
      host.offline = true
      for (var c = 0; c < S.CATEGORIES.length; c++) {
        host.select(S.CATEGORIES[c])
        waitForRendering(host)
        var pg = page()
        compare(pg.contentWidth, pg.width)
        var all = texts(pg, [])
        verify(all.length > 0)
        for (var i = 0; i < all.length; i++) {
          var t = all[i]
          var left = t.mapToItem(pg, 0, 0).x
          var tag = S.CATEGORIES[c] + ": " + t.text
          verify(left >= 0, tag)
          verify(left + t.width <= pg.width + 0.5, tag)
          // wrapped text never needs more than its width; elided text is
          // only the connector name line
          if (t.elide === Text.ElideNone) verify(t.contentWidth <= t.width + 0.5, tag)
        }
      }
    }
  }

  Component { id: pageC; SettingsPage { service: svc; width: 700; height: 500 } }
}
