// Snapshot composition for ScrollPage (U3): one settings category as the
// settings window will lay it out, a section header and a SettingRow per
// schema field, scrolled to `scrollY`.
import QtQuick
import "../../../shell-plugin/components"
import "../../../shell-plugin/lib/settings.js" as S

ScrollPage {
  id: page

  property string category: "pointer"
  property real scrollY: 0
  property var values: ({})
  property var states: ({})

  width: 720
  height: 420
  contentY: Math.min(scrollY, maxY)

  SectionHeader {
    service: page.service
    first: true
    width: parent.width
    title: page.service.ui("set.cat." + page.category)
  }
  Repeater {
    model: S.FIELDS.filter(function (f) { return f.category === page.category })
    delegate: SettingRow {
      required property var modelData
      service: page.service
      def: modelData
      width: parent ? parent.width : 0
      value: page.values.hasOwnProperty(modelData.key) ? page.values[modelData.key] : String(modelData.default)
      saveState: page.states.hasOwnProperty(modelData.key) ? page.states[modelData.key] : ""
    }
  }
}
