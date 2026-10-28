import QtQuick
import QtTest
import "../../../shell-plugin/lib/whatsnew.js" as W
import "../../../shell-plugin/components"
import "../harness"

// What's-new card (B26): lib/whatsnew.js parse and argv, and WhatsNewCard
// against the harness FixtureService: the headline lines are shown, the
// dismiss and link chips emit their signals, and nothing shows without a card.
TestCase {
  name: "whatsnew"
  width: 400
  height: 600
  when: windowShown

  FixtureService { id: svc }

  SignalSpy { id: dismissed; target: card; signalName: "dismiss" }
  SignalSpy { id: links; target: card; signalName: "openLink" }

  WhatsNewCard {
    id: card
    service: svc
    width: 360
    card: W.parse(JSON.stringify({ ok: true, data: { card: {
      title: "v1.2.0", date: "2026-10-01", more: 2, url: "https://github.com/duketopceo/wisp/blob/master/CHANGELOG.md",
      lines: ["One headline.", "Two.", "Three.", "Four is cut."] } } }))
  }

  function init() { dismissed.clear(); links.clear() }

  function find(item, name, out) {
    if (item.objectName === name) out.push(item)
    var kids = item.children
    for (var i = 0; i < kids.length; i++) find(kids[i], name, out)
    return out
  }

  function test_parse_envelope_bare_and_none() {
    verify(W.parse("not json") === null)
    verify(W.parse(JSON.stringify({ ok: true, data: { card: null } })) === null)
    verify(W.parse(JSON.stringify({ card: null })) === null)
    verify(W.parse(JSON.stringify({ card: { title: "x", lines: [] } })) === null)
    var bare = W.parse(JSON.stringify({ card: { title: "v1", lines: ["a"] } }))
    compare(bare.title, "v1")
    compare(bare.more, 0)
    verify(!W.visible(null))
    verify(W.visible(bare))
  }

  function test_at_most_three_clean_lines() {
    var c = W.parse(JSON.stringify({ card: { title: "v1", lines: ["  a   b ", "", 7, "c", "d", "e"] } }))
    compare(c.lines.length, 3)
    compare(c.lines[0], "a b")
    compare(c.lines[2], "d")
    var c3 = W.parse(JSON.stringify({ card: { title: "v1", lines: ["a", "b", "c", "d"] } }))
    compare(c3.lines.length, 3)
  }

  function test_commands() {
    compare(W.statusCommand("wispd").join(" "), "wispd whatsnew --json")
    compare(W.seenCommand("wispd").join(" "), "wispd whatsnew --seen --json")
  }

  function test_only_the_project_address_opens() {
    compare(W.linkCommand("https://github.com/duketopceo/wisp/blob/master/CHANGELOG.md")[0], "xdg-open")
    compare(W.linkCommand("http://github.com/x").length, 0)
    compare(W.linkCommand("https://evil.example/x").length, 0)
    compare(W.linkCommand("file:///etc/passwd").length, 0)
    compare(W.linkCommand("").length, 0)
    compare(W.linkCommand("https://github.com.evil.example/").length, 0)
  }

  function test_the_card_shows_the_headline_and_the_rest_count() {
    var lines = find(card, "whatsnewLine", [])
    compare(lines.length, 3)
    compare(lines[0].text, "One headline.")
    var more = find(card, "whatsnewMore", [])[0]
    compare(more.text, "+2 " + svc.ui("ui.whatsnew.more"))
    compare(find(card, "whatsnewTitle", [])[0].text, svc.ui("ui.whatsnew.title") + " v1.2.0")
  }

  function test_buttons_emit() {
    find(card, "whatsnewDismiss", [])[0].clicked()
    compare(dismissed.count, 1)
    find(card, "whatsnewLink", [])[0].clicked()
    compare(links.count, 1)
    compare(links.signalArguments[0][0], "https://github.com/duketopceo/wisp/blob/master/CHANGELOG.md")
  }

  function test_no_more_line_when_nothing_is_left() {
    var c = createTemporaryObject(Qt.createComponent("../../../shell-plugin/components/WhatsNewCard.qml"), this,
      { service: svc, card: { title: "u", lines: ["a"], more: 0, url: "" } })
    compare(find(c, "whatsnewMore", [])[0].text, "")
  }
}
