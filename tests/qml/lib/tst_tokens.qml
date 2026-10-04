import QtQuick
import QtTest
import "../../../shell-plugin/lib/tokens.js" as Tokens

// The QML port of wisp/theme.py must reproduce the U1 golden fixtures
// within one 8-bit channel step. Run with QML_XHR_ALLOW_FILE_READ=1.
TestCase {
  name: "tokens"

  readonly property var fixtures: ["vantablack", "tokyo-night", "white",
    "catppuccin-latte", "flexoki-light", "red-accent", "partial"]

  function read(rel) {
    var xhr = new XMLHttpRequest()
    xhr.open("GET", Qt.resolvedUrl("../../fixtures/themes/" + rel), false)
    try { xhr.send() } catch (e) { return "" }   // file reads need the env var
    return xhr.status === 200 || xhr.status === 0 ? xhr.responseText : ""
  }

  function channels(hex) {
    return [parseInt(hex.substr(1, 2), 16), parseInt(hex.substr(3, 2), 16),
            parseInt(hex.substr(5, 2), 16)]
  }

  function test_fixture_data() {
    return fixtures.map(function (n) { return { tag: n, name: n } })
  }

  function test_fixture(data) {
    var raw = read(data.name + "/expected.json")
    verify(raw.length > 0, "fixture unreadable: run with QML_XHR_ALLOW_FILE_READ=1")
    var expected = JSON.parse(raw)
    var colors = Tokens.parseColors(read(data.name + "/colors.toml"))
    var shellText = read(data.name + "/shell.toml")
    var shell = shellText.length ? Tokens.parseShell(shellText) : null
    var got = Tokens.derive(colors, shell)
    compare(got.mode, expected.mode)
    compare(Object.keys(got.tokens).sort(), Object.keys(expected.tokens).sort())
    for (var k in expected.tokens) {
      var a = channels(got.tokens[k]), b = channels(expected.tokens[k])
      for (var i = 0; i < 3; i++)
        verify(Math.abs(a[i] - b[i]) <= 1,
               data.name + " " + k + " " + got.tokens[k] + " vs " + expected.tokens[k])
    }
  }

  function test_contrast_matches_wcag() {
    fuzzyCompare(Tokens.contrast("#000000", "#ffffff"), 21, 0.001)
    fuzzyCompare(Tokens.contrast("#777777", "#ffffff"), 4.48, 0.01)
  }

  function test_fallback_when_no_colors() {
    var got = Tokens.load("", "", "light")
    compare(got.source, "fallback")
    compare(got.mode, "light")
  }
}
