"""Menu Fichier (mode Backstage) à la manière de Microsoft 365 : Accueil, Nouveau,
Ouvrir, Informations, Enregistrer, Imprimer (avec aperçu), Exporter, Options."""

from __future__ import annotations

import datetime
import os
import time
import unicodedata

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintPreviewWidget
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
                             QListWidget, QListWidgetItem, QStackedWidget, QToolButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from . import APP_NAME, __version__, icons, security, templates
from .style import T

NAV = (("home", "Accueil"), ("new", "Nouveau"), ("open", "Ouvrir"), (None, None),
       ("info", "Informations"), ("save", "Enregistrer"), ("save_as", "Enregistrer sous"),
       ("print", "Imprimer"), ("export", "Exporter"), ("close", "Fermer"))
PAGES = ("home", "new", "open", "info", "print", "export", "security")


class TemplateTile(QToolButton):
    def __init__(self, key: str, title: str):
        super().__init__()
        self.setObjectName("TemplateTile")
        self.key = key
        category, description, _keywords = templates.template_info(key)
        self.setFixedSize(208, 214)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(3)
        pic = QLabel()
        pic.setPixmap(templates.thumbnail(key, 180, 126))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = QLabel(title)
        name.setObjectName("TemplateTileTitle")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        category_label = QLabel(f"{category} · Page vierge")
        category_label.setObjectName("TemplateTileCategory")
        for w in (pic, name, category_label):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(pic, 1)
        lay.addWidget(name)
        lay.addWidget(category_label)
        self.setToolTip(f"{title}\n{description}")
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)


def _page(title: str) -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    body = QWidget()
    body.setObjectName("BackstagePage")
    lay = QVBoxLayout(body)
    lay.setContentsMargins(44, 28, 44, 28)
    lay.setSpacing(14)
    h = QLabel(title)
    h.setObjectName("BackstageTitle")
    lay.addWidget(h)
    area.setWidget(body)
    return area, lay


