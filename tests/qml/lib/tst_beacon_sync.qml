import QtQuick
import QtTest
import "../../../shell-plugin/lib/cursor.js" as Cur

// Why OverlayLayer feeds its beacon Repeater from a ListModel: a replaced
// array model rebuilds every delegate, a ListModel append only adds one.
TestCase {
  id: tc
  name: "beaconSync"
  when: windowShown
  width: 100
  height: 100

  property int created: 0
  property var arr: []

  ListModel { id: lm }

  Item {
    Repeater {
      id: arrRep
      model: tc.arr
      delegate: Item {
        required property var modelData
        Component.onCompleted: tc.created++
      }
    }
    Repeater {
      id: lmRep
      model: lm
      delegate: Item {
        required property real bx
        Component.onCompleted: tc.created++
      }
    }
  }

  function apply(prev, next) {
    var plan = Cur.beaconSync(prev, next)
    if (plan.kind === "reset") lm.clear()
    for (var i = plan.from; i < next.length; i++) lm.append({ bx: next[i].x })
  }

  function test_replaced_array_rebuilds_all_delegates() {
    arr = [{ x: 1 }]
    wait(20)
    created = 0
    arr = [{ x: 1 }, { x: 2 }]
    wait(20)
    compare(created, 2)
  }

  function test_listmodel_append_creates_only_the_new_delegate() {
    var a = { x: 1, y: 1, label: "", index: 1 }
    var b = { x: 2, y: 2, label: "", index: 2 }
    apply([], [a])
    wait(20)
    created = 0
    apply([a], [a, b])
    wait(20)
    compare(lmRep.count, 2)
    compare(created, 1)
  }

  function test_new_turn_rebuilds_and_empty_clears() {
    var a = { x: 1, y: 1, label: "", index: 1 }
    var c = { x: 9, y: 9, label: "", index: 1 }
    apply([], [a])
    wait(20)
    created = 0
    apply([a], [c])
    wait(20)
    compare(lmRep.count, 1)
    compare(created, 1)
    apply([c], [])
    wait(20)
    compare(lmRep.count, 0)
  }
}
