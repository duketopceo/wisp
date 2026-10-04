// Health view of the management app: the W22 HealthSection at app width.
// Same inputs as the Panel (state health rows and spend field through the
// service; `cua` from wispd cua status --json and `spendModels` from wispd
// spend --json as one-shot reads), so the two surfaces show one set of rows.
import QtQuick

Column {
  id: root

  property var service: null
  property var cua: null
  property var spendModels: []

  width: 560

  HealthSection {
    width: root.width
    service: root.service
    cua: root.cua
    spendModels: root.spendModels
  }
}
