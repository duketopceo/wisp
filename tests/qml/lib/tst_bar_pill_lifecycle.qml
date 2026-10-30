import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../harness"

// Replacing the visible pill while loading the next state mirrors the
// snapshot host and the bar's shared, continuously updating service.
TestCase {
  id: tc
  name: "bar_pill_lifecycle"
  when: windowShown
  visible: true
  width: 480
  height: 120

  FixtureService {
    id: svc
    tokens: Tokens.load("", "", "dark").tokens
  }
  Component { id: pillC; BarPill {} }
  Component { id: hostC; Rectangle { color: svc.tokens.canvas } }

  function readJson(name) {
    var x = new XMLHttpRequest()
    x.open("GET", Qt.resolvedUrl("../../fixtures/states/" + name + ".json"), false)
    x.send()
    return JSON.parse(x.responseText)
  }

  function test_replacing_pill_without_binding_warnings() {
    failOnWarning(/.?/)
    var fixtures = ["listening", "acting"]
    var host = null
    for (var i = 0; i < fixtures.length; i++) {
      if (host) host.destroy()
      var raw = readJson(fixtures[i])
      var mods = raw._fixture || {}
      delete raw._fixture
      svc.load(raw, mods)
      host = hostC.createObject(tc)
      var pill = pillC.createObject(host, { service: svc })
      verify(pill !== null, fixtures[i])
      pill.x = 8
      pill.y = 8
      host.width = Math.ceil(pill.width) + 16
      host.height = Math.max(Math.ceil(pill.height), 8) + 16
      var grabbed = false
      verify(host.grabToImage(function () { grabbed = true }))
      tryVerify(function () { return grabbed })
    }
    host.destroy()
    wait(20)
  }
}
