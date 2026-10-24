from PyQt6.QtWidgets import QApplication

_app = None


def qapp() -> QApplication:
    global _app
    _app = QApplication.instance() or QApplication(["tests"])
    from linxdiagram import app as appmod
    appmod._pick_default_font()
    return _app
