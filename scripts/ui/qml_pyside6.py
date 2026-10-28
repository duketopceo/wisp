#!/usr/bin/env python3
"""A `qml` stand-in on PySide6 for boxes without Qt's own tools.

    pip install PySide6
    WISP_QML="python3 scripts/ui/qml_pyside6.py" python3 scripts/ui/snap.py check

Runs a QML file like `qml FILE -- ARGS...`: arguments after `--` reach
Qt.application.arguments, and the run ends when the QML calls Qt.exit().
Text-heavy goldens drift by a few pixels between Qt builds; the non-text
ones (marks, creature, buddy) match.
"""
import sys


def main(argv):
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    if not argv:
        print("usage: qml_pyside6.py FILE [-- ARGS...]", file=sys.stderr)
        return 2
    rest = argv[1:]
    app = QGuiApplication([sys.argv[0], argv[0]] + (rest if rest[:1] == ["--"]
                                                    else ["--"] + rest))
    engine = QQmlApplicationEngine()
    engine.load(argv[0])
    if not engine.rootObjects():
        return 2
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
