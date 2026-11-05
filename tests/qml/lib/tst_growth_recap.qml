import QtQuick
import QtTest
import "../../../shell-plugin/components" as C
import "../harness" as Harness

TestCase {
  id: test
  name: "WeeklyRecapCard"
  when: windowShown
  width: 420
  height: 600

  Harness.FixtureService { id: fixture }
  Component { id: cardComponent; C.WeeklyRecapCard {} }

  function cardData() {
    return {
      week_start: "2026-10-19", week_end: "2026-10-25",
      title: "your week with wisp",
      summary: "you used wisp 5 days, 6 turns, $0.83 recorded",
      activity_note: "",
      spend_note: "Recorded costs may include estimates; measured and estimated shares are unknown."
    };
  }

  function test_plain_wrapped_summary() {
    var card = createTemporaryObject(cardComponent, test, {
      service: fixture, card: cardData(), width: 200
    });
    verify(card !== null);
    var summary = findChild(card, "recapSummary");
    compare(summary.textFormat, Text.PlainText);
    compare(summary.wrapMode, Text.Wrap);
    compare(summary.text, cardData().summary);
    verify(card.implicitHeight > 0);
  }

  function test_unknown_spend_is_not_zero() {
    var data = cardData();
    data.summary = "you used wisp 5 days, 6 turns, spend unavailable";
    var card = createTemporaryObject(cardComponent, test, {
      service: fixture, card: data
    });
    compare(findChild(card, "recapSummary").text, data.summary);
    verify(findChild(card, "recapSummary").text.indexOf("$0.00") < 0);
  }

  function test_local_actions() {
    var card = createTemporaryObject(cardComponent, test, {
      service: fixture, card: cardData()
    });
    var dismissed = 0;
    var disabled = 0;
    card.dismiss.connect(function () { dismissed += 1; });
    card.offClicked.connect(function () { disabled += 1; });
    findChild(card, "recapDismiss").clicked();
    findChild(card, "recapOff").clicked();
    compare(dismissed, 1);
    compare(disabled, 1);
  }
}