def _section(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("BackstageSection")
    return lab


class Backstage(QWidget):
    back = pyqtSignal()
    newRequested = pyqtSignal(str)
    openRequested = pyqtSignal()
    openPath = pyqtSignal(str)
    commandRequested = pyqtSignal(str)

    def __init__(self, window):
        super().__init__()
        self.win = window
        self.setObjectName("Backstage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        nav = QFrame()
        nav.setObjectName("BackstageNav")
        nav.setFixedWidth(200)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(0, 14, 0, 14)
        nl.setSpacing(0)
        back = QToolButton()
        back.setIcon(icons.icon("back_arrow", "#ffffff"))
        back.setIconSize(QSize(30, 30))
        back.setFixedSize(40, 40)
        back.setToolTip("Retour au dessin (Échap)")
        back.clicked.connect(self.back)
        bl = QHBoxLayout()
        bl.setContentsMargins(16, 0, 0, 14)
        bl.addWidget(back)
        bl.addStretch(1)
        nl.addLayout(bl)
        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text in NAV:
            if key is None:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet("background: rgba(255,255,255,0.35); margin: 8px 20px;")
                nl.addWidget(sep)
                continue
            b = QPushButton(text)
            b.setCheckable(key in PAGES)
            b.clicked.connect(lambda _=False, k=key: self._nav(k))
            if key in PAGES:
                self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            nl.addWidget(b)
        nl.addStretch(1)
        for key, text in (("security", "Sécurité"), ("options", "Options")):
            b = QPushButton(text)
            b.setCheckable(key in PAGES)
            b.clicked.connect(lambda _=False, k=key: self._nav(k))
            if key in PAGES:
                self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            nl.addWidget(b)
        lay.addWidget(nav)
        lay.addWidget(self.stack, 1)
        self.pages: dict[str, QWidget] = {}
        self.pages["home"] = self._home()
        self.pages["new"] = self._new()
        self.pages["open"] = self._open()
        self.pages["info"] = self._info()
        self.pages["print"] = QWidget()  # construite à la première visite (requêtes CUPS lentes)
        self._print_built = False
        self.pages["export"] = self._export()
        self.pages["security"] = self._security()
        for key in PAGES:
            self.stack.addWidget(self.pages[key])

    # ------------------------------------------------------------------ navigation
    def _nav(self, key: str) -> None:
        if key in PAGES:
            self.select(key)
        else:
            self.commandRequested.emit(key)

    def select(self, key: str) -> None:
        if key == "new" and not self._templates_ready:
            self._refresh_templates()
        if key == "print":
            if not self._print_built:
                self._print_built = True
                old = self.pages["print"]
                self.pages["print"] = self._print()
                self.stack.insertWidget(self.stack.indexOf(old), self.pages["print"])
                self.stack.removeWidget(old)
                old.deleteLater()
            self._refresh_preview()
        if key == "info":
            self.set_info()
        self.stack.setCurrentWidget(self.pages[key])
        self.nav_buttons[key].setChecked(True)

    # ------------------------------------------------------------------ Accueil / Nouveau
    def _tiles(self, keys, cols: int = 4) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (key, title) in enumerate(keys):
            t = TemplateTile(key, title)
            t.clicked.connect(lambda _=False, k=key: self.newRequested.emit(k))
            grid.addWidget(t, i // cols, i % cols)
        grid.setColumnStretch(cols, 1)
        return grid

    def _home(self) -> QWidget:
        hour = datetime.datetime.now().hour
        greet = "Bonsoir" if hour >= 18 or hour < 5 else "Bonjour"
        area, lay = _page(greet)
        row = QHBoxLayout()
        row.addWidget(_section("Nouveau"))
        row.addStretch(1)
        more = QPushButton("Plus de diagrammes  →")
        more.setFlat(True)
        more.setStyleSheet(f"color: {T['accent_line']}; border: none; background: transparent;")
        more.clicked.connect(lambda: self.select("new"))
        row.addWidget(more)
        lay.addLayout(row)
        featured = dict(templates.TEMPLATES)
        keys = ("blank", "flow", "network", "org")
        lay.addLayout(self._tiles([(key, featured[key]) for key in keys], cols=4))
        lay.addSpacing(10)
        lay.addWidget(_section("Récent"))
        self.recent_home = self._recent_tree()
        lay.addWidget(self.recent_home, 1)
        return area

    def _new(self) -> QWidget:
        area = QWidget()
        area.setObjectName("BackstagePage")
        lay = QVBoxLayout(area)
        lay.setContentsMargins(36, 26, 36, 22)
        lay.setSpacing(10)
        title = QLabel("Nouveau diagramme")
        title.setObjectName("BackstageTitle")
        lay.addWidget(title)
        intro = QLabel("Choisissez un type : une page vierge s’ouvrira avec les gabarits de formes correspondants.")
        intro.setObjectName("TemplateIntro")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        header = QHBoxLayout()
        self.template_search = QLineEdit()
        self.template_search.setObjectName("TemplateSearch")
        self.template_search.setPlaceholderText("Rechercher un type de diagramme…")
        self.template_search.setClearButtonEnabled(True)
        self.template_search.addAction(icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.template_count = QLabel()
        self.template_count.setObjectName("TemplateCount")
        header.addWidget(self.template_search, 1)
        header.addWidget(self.template_count)
        lay.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(18)
        self.template_categories = QListWidget()
        self.template_categories.setObjectName("TemplateCategories")
        self.template_categories.setFixedWidth(206)
        category_counts = {category: sum(templates.template_info(key)[0] == category
                                         for key, _title in templates.TEMPLATES)
                           for category in templates.TEMPLATE_CATEGORIES[1:]}
        for category in templates.TEMPLATE_CATEGORIES:
            count = len(templates.TEMPLATES) if category == templates.TEMPLATE_CATEGORIES[0] else \
                category_counts.get(category, 0)
            item = QListWidgetItem(f"{category}  ·  {count}")
            item.setData(Qt.ItemDataRole.UserRole, category)
            self.template_categories.addItem(item)

        self.template_gallery = QWidget()
        self.template_grid = QGridLayout(self.template_gallery)
        self.template_grid.setContentsMargins(2, 2, 8, 8)
        self.template_grid.setHorizontalSpacing(10)
        self.template_grid.setVerticalSpacing(10)
        self.template_results = QScrollArea()
        self.template_results.setObjectName("TemplateResults")
        self.template_results.setWidgetResizable(True)
        self.template_results.setFrameShape(QFrame.Shape.NoFrame)
        self.template_results.setWidget(self.template_gallery)

        content.addWidget(self.template_categories)
        content.addWidget(self.template_results, 1)
        lay.addLayout(content, 1)

        self.template_categories.setCurrentRow(0)
        self._templates_ready = False
        self.template_categories.currentItemChanged.connect(lambda *_: self._refresh_templates())
        self.template_search.textChanged.connect(lambda *_: self._refresh_templates())
        return area

    def _refresh_templates(self) -> None:
        if not hasattr(self, "template_grid"):
            return
        self._templates_ready = True
        selected = self.template_categories.currentItem()
        category = selected.data(Qt.ItemDataRole.UserRole) if selected else templates.TEMPLATE_CATEGORIES[0]
        fold = lambda text: "".join(
            char for char in unicodedata.normalize("NFKD", text.casefold())
            if not unicodedata.combining(char))
        query = fold(self.template_search.text()).strip()
        filtered = []
        for key, title in templates.TEMPLATES:
            item_category, description, keywords = templates.template_info(key)
            if category != templates.TEMPLATE_CATEGORIES[0] and item_category != category:
                continue
            haystack = fold(f"{title} {item_category} {description} {keywords}")
            if query and not all(term in haystack for term in query.split()):
                continue
            filtered.append((key, title))

        while self.template_grid.count():
            item = self.template_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        columns = 4
        for index, (key, title) in enumerate(filtered):
            tile = TemplateTile(key, title)
            tile.clicked.connect(lambda _=False, template=key: self.newRequested.emit(template))
            self.template_grid.addWidget(tile, index // columns, index % columns)
        self.template_grid.setColumnStretch(columns, 1)
        suffix = "type de diagramme" if len(filtered) == 1 else "types de diagramme"
        self.template_count.setText(f"{len(filtered)} {suffix}")
        if not filtered:
            empty = QLabel("Aucun modèle ne correspond à cette recherche.")
            empty.setObjectName("Hint")
            self.template_grid.addWidget(empty, 0, 0)

    # ------------------------------------------------------------------ Ouvrir
    def _open(self) -> QWidget:
        area, lay = _page("Ouvrir")
        row = QHBoxLayout()
        for text, icon_name, slot in (("Parcourir", "open", self.openRequested.emit),
                                      ("Importer un fichier Visio (.vsdx)", "visio",
                                       lambda: self.commandRequested.emit("import_vsdx"))):
            b = QPushButton(icons.icon(icon_name), "  " + text)
            b.setIconSize(QSize(24, 24))
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_section("Documents récents"))
        self.recent_open = self._recent_tree()
        lay.addWidget(self.recent_open, 1)
        clear = QPushButton("Effacer les documents récents")
        clear.clicked.connect(lambda: self.commandRequested.emit("clear_recent"))
        lay.addWidget(clear, 0, Qt.AlignmentFlag.AlignLeft)
        return area

    def _recent_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setObjectName("RecentList")
        tree.setHeaderLabels(["Nom", "Date de modification"])
        tree.setRootIsDecorated(False)
        tree.setIconSize(QSize(28, 28))
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tree.itemActivated.connect(self._open_item)
        tree.itemClicked.connect(self._open_item)
        return tree

    def _open_item(self, it) -> None:
        path = it.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.openPath.emit(path)

    def set_recent(self, paths: list[str]) -> None:
        for tree in (self.recent_home, self.recent_open):
            tree.clear()
            for p in paths:
                exists = os.path.isfile(p)
                when = time.strftime("%d/%m/%Y %H:%M", time.localtime(os.path.getmtime(p))) if exists \
                    else "Introuvable"
                it = QTreeWidgetItem([f"{os.path.basename(p)}\n{os.path.dirname(p)}", when])
                it.setIcon(0, icons.icon("visio" if p.lower().endswith(".vsdx") else "page_setup"))
                it.setData(0, Qt.ItemDataRole.UserRole, p if exists else None)
                it.setToolTip(0, security.tooltip_html(p))
                if not exists:
                    it.setDisabled(True)
                tree.addTopLevelItem(it)
            if not paths:
                it = QTreeWidgetItem(["Aucun document récent.", ""])
                it.setDisabled(True)
                tree.addTopLevelItem(it)

    # ------------------------------------------------------------------ Informations
    def _info(self) -> QWidget:
        area, lay = _page("Informations")
        self.info_name = QLabel()
        self.info_name.setTextFormat(Qt.TextFormat.PlainText)
        self.info_name.setStyleSheet("font-size: 16px;")
        lay.addWidget(self.info_name)
        cols = QHBoxLayout()
        cols.setSpacing(30)
        left = QVBoxLayout()
        self.protect_tile = self._action_tile("lock", "Protéger le document",
                                              "Chiffrez le document avec un mot de passe (AES-256).",
                                              "protect")
        left.addWidget(self.protect_tile)
        self.unprotect = QPushButton("Supprimer le mot de passe")
        self.unprotect.clicked.connect(lambda: self.commandRequested.emit("unprotect"))
        left.addWidget(self.unprotect, 0, Qt.AlignmentFlag.AlignLeft)
        left.addWidget(self._action_tile("check_diagram", "Vérifier le diagramme",
                                         "Recherchez les connecteurs non reliés et les formes isolées.",
                                         "check_diagram"))
        left.addStretch(1)
        cols.addLayout(left, 3)
        right = QVBoxLayout()
        right.addWidget(_section("Propriétés"))
        self.props_form = QFormLayout()
        self.props_labels = {}
        for key, label in (("size", "Taille"), ("pages", "Pages"), ("shapes", "Formes"),
                           ("encrypted", "Chiffrement"), ("title", "Titre"), ("author", "Auteur"),
                           ("subject", "Objet")):
            v = QLabel("—")
            v.setTextFormat(Qt.TextFormat.PlainText)
            v.setStyleSheet(f"color: {T['text2']};")
            self.props_form.addRow(label, v)
            self.props_labels[key] = v
        right.addLayout(self.props_form)
        edit = QPushButton("Modifier les propriétés…")
        edit.clicked.connect(lambda: self.commandRequested.emit("properties"))
        right.addWidget(edit, 0, Qt.AlignmentFlag.AlignLeft)
        right.addStretch(1)
        cols.addLayout(right, 2)
        lay.addLayout(cols, 1)
        return area

    def _action_tile(self, icon_name: str, title: str, text: str, cmd: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 6, 0, 6)
        b = QToolButton()
        b.setIcon(icons.icon(icon_name))
        b.setIconSize(QSize(36, 36))
        b.setText(title)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        b.setFixedSize(110, 86)
        b.setStyleSheet(f"QToolButton {{ border: 1px solid {T['border']}; background: {T['surface']}; }}"
                        f"QToolButton:hover {{ background: {T['hover']}; }}")
        b.clicked.connect(lambda: self.commandRequested.emit(cmd))
        row.addWidget(b)
        col = QVBoxLayout()
        h = QLabel(f"<b>{title}</b>")
        d = QLabel(text)
        d.setWordWrap(True)
        d.setStyleSheet(f"color: {T['text2']};")
        col.addWidget(h)
        col.addWidget(d)
        col.addStretch(1)
        row.addLayout(col, 1)
        return box

    def set_info(self) -> None:
        doc = self.win.doc
        self.info_name.setText(f"{self.win.doc_title()}\n{doc.path or 'Pas encore enregistré'}")
        size = "—"
        if doc.path and os.path.isfile(doc.path):
            size = f"{os.path.getsize(doc.path) / 1024:.0f} Ko"
        vals = {"size": size, "pages": str(len(doc.pages)),
                "shapes": str(sum(len(p.shapes()) for p in doc.pages)),
                "encrypted": "AES-256-GCM" if doc.password else "Aucun",
                "title": doc.properties.get("title") or "Ajouter un titre",
                "author": doc.properties.get("author") or "—",
                "subject": doc.properties.get("subject") or "—"}
        for k, v in vals.items():
            self.props_labels[k].setText(v)
        self.unprotect.setVisible(bool(doc.password))

    # ------------------------------------------------------------------ Imprimer
    def _print(self) -> QWidget:
        w = QWidget()
        w.setObjectName("BackstagePage")
        outer = QHBoxLayout(w)
        outer.setContentsMargins(44, 28, 20, 20)
        outer.setSpacing(24)
        left = QVBoxLayout()
        h = QLabel("Imprimer")
        h.setObjectName("BackstageTitle")
        left.addWidget(h)
        row = QHBoxLayout()
        go = QToolButton()
        go.setIcon(icons.icon("print"))
        go.setIconSize(QSize(36, 36))
        go.setText("Imprimer")
        go.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        go.setFixedSize(92, 86)
        go.setStyleSheet(f"QToolButton {{ border: 1px solid {T['border']}; background: {T['surface']}; }}"
                         f"QToolButton:hover {{ background: {T['hover']}; }}")
        go.clicked.connect(self._do_print)
        row.addWidget(go)
        self.copies = QSpinBox()
        self.copies.setRange(1, 99)
        self.copies.setPrefix("Copies : ")
        row.addWidget(self.copies, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        left.addLayout(row)
        left.addWidget(_section("Imprimante"))
        self.printer_box = QComboBox()
        self.printer_box.addItem("Imprimer dans un fichier PDF", "")
        for info in QPrinterInfo.availablePrinters():
            self.printer_box.addItem(info.printerName(), info.printerName())
        default = QPrinterInfo.defaultPrinter()
        if not default.isNull():
            self.printer_box.setCurrentIndex(max(0, self.printer_box.findData(default.printerName())))
        left.addWidget(self.printer_box)
        left.addWidget(_section("Paramètres"))
        self.which = QComboBox()
        self.which.addItems(["Imprimer toutes les pages", "Imprimer la page active"])
        self.which.currentIndexChanged.connect(lambda _i: self._refresh_preview())
        left.addWidget(self.which)
        hint = QLabel("Chaque page est ajustée à la feuille ; l'orientation suit celle de la page.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        left.addWidget(hint)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(300)
        outer.addWidget(lw)
        self.printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        self.preview = QPrintPreviewWidget(self.printer)
        self.preview.setZoomMode(QPrintPreviewWidget.ZoomMode.FitInView)
        self.preview.paintRequested.connect(self._paint_preview)
        outer.addWidget(self.preview, 1)
        return w

    def _pages_to_print(self):
        if self.which.currentIndex() == 1 and self.win.scene() is not None:
            return [self.win.scene()]
        return [p for p in self.win.doc.pages if not p.is_background]  # comme Visio

    def _paint_preview(self, printer) -> None:
        from .export import print_pages
        print_pages(printer, self._pages_to_print())

    def _refresh_preview(self) -> None:
        self.preview.updatePreview()

    def _do_print(self) -> None:
        name = self.printer_box.currentData()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setCopyCount(self.copies.value())
        printer.setDocName(self.win.doc_title())
        if not name:
            from PyQt6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getSaveFileName(self, "Imprimer dans un fichier PDF",
                                                  os.path.splitext(self.win.doc_title())[0] + ".pdf",
                                                  "PDF (*.pdf)")
            if not path:
                return
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(path)
        else:
            printer.setPrinterName(name)
        from .export import print_pages
        print_pages(printer, self._pages_to_print())
        self.back.emit()

    # ------------------------------------------------------------------ Exporter
    def _export(self) -> QWidget:
        area, lay = _page("Exporter")
        lay.addWidget(self._action_tile("pdf", "Créer un document PDF",
                                        "Conserve la mise en page ; idéal pour partager et imprimer.",
                                        "export_pdf"))
        lay.addWidget(_section("Modifier le type de fichier"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(30)
        grid.setVerticalSpacing(6)
        types = (("export_vsdx", "visio", "Dessin Visio (*.vsdx)", "Ouvrable dans Microsoft Visio et LibreOffice."),
                 ("save_as", "save", f"Dessin {APP_NAME} (*.lxd)", "Format natif, chiffrable par mot de passe."),
                 ("export_png", "png", "Image PNG (*.png)", "Image de haute qualité, fond transparent possible."),
                 ("export_jpg", "image", "Image JPEG (*.jpg)", "Image compressée pour le web et les e-mails."),
                 ("export_svg", "svg", "Graphique vectoriel SVG (*.svg)", "Pour le web ou Inkscape."),
                 ("export_html", "export_html", "Page web (*.html)",
                  "Toutes les pages dans un fichier HTML autonome, sans script."))
        for i, (cmd, ic, title, text) in enumerate(types):
            b = QToolButton()
            b.setIcon(icons.icon(ic))
            b.setIconSize(QSize(32, 32))
            b.setText(f"{title}\n{text}")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setMinimumSize(380, 56)
            b.setAutoRaise(True)
            b.setStyleSheet(f"QToolButton {{ text-align: left; padding: 6px; }}"
                            f"QToolButton:hover {{ background: {T['hover']}; }}")
            b.clicked.connect(lambda _=False, c=cmd: self.commandRequested.emit(c))
            grid.addWidget(b, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addStretch(1)
        return area

    # ------------------------------------------------------------------ Sécurité
    def _security(self) -> QWidget:
        area, lay = _page("Sécurité et confidentialité")
        enc = "disponible" if security.encryption_available() else "indisponible (OpenSSL absent)"
        text = (
            f"{APP_NAME} {__version__} protège vos documents :\n\n"
            "•  Aucune macro, aucun script, aucune formule exécutée.\n"
            "•  Fichiers .lxd strictement validés, empreinte SHA-256 contre l'altération.\n"
            f"•  Chiffrement par mot de passe AES-256-GCM + scrypt ({enc}).\n"
            "•  Import .vsdx blindé : bombes de décompression, XXE et ressources externes bloquées.\n"
            "•  Images PNG/JPEG uniquement, métadonnées (EXIF, GPS) supprimées à l'insertion.\n"
            "•  Liens limités à http, https, mailto et aux pages du document, confirmés avant ouverture.\n"
            "•  Écriture atomique, documents privés (0600), aucune connexion réseau.")
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(lab)
        row = QHBoxLayout()
        for t, cmd in (("Effacer les documents récents", "clear_recent"),
                       ("Supprimer les fichiers de récupération", "clear_autosave")):
            b = QPushButton(t)
            b.clicked.connect(lambda _=False, c=cmd: self.commandRequested.emit(c))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return area

