import QtQuick
import QtTest
import "../../../shell-plugin/lib/settings.js" as S
import "../../../shell-plugin/components"
import "../harness"

// Settings window body (overhaul U4): the sidebar lists every schema
// category, a click or Up/Down picks one (emitting picked), unknown names
// are ignored, and the page title follows the category.
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

  TestCase {
    name: "settingshost"
    when: windowShown

    function init() { host.category = S.CATEGORIES[0]; picks.clear() }

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
      find(host, "sidebar").forceActiveFocus()
      keyClick(Qt.Key_Down)
      compare(host.category, S.CATEGORIES[1])
      keyClick(Qt.Key_Up)
      keyClick(Qt.Key_Up)
      compare(host.category, S.CATEGORIES[0])
      compare(picks.count, 2)
    }

    function test_select_ignores_unknown_and_same() {
      host.select("nope")
      host.select(S.CATEGORIES[0])
      compare(host.category, S.CATEGORIES[0])
      compare(picks.count, 0)
    }
  }
}
