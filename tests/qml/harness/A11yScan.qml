// Accessibility scan for the construction-rule tests (one-surface U7).
// controls(root) walks the visual item tree and returns every visible,
// enabled interactive item: it takes Tab focus, it is an editable text
// input, or its Accessible.role is one a person presses or edits.
// unnamed(root) returns those whose Accessible.name is empty, as
// readable descriptions. focusable(item) says whether the focus-ring rule
// applies: a control that takes Tab focus must show it. A role-only
// control (a Panel tab, a sidebar row in a list that holds the focus) is
// pressed or picked without taking focus, so it needs a name only.
// "Interactive" is decided by focus and role, not by MouseArea presence,
// so hover-only areas are not counted.
import QtQuick

QtObject {
  readonly property var roles: [
    Accessible.Button, Accessible.CheckBox, Accessible.RadioButton,
    Accessible.ComboBox, Accessible.PageTab, Accessible.EditableText,
    Accessible.Slider, Accessible.SpinBox, Accessible.Link,
    Accessible.ListItem
  ]

  function editable(item) {
    return item.cursorPosition !== undefined && item.readOnly === false
  }

  function focusable(item) {
    return item.activeFocusOnTab === true || editable(item)
  }

  function interactive(item) {
    if (!item.visible || !item.enabled) return false
    return item.activeFocusOnTab === true || editable(item)
        || roles.indexOf(item.Accessible.role) >= 0
  }

  function controls(root) {
    var out = []
    function walk(item) {
      if (!item || !item.visible) return
      if (item !== root && interactive(item)) out.push(item)
      var kids = item.children || []
      for (var i = 0; i < kids.length; i++) walk(kids[i])
    }
    walk(root)
    return out
  }

  function nameOf(item) {
    var n = item.Accessible.name
    return n === undefined || n === null ? "" : String(n).trim()
  }

  function describe(item) {
    var type = String(item).split("(")[0].split("_QML")[0]
    var where = item.parent
    while (where && !where.objectName) where = where.parent
    return (item.objectName || type) + " in "
        + (where ? where.objectName : "(root)")
  }

  function unnamed(root) {
    var bad = []
    var list = controls(root)
    for (var i = 0; i < list.length; i++)
      if (nameOf(list[i]) === "") bad.push(describe(list[i]))
    return bad
  }

  function named(root) {
    var out = []
    var list = controls(root)
    for (var i = 0; i < list.length; i++)
      if (list[i].objectName) out.push(list[i].objectName)
    return out
  }
}
