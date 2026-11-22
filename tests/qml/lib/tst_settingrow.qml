import QtQuick
import QtTest
import "../../../shell-plugin/lib/settings.js" as S
import "../../../shell-plugin/components"
import "../harness"

// Settings window controls (overhaul U3) against the harness
// FixtureService: toggle, select, number field, row states and reset,
// focus order and ring, reflow at 720 px and text scale 1.25, and the
// ScrollPage scroll paths.
Item {
  id: root
  width: 900
  height: 600

  FixtureService {
    id: svc
    tokens: ({ canvas: "#101010", raised: "#202020", keyline: "#303030",
               keylineStrong: "#505050", ink: "#eeeeee", inkMuted: "#999999",
               accent: "#4488ff", selection: "#223355", fail: "#ff5555",
               ok: "#55ff55" })
  }

  Column {
    id: stack
    width: 720
    SettingRow { id: toggleRow; service: svc; width: parent.width; def: S.field("cua.dry_run"); value: "false" }
    SettingRow { id: selectRow; service: svc; width: parent.width; def: S.field("agent.autonomy"); value: "autonomous" }
    SettingRow { id: numberRow; service: svc; width: parent.width; def: S.field("cua.max_per_turn"); value: "12" }
  }

  SettingRow { id: usdRow; service: svc; x: 0; y: 450; width: 720; def: S.field("agents.act_max_usd"); value: "0" }
  SignalSpy { id: usdSpy; target: usdRow; signalName: "commit" }

  SearchControl { id: search; service: svc; x: 0; y: 400 }
  SignalSpy { id: searchSpy; target: search; signalName: "search" }

  SignalSpy { id: toggleSpy; target: toggleRow; signalName: "commit" }
  SignalSpy { id: selectSpy; target: selectRow; signalName: "commit" }
  SignalSpy { id: numberSpy; target: numberRow; signalName: "commit" }

  Component {
    id: pageC
    ScrollPage {
      service: svc
      width: 400
      height: 200
      Repeater {
        model: 8
        delegate: Rectangle { width: 300; height: 50; color: svc.tokens.raised }
      }
    }
  }

  TestCase {
  id: tc
  name: "settingrow"
  when: windowShown

  function init() {
    toggleSpy.clear(); selectSpy.clear(); numberSpy.clear(); searchSpy.clear(); usdSpy.clear()
    usdRow.value = "0"; usdRow.saveState = ""
    search.text = ""
    toggleRow.value = "false"; toggleRow.saveState = ""; toggleRow.errorText = ""
    selectRow.value = "autonomous"
    numberRow.value = "12"; numberRow.saveState = ""; numberRow.errorText = ""
    numberRow.control.revert()
    svc.textScale = 1
    stack.width = 720
  }

  function find(item, name) {
    if (item.objectName === name) return item
    var kids = item.children
    for (var i = 0; i < kids.length; i++) {
      var r = find(kids[i], name)
      if (r) return r
    }
    return null
  }

  function test_toggle_commits_on_click_and_space() {
    var t = toggleRow.control
    verify(t)
    mouseClick(t)
    compare(toggleSpy.count, 1)
    compare(toggleSpy.signalArguments[0][0], "true")
    t.forceActiveFocus()
    keyClick(Qt.Key_Space)
    compare(toggleSpy.count, 2)
    compare(toggleSpy.signalArguments[1][0], "true")
    toggleRow.value = "true"
    keyClick(Qt.Key_Space)
    compare(toggleSpy.signalArguments[2][0], "false")
  }

  function test_toggle_meets_window_control_height() {
    verify(toggleRow.control.height >= 32)
    verify(numberRow.control.children[0].height >= 32)
  }

  function test_number_field_blocks_invalid_and_commits_valid() {
    var c = numberRow.control
    var input = find(c, "input:cua.max_per_turn")
    verify(input)
    input.forceActiveFocus()
    input.selectAll()
    keyClick(Qt.Key_0)
    compare(input.text, "0")
    compare(c.problem, "ui.err.range")
    var err = find(c, "problem:cua.max_per_turn")
    verify(err.visible)
    compare(err.text, svc.ui("ui.err.range"))
    keyClick(Qt.Key_Return)
    compare(numberSpy.count, 0)
    input.focus = false
    compare(numberSpy.count, 0)
    compare(input.text, "0")
    input.forceActiveFocus()
    input.selectAll()
    keyClick(Qt.Key_2)
    keyClick(Qt.Key_0)
    compare(c.problem, "")
    verify(!err.visible)
    keyClick(Qt.Key_Return)
    compare(numberSpy.count, 1)
    compare(numberSpy.signalArguments[0][0], "20")
    // leaving the field after Enter does not send it again
    input.focus = false
    compare(numberSpy.count, 1)
  }

  function test_escape_restores_saved_value() {
    var input = find(numberRow.control, "input:cua.max_per_turn")
    input.forceActiveFocus()
    input.selectAll()
    keyClick(Qt.Key_5)
    keyClick(Qt.Key_Escape)
    compare(input.text, "12")
    keyClick(Qt.Key_Return)
    compare(numberSpy.count, 0)
  }

  function test_row_states() {
    var strip = find(numberRow, "strip")
    numberRow.saveState = "saving"
    compare(strip.text, svc.ui("ui.set.saving"))
    numberRow.saveState = "saved"
    compare(strip.text, svc.ui("ui.set.saved"))
    numberRow.saveState = "error"
    numberRow.errorText = "max_per_turn must be at most 200"
    compare(strip.text, "max_per_turn must be at most 200")
    verify(strip.visible)
  }

  function test_error_row_reset_commits_schema_default() {
    numberRow.value = "20"
    numberRow.saveState = "error"
    numberRow.errorText = "rejected"
    var reset = find(numberRow, "reset")
    verify(reset.visible)
    waitForRendering(numberRow)
    mouseClick(reset)
    compare(numberSpy.count, 1)
    compare(numberSpy.signalArguments[0][0], S.field("cua.max_per_turn").default)
    numberRow.value = "12"
    numberRow.saveState = ""
    verify(!reset.visible)
    compare(find(numberRow, "strip").text, "")
  }

  function test_queued_and_saving_lock_the_control_and_show_the_strip() {
    var strip = find(numberRow, "strip")
    numberRow.saveState = "queued"
    verify(!numberRow.control.enabled)
    compare(strip.text, svc.ui("ui.set.saving"))
    numberRow.saveState = "saving"
    verify(!numberRow.control.enabled)
    verify(toggleRow.control.enabled)
    toggleRow.saveState = "queued"
    verify(!toggleRow.control.enabled)
    mouseClick(toggleRow.control)
    compare(toggleSpy.count, 0)
    toggleRow.saveState = "saved"
    verify(toggleRow.control.enabled)
    numberRow.saveState = "error"
    verify(numberRow.control.enabled)
  }

  function test_no_reset_while_queued() {
    numberRow.value = "20"
    numberRow.saveState = "queued"
    verify(!find(numberRow, "reset").visible)
    numberRow.reset()
    compare(numberSpy.count, 0)
  }

  function test_value_compares_in_schema_format() {
    compare(usdRow.shown, "0.00")
    verify(!usdRow.differs)
    verify(!find(usdRow, "reset").visible)
    usdRow.value = "8"
    compare(usdRow.shown, "8.00")
    usdRow.value = "5"
    verify(usdRow.differs)
    usdRow.reset()
    compare(usdSpy.count, 1)
    compare(usdSpy.signalArguments[0][0], "0.00")
    usdRow.value = "0"
    usdSpy.clear()
  }

  function test_no_reset_while_saving() {
    numberRow.value = "20"
    numberRow.saveState = "saving"
    verify(!find(numberRow, "reset").visible)
    numberRow.reset()
    compare(numberSpy.count, 0)
  }

  function test_select_shows_spaces_and_commits_raw() {
    var opt = find(selectRow.control, "opt:always_ask")
    verify(opt)
    compare(opt.children[0].text, "always ask")
    mouseClick(opt)
    compare(selectSpy.count, 1)
    compare(selectSpy.signalArguments[0][0], "always_ask")
  }

  function test_select_arrow_keys_commit() {
    selectRow.control.forceActiveFocus()
    keyClick(Qt.Key_Right)
    compare(selectSpy.signalArguments[0][0], "guided")
    keyClick(Qt.Key_End)
    compare(selectSpy.signalArguments[1][0], "always_ask")
  }

  function test_tab_order_and_focus_ring() {
    toggleRow.control.forceActiveFocus()
    verify(toggleRow.control.focused)
    keyClick(Qt.Key_Tab)
    verify(selectRow.control.activeFocus)
    verify(selectRow.control.focused)
    keyClick(Qt.Key_Tab)
    var input = find(numberRow.control, "input:cua.max_per_turn")
    verify(input.activeFocus)
    verify(numberRow.control.focused)
    var box = input.parent
    compare(box.border.width, 2)
  }

  function test_reflow_at_720_and_text_scale_125() {
    svc.textScale = 1.25
    stack.width = 720
    var rows = [toggleRow, selectRow, numberRow]
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i]
      verify(r.width <= 720)
      var kids = [r.children[0], r.children[1]]  // text column, control box
      for (var j = 0; j < kids.length; j++) {
        var k = kids[j]
        verify(k.x >= 0, r.key + " child " + j + " x")
        verify(k.x + k.width <= r.width + 0.5, r.key + " child " + j + " overflows: "
               + (k.x + k.width) + " > " + r.width)
      }
      verify(r.control.width <= r.width)
    }
    // a narrow row stacks its control under the text, still inside it
    stack.width = 360
    verify(selectRow.stacked)
    verify(selectRow.control.width <= 360)
    verify(selectRow.children[1].y >= selectRow.children[0].height)
  }

  function test_scrollpage_wheel_pagedown_drag() {
    var page = createTemporaryObject(pageC, root)
    verify(page)
    tryVerify(function () { return page.contentHeight > 2 * page.height })
    compare(page.contentY, 0)
    mouseWheel(page, 200, 100, 0, -240)
    tryVerify(function () { return page.contentY > 0 })
    page.contentY = 0
    page.forceActiveFocus()
    keyClick(Qt.Key_PageDown)
    verify(page.contentY > 0)
    var y = page.contentY
    keyClick(Qt.Key_End)
    compare(page.contentY, page.maxY)
    page.contentY = 0
    mouseDrag(page, 200, 180, 0, -120)
    tryVerify(function () { return page.contentY > 0 })
    verify(page.contentY <= page.maxY)
  }


  function test_failed_save_lets_the_same_draft_be_sent_again() {
    var input = find(numberRow.control, "input:cua.max_per_turn")
    input.forceActiveFocus()
    input.selectAll()
    keyClick(Qt.Key_3)
    keyClick(Qt.Key_0)
    keyClick(Qt.Key_Return)
    compare(numberSpy.count, 1)
    numberRow.saveState = "saving"
    keyClick(Qt.Key_Return)
    compare(numberSpy.count, 1)
    numberRow.saveState = "error"
    numberRow.errorText = "daemon offline"
    keyClick(Qt.Key_Return)
    compare(numberSpy.count, 2)
    compare(numberSpy.signalArguments[1][0], "30")
  }

  function test_reset_while_focused_drops_the_draft() {
    numberRow.value = "20"
    var input = find(numberRow.control, "input:cua.max_per_turn")
    input.forceActiveFocus()
    input.selectAll()
    keyClick(Qt.Key_5)
    keyClick(Qt.Key_0)
    numberRow.reset()
    compare(numberSpy.count, 1)
    compare(numberSpy.signalArguments[0][0], "12")
    compare(input.text, "12")
    // the host saves the default; leaving the field sends nothing more
    numberRow.value = "12"
    input.focus = false
    compare(numberSpy.count, 1)
    compare(input.text, "12")
  }

  function test_saved_value_updates_untouched_focused_field() {
    var input = find(numberRow.control, "input:cua.max_per_turn")
    input.forceActiveFocus()
    numberRow.value = "40"
    compare(input.text, "40")
  }

  function test_search_emits_and_escape_clears() {
    search.focusField()
    verify(search.focused)
    keyClick(Qt.Key_B)
    compare(searchSpy.count, 1)
    compare(searchSpy.signalArguments[0][0], "b")
    keyClick(Qt.Key_Escape)
    compare(search.text, "")
    compare(searchSpy.count, 2)
    compare(searchSpy.signalArguments[1][0], "")
    // a second Escape on an empty field is left for the window to handle
    keyClick(Qt.Key_Escape)
    compare(searchSpy.count, 2)
  }
}
}
