"""Point d'entrée : application Qt, thème, fenêtres, documents récents, récupération."""

from __future__ import annotations

import os
import re
import sys
import time
import traceback

from PyQt6.QtCore import QObject, QSettings, Qt
from PyQt6.QtGui import QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import APP_ID, APP_NAME, ORG_NAME, __version__, fileformat, icons, security, style, units
from .document import Document
from .scene import set_dark_canvas

MAX_RECENT = 12
_AUTOSAVE_RE = re.compile(r"^([0-9a-f]{16})-(\d+)\.lxd$")


def _xdg(var: str, fallback: str) -> str:
    base = os.environ.get(var)
    if not base or not os.path.isabs(base):
        base = os.path.expanduser(fallback)
    return os.path.join(base, APP_NAME)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class AppContext(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.windows: list = []
        self._untitled: dict[int, str] = {}
        self._counter = 0
        self.autosave_dir = security.private_dir(os.path.join(_xdg("XDG_DATA_HOME", "~/.local/share"),
                                                              "autosave"))

    # ---------------------------------------------------------------- fenêtres
    def new_window(self, doc: Document | None = None, title_hint: str | None = None):
        from .mainwindow import MainWindow
        w = MainWindow(self, doc, title_hint)
        w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.windows.append(w)
        if self.windows and len(self.windows) > 1:
            prev = self.windows[-2]
            w.move(prev.pos().x() + 32, prev.pos().y() + 32)
        w.show()
        return w

    def window_closed(self, w) -> None:
        if w in self.windows:
            self.windows.remove(w)

    def find_window(self, path: str):
        for w in self.windows:
            if w.doc is not None and w.doc.path and os.path.abspath(w.doc.path) == path:
                return w
        return None

    def untitled_name(self, window) -> str:
        key = id(window.doc)
        if key not in self._untitled:
            self._counter += 1
            self._untitled[key] = f"Dessin{self._counter}"
        return self._untitled[key]

    def quit(self) -> None:
        for w in list(self.windows):
            if not w.close():
                return
        self.app.quit()

    # ---------------------------------------------------------------- récents
    def recent_files(self) -> list[str]:
        files = self.settings.value("recent/files", [], type=list) or []
        return [f for f in files if isinstance(f, str)][:MAX_RECENT]

    def add_recent(self, path: str) -> None:
        if not self.settings.value("privacy/remember_recent", True, type=bool):
            return
        files = [f for f in self.recent_files() if f != path]
        files.insert(0, path)
        self.settings.setValue("recent/files", files[:MAX_RECENT])

    def clear_recent(self) -> None:
        self.settings.setValue("recent/files", [])

    # ---------------------------------------------------------------- récupération
    def autosave_path(self, doc: Document) -> str:
        return os.path.join(self.autosave_dir, f"{doc.uid}-{os.getpid()}.lxd")

    def write_autosave(self, doc: Document) -> None:
        # Un document chiffré reste chiffré dans sa copie de récupération.
        fileformat.save_file(self.autosave_path(doc), doc.to_dict(), doc.password)

    def remove_autosave(self, doc: Document | None) -> None:
        if doc is None:
            return
        try:
            os.unlink(self.autosave_path(doc))
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _orphans(self) -> list[str]:
        out = []
        try:
            names = os.listdir(self.autosave_dir)
        except OSError:
            return out
        for name in names:
            m = _AUTOSAVE_RE.match(name)
            if m and not _pid_alive(int(m.group(2))):
                out.append(os.path.join(self.autosave_dir, name))
        return sorted(out, key=os.path.getmtime, reverse=True)

    def clear_autosaves(self) -> int:
        n = 0
        for path in self._orphans():
            try:
                os.unlink(path)
                n += 1
            except OSError:
                pass
        return n

    def recover(self) -> bool:
        files = self._orphans()
        if not files:
            return False
        from .dialogs import RecoveryDialog
        dlg = RecoveryDialog(None, files)
        accepted = dlg.exec() == RecoveryDialog.DialogCode.Accepted
        chosen = dlg.selected() if accepted else []
        opened = False
        for path in chosen:
            w = self.new_window()
            try:
                data, _warnings, password = fileformat.load_file(path, w.ask_password("récupération"))
            except fileformat.DocumentError as exc:
                QMessageBox.warning(w, APP_NAME, f"Récupération impossible :\n{exc}")
                w.close()
                continue
            doc = Document(data)
            doc.password = password
            doc.undo_stack.resetClean()
            w.title_hint = "Document récupéré"
            w.set_document(doc)
            opened = True
        if accepted or dlg.discard_all:
            for path in files:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return opened


# ------------------------------------------------------------------------ thème

def _is_dark(mode: str) -> bool:
    if mode == "dark":
        return True
    if mode == "system":
        try:
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except AttributeError:
            return False
    return False  # « En couleur » (clair), comme Visio par défaut


def apply_theme(app: QApplication, dark: bool) -> None:
    style.apply(app, dark)
    icons.set_dark(dark)
    set_dark_canvas(dark)


def _pick_default_font() -> None:
    families = set(QFontDatabase.families())
    for fam in ("Calibri", "Carlito", "Noto Sans", "Cantarell", "DejaVu Sans", "Liberation Sans"):
        if fam in families:
            units.set_default_font(fam)
            return
    units.set_default_font(QApplication.font().family())


def _install_excepthook() -> None:
    log_dir = security.private_dir(_xdg("XDG_STATE_HOME", "~/.local/state"))
    last = [0.0]

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            fd = os.open(os.path.join(log_dir, "erreurs.log"),
                         os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {APP_NAME} {__version__}\n{text}\n")
        except OSError:
            pass
        sys.__stderr__.write(text)
        if time.monotonic() - last[0] > 5 and QApplication.instance() is not None:
            last[0] = time.monotonic()
            QMessageBox.critical(None, APP_NAME,
                                 "Une erreur inattendue s'est produite. Votre travail est protégé par "
                                 "la récupération automatique ; enregistrez-le dès que possible.\n\n"
                                 f"{exc_type.__name__}: {exc}")
    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--help" in argv or "-h" in argv:
        print(f"Usage : linxdiagram [FICHIER.lxd | FICHIER.vsdx]…\n\n{APP_NAME} {__version__} — "
              "éditeur de diagrammes natif pour Linux.")
        return 0
    security.harden_process()
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setApplicationVersion(__version__)
    QGuiApplication.setDesktopFileName(APP_ID)
    app = QApplication(argv)
    app.setWindowIcon(icons.app_icon())
    settings = QSettings(ORG_NAME, APP_NAME)
    apply_theme(app, _is_dark(settings.value("ui/theme", "light")))
    _pick_default_font()
    _install_excepthook()
    ctx = AppContext(app)
    app.setQuitOnLastWindowClosed(True)
    files = [a for a in argv[1:] if not a.startswith("-")]
    recovered = ctx.recover()
    if files:
        first = ctx.new_window()
        for f in files:
            first.open_path(f)
    elif not recovered:
        w = ctx.new_window()
        w.show_backstage("home")
    return app.exec()
