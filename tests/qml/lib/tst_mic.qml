import QtQuick
import QtTest
import "../../../shell-plugin/lib/bar.js" as B
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../../../shell-plugin/components"
import "../harness"

// B33: the bar shows the open-mic mark exactly while the daemon says the
// opt-in wake word is listening, and never otherwise.
TestCase {
  id: tc
  name: "mic"
  when: windowShown
  width: 200
  height: 100

  FixtureService { id: svc }

  function readJson(name) {
    var x = new XMLHttpRequest();
    x.open("GET", Qt.resolvedUrl("../../fixtures/states/" + name + ".json"), false);
    x.send();
    return JSON.parse(x.responseText);
  }

  function test_the_rule() {
    verify(B.micOpen("open", false))
    verify(!B.micOpen("", false))
    verify(!B.micOpen("open", true))
    verify(!B.micOpen(undefined, false))
  }

  function test_mark_follows_the_state_field() {
    svc.tokens = Tokens.load("", "", "dark").tokens;
    var raw = readJson("idle");
    delete raw._fixture;
    svc.load(raw, {});
    var m = createTemporaryObject(markComp, tc, { service: svc });
    verify(m !== null);
    compare(m.micOpen, false, "no mic mark by default");
    raw.mic = "open";
    svc.load(raw, {});
    compare(m.micOpen, true, "mic mark while listening");
    raw.mic = "";
    svc.load(raw, {});
    compare(m.micOpen, false, "gone when the listener stops");
    m.destroy();
  }

  Component { id: markComp; BarMark { } }
}
