// Activity page of the settings window (one-surface U3, from the retired
// console): open suggestions with their three answers, the turn log
// (what it heard, how it routed, what it said) and learned corrections.
// The rows come from lib/manage.js over the files the shell watches;
// this item only draws them.
import QtQuick
import "../lib/metrics.js" as M

Column {
  id: root

  property var service: null
  // [{time, route, ms, you, wisp}] oldest first (Manage.turnRows)
  property var turns: []
  // [{key, title, evidence}] (Manage.openSuggestions)
  property var suggestions: []
  // raw correction lines, newest first (Manage.correctionLines)
  property var corrections: []
  signal answer(string pick)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1

  width: 560
  spacing: M.scale.space.md

  component Small: Text {
    textFormat: Text.PlainText
    width: root.width
    elide: Text.ElideRight
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("caption", root.ts)
  }

  SectionHeader {
    visible: root.suggestions.length > 0
    service: root.service
    width: root.width
    first: true
    title: root.service.ui("ui.activity.ideas")
  }
  Repeater {
    model: root.suggestions
    delegate: Column {
      id: idea
      required property var modelData
      objectName: "idea:" + modelData.key
      width: root.width
      spacing: M.scale.space.xs
      Text {
        textFormat: Text.PlainText
        width: parent.width
        wrapMode: Text.Wrap
        text: idea.modelData.title || ""
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("body", root.ts)
        font.weight: Font.DemiBold
      }
      Small { visible: text !== ""; text: idea.modelData.evidence || "" }
      Row {
        spacing: M.scale.space.sm
        Repeater {
          model: [["automate", "ui.activity.automate"], ["not now", "ui.activity.not_now"],
                  ["never", "ui.activity.never"]]
          delegate: Chip {
            required property var modelData
            service: root.service
            label: root.service.ui(modelData[1])
            focusable: true
            onClicked: root.answer("suggestion:" + modelData[0] + ":" + idea.modelData.key)
          }
        }
      }
    }
  }

  SectionHeader {
    service: root.service
    width: root.width
    first: root.suggestions.length === 0
    title: root.service.ui("ui.activity.log")
    note: root.service.ui("ui.activity.sub")
  }
  EmptyState {
    objectName: "empty"
    visible: root.turns.length === 0
    service: root.service
    tab: "activity"
    width: root.width
  }
  Repeater {
    model: root.turns.slice().reverse()
    delegate: Column {
      id: turn
      required property var modelData
      width: root.width
      spacing: M.scale.space.xs
      Rectangle { width: parent.width; height: M.size.keyline; color: root.tk.keyline }
      Small {
        text: [turn.modelData.time, turn.modelData.route,
               turn.modelData.ms > 0 ? turn.modelData.ms + " ms" : ""]
          .filter(function (s) { return s !== "" }).join("  ")
      }
      Text {
        textFormat: Text.PlainText
        visible: turn.modelData.you !== ""
        width: parent.width
        wrapMode: Text.Wrap
        text: root.service.ui("ui.activity.you") + "  " + turn.modelData.you
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("body", root.ts)
      }
      Text {
        textFormat: Text.PlainText
        visible: turn.modelData.wisp !== ""
        width: parent.width
        wrapMode: Text.Wrap
        text: root.service.ui("ui.activity.wisp") + "  " + turn.modelData.wisp
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("body", root.ts)
      }
    }
  }

  SectionHeader {
    visible: root.corrections.length > 0
    service: root.service
    width: root.width
    title: root.service.ui("ui.activity.corrections")
  }
  Repeater {
    model: root.corrections
    delegate: Small { required property string modelData; text: modelData }
  }
}
