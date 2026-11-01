import QtQuick
import QtQuick.Controls
import QtTest
import "../../../shell-plugin/lib/metrics.js" as M

// Type and spacing scale (settings overhaul U1, KTD2, R11 to R14) and the
// scroll audit helper that later settings pages rely on.
TestCase {
  id: tc
  name: "metrics"
  width: 400
  height: 300
  visible: true
  when: windowShown

  ScrollAudit { id: audit }

  function test_font_scale_meets_the_minimums() {
    var f = M.scale.font
    for (var k in f) verify(f[k] >= M.scale.minimum.secondary, k)
    verify(f.body >= M.scale.minimum.body)
    verify(f.answer >= f.body && f.title > f.answer && f.heading > f.title)
  }

  function test_space_scale_is_four_pixel_steps() {
    var s = M.scale.space
    for (var k in s) compare(s[k] % 4, 0, k)
    compare(s.xs, 4)
    verify(s.sm < s.md && s.md < s.lg && s.lg < s.xl && s.xl < s.xxl && s.xxl < s.huge)
  }

  function test_old_blocks_are_untouched() {
    compare(M.font.body, 12)
    compare(M.spacing.lg, 8)
    compare(M.size.control, 28)
  }

  function test_text_scale_grows_text_and_keeps_the_hit_target() {
    compare(M.fontSize("body", 1), 14)
    compare(M.fontSize("body", 1.25), 18)
    compare(M.fontSize("caption", 1.25), 15)
    compare(M.controlHeight(false), 32)
    compare(M.controlHeight(true), 28)
  }

  function test_text_scale_never_goes_under_the_minimums() {
    compare(M.textScale(0.5), 1)
    compare(M.fontSize("caption", 0.5), 12)
    compare(M.textScale(9), 2)
    compare(M.textScale("junk"), 1)
    compare(M.textScale(undefined), 1)
    compare(M.textScale(""), 1)
    compare(M.textScale("1.5"), 1.5)
  }

  Component {
    id: tallPage
    Item {
      width: 400
      height: 300
      Flickable {
        id: flick
        objectName: "page"
        anchors.fill: parent
        contentWidth: width
        contentHeight: 900
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
      }
    }
  }

  Component {
    id: tallNoBar
    Item {
      width: 400
      height: 300
      Flickable {
        objectName: "nobar"
        anchors.fill: parent
        contentWidth: width
        contentHeight: 900
      }
    }
  }

  Component {
    id: tallNoFlickable
    Item {
      width: 400
      height: 300
      Column {
        objectName: "column"
        Rectangle { width: 400; height: 900 }
      }
    }
  }

  Component {
    id: shortPage
    Item {
      width: 400
      height: 300
      Column {
        objectName: "short"
        Rectangle { width: 400; height: 100 }
      }
    }
  }

  function test_audit_passes_a_scrollable_page() {
    var page = createTemporaryObject(tallPage, tc)
    verify(page)
    compare(audit.audit(page), [])
  }

  function test_audit_fails_a_flickable_without_a_scrollbar() {
    var page = createTemporaryObject(tallNoBar, tc)
    compare(audit.audit(page), ["flickable-no-bar:nobar"])
  }

  function test_audit_fails_tall_content_outside_any_flickable() {
    var page = createTemporaryObject(tallNoFlickable, tc)
    var out = audit.audit(page)
    verify(out.length > 0)
    verify(out[0].indexOf("clipped:") === 0)
  }

  function test_audit_passes_content_that_fits() {
    var page = createTemporaryObject(shortPage, tc)
    compare(audit.audit(page), [])
  }
}
