"""Fenêtre principale, disposée comme Visio : barre de titre, ruban, volet Formes,
zone de dessin avec onglets de pages, volets de tâches et barre d'état."""

from __future__ import annotations

import base64
import csv
import io
import math
import os
import unicodedata

from PyQt6.QtCore import (QBuffer, QEvent, QIODevice, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt,
                          QTimer, QUrl)
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QFont, QIcon, QKeySequence,
                         QPainter, QPen, QPixmap)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog,
                             QFontComboBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                             QMainWindow, QMenu, QMessageBox, QSlider, QSplitter,
                             QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from . import (APP_NAME, __version__, FILE_EXT, compat, datavis, export, fileformat, icons, quickstyles,
               security, favorites, fields, shapeops, spellcheck, stencils, swimlanes, templates, vsdx)
from .backstage import Backstage
from .canvas import CanvasArea
from .commands import DocSettingsCommand, PageCommand, ReorderPagesCommand
from .dialogs import (DataGraphicDialog, DataImportDialog, DataLinkDialog, FindReplaceDialog,
                      ImageExportDialog, LayersDialog, OptionsDialog, PageSetupDialog, PasswordDialog, PropertiesDialog,
                      ReorderPagesDialog, RulerGridDialog, ShapeSheetDialog, SnapGlueDialog, ShortcutsDialog,
                      ZoomDialog, FieldDialog, SpellDialog)
from .document import Document
from .items import ConnectorItem, ShapeItem, decode_image
from .panes import (CommentsPane, DrawingExplorerPane, FormatPane, IssuesPane, PanZoomPane,
                    ShapeDataPane, ShapesPane, SizePositionPane, TaskPaneArea)
from .presentation import PresentationView
from .ribbon import ICON, SMALL, Ribbon, RibbonButton, RibbonGallery, RibbonGroup
from .style import T
from .titlebar import FramelessResizer, TitleBar
from .units import (ARROW_LABELS, ARROWS, DASH_LABELS, DASHES, PAGE_SIZES, PX_PER_MM, ROUTE_LABELS,
                    ROUTES, THEMES, mm_to_px)
from .widgets import ColorButton

CLIP_MIME = "application/x-linxdiagram-clip"
LXD_FILTER = f"Dessin {APP_NAME} (*{FILE_EXT})"
VSDX_FILTER = "Dessin Visio (*.vsdx)"
LINE_WEIGHTS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.25, 3.0, 4.5, 6.0)
FONT_SIZES = (6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72)
CFF_TAB = "Diagramme de flux interfonctionnel"
CONTAINER_TAB = "Format du conteneur"
SYMBOLS = "©®™€£$¥§¶°±×÷≈≠≤≥∞µπΩΣ√∑←→↑↓↔⇒✓✗•…«»"
BACKGROUNDS = (("#ffffff", "Blanc"), ("#f3f2f1", "Gris clair"), ("#eaf1fb", "Bleu clair"),
               ("#eef7ee", "Vert clair"), ("#fdf5e6", "Sable"), ("#f6effa", "Lavande"),
               ("#2b2b2b", "Ardoise"))
BORDERS = (("simple", "Simple"), ("band", "Bandeau"), ("frame", "Cadre technique"), ("modern", "Moderne"))
PANES = (("format", "Format de la forme", "format_panel"), ("size", "Taille et position", "size_position"),
         ("data", "Données de forme", "shape_data"), ("comments", "Commentaires", "comments"),
         ("issues", "Problèmes", "check_diagram"), ("panzoom", "Panoramique et zoom", "pan_zoom"),
         ("drawing", "Explorateur de dessin", "layers"))


def _clean_data_headers(headers: list[str]) -> list[str]:
    if not headers or len(headers) > fileformat.MAX_DATA_FIELDS:
        raise datavis.DataError(f"Le CSV doit contenir entre 1 et {fileformat.MAX_DATA_FIELDS} colonnes.")
    clean = [security.clean_line(h, 100) for h in headers]
    if any(not h for h in clean) or len(set(clean)) != len(clean):
        raise datavis.DataError("Pour lier les données, chaque colonne CSV doit avoir un nom unique de 100 caractères maximum.")
    return clean


def _csv_safe_cell(value: str) -> str:
    """Neutralise les cellules texte actives dans Excel/LibreOffice sans casser les lignes CSV."""
    value = str(value)
    index = 0
    while index < len(value) and (value[index].isspace() or value[index] == "\ufeff"
                                  or unicodedata.category(value[index]) == "Cf"):
        index += 1
    return "'" + value if value[index:index + 1] in ("=", "+", "-", "@") else value


def _merge_linked_data(existing: dict, old_fields: list[str], headers: list[str], row: list[str],
                       field_map: dict[str, str] | None = None) -> tuple[dict, int]:
    field_map = field_map or {header: header for header in headers}
    incoming = {field_map[header]: row[i] if i < len(row) else ""
                for i, header in enumerate(headers) if header in field_map}
    old = set(old_fields)
    manual = [(key, value) for key, value in existing.items() if key not in old and key not in incoming]
    room = max(0, fileformat.MAX_DATA_FIELDS - len(incoming))
    kept = manual[:room]
    # Les champs du CSV ont priorité, les propriétés manuelles restantes sont conservées si possible.
    return {**incoming, **dict(kept)}, len(manual) - len(kept)


def _data_link_identity(link: dict) -> tuple[str, str, str]:
    return os.path.normcase(os.path.normpath(link.get("path", ""))), link.get("source_key", ""), \
        link.get("shape_key", "")


def _data_link_field_map(shape: ShapeItem, path: str, headers: list[str], old_link: dict | None,
                        existing_data: dict | None = None, source_key: str = "") -> dict[str, str]:
    """Donne aux colonnes CSV un nom unique sans écraser les données d'autres sources."""
    old_link = old_link or {}
    old_fields = set(old_link.get("fields", []))
    reserved = set(shape.data if existing_data is None else existing_data) - old_fields
    old_map = old_link.get("field_map", {})
    stem = os.path.splitext(os.path.basename(path))[0] or "CSV"
    out: dict[str, str] = {}
    limit = max(0, fileformat.MAX_DATA_FIELDS - len(reserved))
    selected = list(headers[:limit])
    source_key = old_link.get("source_key", source_key)
    if source_key in headers and source_key not in selected and limit:
        selected[-1] = source_key
    for header in selected:
        target = old_map.get(header)
        if not target or target in reserved:
            base = header if header not in reserved else security.clean_line(f"{stem} · {header}", 100)
            target = base or "Donnée CSV"
            suffix_index = 2
            while target in reserved:
                suffix = f" ({suffix_index})"
                target = security.clean_line(base[:100 - len(suffix)] + suffix, 100)
                suffix_index += 1
        out[header] = target
        reserved.add(target)
    return out


def tile_rects(n: int, area: QRect) -> list[QRect]:
    """Emplacements de « Réorganiser tout » : 1, 2 ou 3 colonnes selon le nombre de fenêtres."""
    if n <= 0:
        return []
    cols = 1 if n == 1 else 2 if n <= 4 else 3
    rows = -(-n // cols)
    cw, ch = area.width() // cols, area.height() // rows
    return [QRect(area.x() + (i % cols) * cw, area.y() + (i // cols) * ch, cw, ch) for i in range(n)]


class MainWindow(QMainWindow):
    def __init__(self, ctx, doc: Document | None = None, title_hint: str | None = None):
        super().__init__()
        self.ctx = ctx
        self.settings = ctx.settings
        self.doc: Document | None = None
        self.title_hint = title_hint
        self.a: dict[str, QAction] = {}
        self._connected_scenes: set[int] = set()
        self._updating_ui = False
        self._presentation = None
        self._paste_count = 0
        self.native_frame = self.settings.value("ui/native_titlebar", compat.IS_MACOS, type=bool)
        if not self.native_frame:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.resizer = FramelessResizer(self)
        self.setWindowIcon(icons.app_icon())
        self.setAcceptDrops(True)
        self._build_actions()
        self._build_ui()
        self._build_ribbon()
        self._build_statusbar()
        self._build_search_entries()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave)
        self.apply_autosave_interval()
        self.quick_popup = None
        self._quick_hide = QTimer(self)
        self._quick_hide.setSingleShot(True)
        self._quick_hide.timeout.connect(self._hide_quick_shapes)
        self.set_document(doc or Document())
        geo = self.settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1440, 900)
        self._fit_to_screen(first_run=geo is None)

    def _fit_to_screen(self, first_run: bool = False) -> None:
        """La fenêtre ne dépasse jamais l'écran (sinon les boutons Fermer/Agrandir sont invisibles)."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        too_big = self.width() > avail.width() or self.height() > avail.height()
        if too_big or (first_run and (avail.width() < 1500 or avail.height() < 950)):
            self.resize(min(self.width(), avail.width()), min(self.height(), avail.height()))
            self.move(avail.topLeft())
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    # ================================================================== actions
    def _act(self, key, text, icon=None, shortcut=None, slot=None, checkable=False, tip=None, label=None):
        a = QAction(label or text, self)
        if icon:
            a.setIcon(icons.icon(icon))
            a.setProperty("icon_name", icon)
        if shortcut:
            seqs = shortcut if isinstance(shortcut, (list, tuple)) else [shortcut]
            a.setShortcuts([QKeySequence(s) for s in seqs])
            first = QKeySequence(seqs[0]).toString(QKeySequence.SequenceFormat.NativeText)
            a.setToolTip(f"<b>{text} ({first})</b>" + (f"<br>{tip}" if tip else ""))
        else:
            a.setToolTip(f"<b>{text}</b>" + (f"<br>{tip}" if tip else ""))
        a.setStatusTip(tip or text)
        a.setProperty("search_text", text)
        a.setCheckable(checkable)
        if slot is not None:
            if checkable:
                a.toggled.connect(slot)
            else:
                a.triggered.connect(lambda _=False, s=slot: s())
        self.addAction(a)
        self.a[key] = a
        return a

    def _plain_message(self, icon: QMessageBox.Icon, title: str, text: str) -> None:
        box = QMessageBox(icon, title, str(text), QMessageBox.StandardButton.Ok, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.exec()

    def _sc(self, fn):
        """Exécute fn(scène) s'il y a une page affichée."""
        def run():
            sc = self.scene()
            if sc is not None:
                fn(sc)
        return run

    def _build_actions(self) -> None:
        A = self._act
        SK = QKeySequence.StandardKey
        # Fichier
        A("new", "Nouveau", "new", SK.New, lambda: self.show_backstage("new"))
        A("open", "Ouvrir…", "open", SK.Open, self.open_dialog)
        A("save", "Enregistrer", "save", SK.Save, self.save)
        A("save_as", "Enregistrer sous…", "save_as", ["F12", "Ctrl+Shift+S"], self.save_as)
        A("import_vsdx", "Importer un fichier Visio…", "visio", None, self.import_vsdx_dialog,
          label="Importer .vsdx")
        A("export_pdf", "Exporter en PDF…", "pdf", None, self.export_pdf)
        A("export_png", "Exporter en PNG…", "png", None, lambda: self.export_image("png"))
        A("export_jpg", "Exporter en JPEG…", "image", None, lambda: self.export_image("jpg"))
        A("export_svg", "Exporter en SVG…", "svg", None, self.export_svg)
        A("export_html", "Enregistrer comme page web…", "export_html", None, self.export_html)
        A("export_vsdx", "Exporter au format Visio…", "visio", None, self.export_vsdx,
          label="Exporter .vsdx")
        A("print", "Imprimer", "print", SK.Print, lambda: self.show_backstage("print"))
        A("protect", "Protéger le document par mot de passe…", "lock", None, self.protect,
          label="Protéger le document")
        A("properties", "Propriétés du document…", "properties", None, self.edit_properties,
          label="Propriétés")
        A("close", "Fermer", "close", "Ctrl+W", self.close)
        A("quit", "Quitter", None, SK.Quit, self.ctx.quit)
        A("options", "Options", "options", None, self.show_options)
        # Presse-papiers / édition
        A("undo", "Annuler", "undo", SK.Undo, lambda: self.doc.undo_stack.undo())
        A("redo", "Rétablir", "redo", ["Ctrl+Y", "Ctrl+Shift+Z"], lambda: self.doc.undo_stack.redo())
        A("cut", "Couper", "cut", SK.Cut, self.cut)
        A("copy", "Copier", "copy", SK.Copy, self.copy)
        A("paste", "Coller", "paste", SK.Paste, self.paste)
        A("paste_special", "Collage spécial…", "paste", "Ctrl+Alt+V", self.paste_special,
          tip="Choisit le format à coller : formes, image ou texte sans mise en forme.")
        A("duplicate", "Dupliquer", "duplicate", "Ctrl+D", self.duplicate)
        A("delete", "Supprimer", "delete", [QKeySequence(Qt.Key.Key_Delete)], self.delete)
        A("select_all", "Tout sélectionner", "select_all", SK.SelectAll, self._sc(lambda s: s.select_all()))
        A("find", "Rechercher…", "find", SK.Find, lambda: FindReplaceDialog(self, self).exec())
        A("replace", "Remplacer…", "replace", None, lambda: FindReplaceDialog(self, self, replace=True).exec())
        A("edit_text", "Modifier le texte", "edit_text", "F2", self.edit_text)
        A("format_painter", "Reproduire la mise en forme", "format_painter", None, self.format_painter,
          checkable=True, tip="Copie la mise en forme de la forme sélectionnée et l'applique à une autre.")
        # Outils
        self.tool_group = QActionGroup(self)
        for key, text, ic, sc, tip in (
                ("select", "Outil Pointeur", "pointer", "Ctrl+1", "Sélectionner, déplacer et redimensionner."),
                ("text", "Texte", "tool_text", "Ctrl+2", "Cliquez sur la page pour écrire du texte."),
                ("connector", "Connecteur", "connector", "Ctrl+3", "Faites glisser d'une forme à une autre."),
                ("line", "Ligne", "line", "Ctrl+6", "Tracer un trait."),
                ("pen", "Stylo", "pen_tool", "Ctrl+7", "Tracer un dessin à main levée."),
                ("rectangle", "Rectangle", "rect_tool", "Ctrl+8", "Dessiner un rectangle."),
                ("ellipse", "Ellipse", "ellipse_tool", "Ctrl+9", "Dessiner une ellipse."),
                ("freeform", "Forme libre", "freeform", "Ctrl+5", "Dessiner une forme fermée à main levée."),
                ("arc", "Arc", "arc", None, "Tracer un arc entre deux points."),
                ("port", "Point de connexion", "ports", "Ctrl+Shift+1",
                 "Ctrl + clic sur une forme : ajouter un point. Clic : le sélectionner, puis le "
                 "glisser ou le supprimer (Suppr)."),
                ("textblock", "Bloc de texte", "text_block", "Ctrl+Shift+4",
                 "Déplacer ou redimensionner la zone de texte d'une forme.")):
            act = A(f"tool_{key}", text, ic, sc, None, checkable=True, tip=tip,
                    label="Pointeur" if key == "select" else None)
            act.triggered.connect(lambda _=False, k=key: self.doc.set_tool(k))
            self.tool_group.addAction(act)
        self.a["tool_select"].setChecked(True)
        # Police / paragraphe
        A("bold", "Gras", "bold", SK.Bold, lambda on: self._text_style({"bold": on}), checkable=True)
        A("italic", "Italique", "italic", SK.Italic, lambda on: self._text_style({"italic": on}), checkable=True)
        A("underline", "Souligné", "underline", SK.Underline, lambda on: self._text_style({"underline": on}),
          checkable=True)
        A("strike", "Barré", "strike", None, lambda on: self._text_style({"strike": on}), checkable=True)
        A("font_grow", "Augmenter la taille de police", "font_grow", "Ctrl+Shift+>", lambda: self._font_step(1))
        A("font_shrink", "Diminuer la taille de police", "font_shrink", "Ctrl+Shift+<", lambda: self._font_step(-1))
        A("clear_format", "Effacer la mise en forme", "clear_format", None, self.clear_format)
        for key, text, sc in (("left", "Aligner le texte à gauche", "Ctrl+Shift+L"),
                              ("center", "Centrer", "Ctrl+Shift+C"),
                              ("right", "Aligner le texte à droite", "Ctrl+Shift+R"),
                              ("justify", "Justifier", "Ctrl+Shift+J")):
            A(f"halign_{key}", text, "justify" if key == "justify" else f"align_text_{key}", sc,
              lambda k=key: self._text_style({"halign": k}))
        A("bullets", "Puces", "bullets", None, lambda on: self._text_style({"bullets": on}), checkable=True,
          tip="Ajoute ou retire les puces des paragraphes du texte.")
        A("indent_more", "Augmenter le retrait", "indent_more", None, lambda: self._indent_step(1))
        A("indent_less", "Diminuer le retrait", "indent_less", None, lambda: self._indent_step(-1))
        for key, text, sc in (("top", "Aligner en haut", "Ctrl+Shift+T"),
                              ("middle", "Aligner au milieu", "Ctrl+Shift+M"),
                              ("bottom", "Aligner en bas", "Ctrl+Shift+V")):
            A(f"valign_{key}", text, f"valign_{key}", sc, lambda k=key: self._text_style({"valign": k}))
        # Organiser
        A("front", "Mettre au premier plan", "front", "Ctrl+Shift+F", lambda: self._reorder("front"),
          label="Premier plan")
        A("back", "Mettre à l'arrière-plan", "back", "Ctrl+Shift+B", lambda: self._reorder("back"),
          label="Arrière-plan")
        A("forward", "Avancer", "forward", None, lambda: self._reorder("forward"))
        A("backward", "Reculer", "backward", None, lambda: self._reorder("backward"))
        A("group", "Grouper", "group", "Ctrl+Shift+G", self._sc(lambda s: s.group_selection()))
        A("ungroup", "Dissocier", "ungroup", "Ctrl+Shift+U", self._sc(lambda s: s.ungroup_selection()))
        A("rotate_right", "Faire pivoter à droite de 90°", "rotate_right", "Ctrl+R",
          self._sc(lambda s: s.rotate_selection(90)))
        A("rotate_left", "Faire pivoter à gauche de 90°", "rotate_left", "Ctrl+L",
          self._sc(lambda s: s.rotate_selection(-90)))
        A("flip_h", "Retourner horizontalement", "flip_h", "Ctrl+H", self._sc(lambda s: s.flip_selection(True)))
        A("flip_v", "Retourner verticalement", "flip_v", "Ctrl+J", self._sc(lambda s: s.flip_selection(False)))
        for key, text in (("left", "Aligner à gauche"), ("center", "Aligner au centre"),
                          ("right", "Aligner à droite"), ("top", "Aligner en haut"),
                          ("middle", "Aligner au milieu"), ("bottom", "Aligner en bas")):
            A(f"align_{key}", text, f"align_{key}", None, lambda k=key: self.scene().align(k))
        A("distribute_h", "Distribuer horizontalement", "distribute_h", None,
          self._sc(lambda s: s.distribute("h")))
        A("distribute_v", "Distribuer verticalement", "distribute_v", None,
          self._sc(lambda s: s.distribute("v")))
        A("lock", "Verrouiller la forme", "lock", None, self._sc(lambda s: s.set_locked(s.selected_shapes(), True)),
          tip="Empêche de déplacer, redimensionner ou supprimer les formes sélectionnées.")
        A("unlock", "Déverrouiller la forme", "lock", None,
          self._sc(lambda s: s.set_locked(s.selected_shapes(), False)))
        # Insertion
        A("page_add", "Page vierge", "page_add", None, self.add_page, tip="Insère une nouvelle page.")
        A("page_dup", "Dupliquer la page", "page_dup", None, self.duplicate_page)
        A("page_del", "Supprimer la page", "page_del", None, self.delete_page)
        A("page_rename", "Renommer la page…", "page_rename", None, self.rename_page)
        A("add_favorite", "Ajouter aux Favoris…", "shapes_panel", None, self.add_to_favorites,
          tip="Enregistre la sélection dans le gabarit Favoris (Mes formes) pour la réutiliser.")
        A("container_fit", "Ajuster au contenu", "auto_size", None,
          lambda: self._with_container(lambda sc, c: sc.container_fit(c)),
          tip="Redimensionne le conteneur autour des formes qu'il contient.")
        A("container_select", "Sélectionner le contenu", "select_all", None,
          lambda: self._with_container(lambda sc, c: sc.container_select_contents(c)))
        A("container_disband", "Désassembler le conteneur", "ungroup", None,
          lambda: self._with_container(lambda sc, c: sc.container_disband(c)),
          tip="Supprime le conteneur en conservant les formes qu'il contient.")
        A("spelling", "Orthographe", "spelling", "F7", self.check_spelling,
          tip="Vérifie l'orthographe de tous les textes du document (dictionnaires Hunspell du système).")
        A("insert_field", "Champ", "field", None, self.insert_field,
          tip="Insère un champ qui se met à jour : date, heure, numéro de page, nom du fichier…")
        A("page_background_new", "Page d'arrière-plan", "background_page", None, self.add_background_page,
          tip="Insère une page d'arrière-plan (cartouche, logo, filigrane) affichée derrière les pages "
              "qui l'utilisent.")
        A("page_is_background", "Page d'arrière-plan", None, None, self.toggle_background_page, checkable=True,
          label="Utiliser comme page d'arrière-plan")
        A("image", "Images", "image", None, self.insert_image_dialog, tip="Insère une image PNG ou JPEG.")
        A("textbox", "Zone de texte", "textbox", None, lambda: self._insert("basic.text"))
        A("link", "Lien hypertexte…", "link", "Ctrl+K", self.edit_link, label="Lien")
        A("open_link", "Ouvrir le lien hypertexte", "link", None, self.open_link)
        A("screentip", "Info-bulle d'écran…", "screentip", None, self.edit_tip)
        A("page_setup", "Mise en page…", "page_setup", "Shift+F5", self.page_setup_dialog)
        # Création
        A("portrait", "Portrait", "orientation", None, lambda: self.set_orientation(False))
        A("landscape", "Paysage", "orientation", None, lambda: self.set_orientation(True))
        A("fit_drawing", "Ajuster au dessin", "fit_drawing", None, self.fit_page_to_drawing)
        A("auto_size", "Taille automatique", "auto_size", None, self.toggle_auto_size, checkable=True,
          tip="La page s'agrandit automatiquement quand le dessin dépasse.")
        A("relayout_tb", "De haut en bas", "relayout", None, self._sc(lambda s: s.relayout("TB")))
        A("relayout_lr", "De gauche à droite", "relayout", None, self._sc(lambda s: s.relayout("LR")))
        A("line_jumps", "Afficher les sauts de ligne", "line_jumps", None, self.toggle_line_jumps,
          checkable=True)
        # Données / processus / révision
        A("data_org", "Organigramme à partir de données…", "data_visualizer", None,
          lambda: self.create_from_data("org"))
        A("data_flow", "Diagramme de flux à partir de données…", "data_visualizer", None,
          lambda: self.create_from_data("flow"))
        A("data_link", "Lier les formes à un fichier CSV…", "data_visualizer", None,
          self.link_data, tip="Ajoute une source CSV locale sans écraser les autres liens.")
        A("data_refresh", "Actualiser les données liées", "data_visualizer", None,
          self.refresh_linked_data, tip="Relit les fichiers CSV locaux associés aux formes.")
        A("data_unlink", "Dissocier la sélection", "data_visualizer", None,
          self.unlink_data, tip="Retire le lien CSV et conserve les données déjà importées.")
        A("data_graphic", "Configurer un graphique de données…", "data_visualizer", None,
          self.set_data_graphic, tip="Affiche une propriété et personnalise les règles de couleur des statuts.")
        A("data_graphic_clear", "Supprimer le graphique de données", "data_visualizer", None,
          self.clear_data_graphic)
        A("shape_report", "Rapports de forme…", "shape_report", None, self.shape_report,
          tip="Exporte la liste des formes et de leurs données (CSV).")
        A("subprocess", "Créer à partir de la sélection", "subprocess", None, self.create_subprocess,
          tip="Déplace la sélection vers une nouvelle page reliée par un sous-processus.")
        A("check_diagram", "Vérifier le diagramme", "check_diagram", None, self.check_diagram)
        A("auto_align_space", "Aligner automatiquement et espacer", "position", None,
          self._sc(lambda s: s.auto_align_space()),
          tip="Aligne les formes reliées presque alignées et égalise leurs espacements.")
        A("auto_align", "Aligner automatiquement", "align", None,
          self._sc(lambda s: s.auto_align_space(space=False)))
        A("auto_space", "Espacement automatique", "distribute_v", None,
          self._sc(lambda s: s.auto_align_space(align=False)))
        for op, label in shapeops.OPERATIONS.items():
            A(f"op_{op}", label, "union" if op == "union" else "shape_ops", None,
              lambda _=False, o=op: self._shape_op(o))
        A("cff_lane", "Couloir", "swimlane", None, self._sc(lambda s: s.cff_insert_lane()),
          tip="Insère un couloir après le couloir sélectionné (ou à la fin).")
        A("cff_lane_before", "Insérer un couloir avant", "swimlane", None,
          self._sc(lambda s: s.cff_insert_lane(before=True)))
        A("cff_lane_after", "Insérer un couloir après", "swimlane", None, self._sc(lambda s: s.cff_insert_lane()))
        A("cff_phase", "Séparateur", "separator", None, self._sc(lambda s: s.cff_insert_phase()),
          tip="Ajoute une phase (séparateur) à la structure.")
        A("cff_new_h", "Diagramme horizontal", "swimlane", None,
          lambda: self._new_cff("h"), tip="Couloirs horizontaux avec barre de titre.")
        A("cff_new_v", "Diagramme vertical", "swimlane_v", None,
          lambda: self._new_cff("v"), tip="Couloirs verticaux (colonnes) avec barre de titre.")
        A("cff_layout", "Disposer les couloirs", "relayout", None, self._sc(lambda s: s.cff_layout()),
          tip="Remet les couloirs bout à bout et réaligne leur contenu.")
        A("cff_dir_h", "Horizontale", "swimlane", None, lambda: self._cff_orientation("h"), checkable=True,
          tip="Couloirs en lignes, processus de gauche à droite.")
        A("cff_dir_v", "Verticale", "swimlane_v", None, lambda: self._cff_orientation("v"), checkable=True,
          tip="Couloirs en colonnes, processus de haut en bas.")
        A("cff_title", "Barre de titre", None, None,
          lambda on: self._cff_option("title", on), checkable=True,
          tip="Affiche ou masque la barre de titre du diagramme.")
        A("cff_separators", "Séparateurs", None, None,
          lambda on: self._cff_option("hidden", not on), checkable=True,
          tip="Affiche ou masque les séparateurs de phases.")
        A("cff_rotate", "Faire pivoter les étiquettes des couloirs", "rotate_right", None,
          lambda on: self._cff_option("rotate", on), checkable=True,
          tip="Écrit les noms des couloirs dans l'autre sens.")
        A("new_comment", "Nouveau commentaire", "comment", "Ctrl+Alt+M", self.new_comment)
        A("delete_comment", "Supprimer les commentaires de la forme", "delete", None,
          self._sc(lambda s: s.single_selected and s.delete_comment(s.single_selected)))
        A("prev_comment", "Précédent", "prev_comment", None, lambda: self.step_comment(-1))
        A("next_comment", "Suivant", "next_comment", None, lambda: self.step_comment(1))
        A("layers", "Propriétés des calques…", "layers", None, self.layers_dialog)
        A("shapesheet", "Afficher la ShapeSheet", "shapesheet", None, self.show_shapesheet, label="ShapeSheet")
        # Affichage
        A("presentation", "Plein écran", "presentation", "F5", self.start_presentation,
          tip="Affiche les pages en plein écran (flèches pour naviguer, Échap pour quitter).")
        A("rulers", "Règle", None, None, self.toggle_rulers, checkable=True)
        A("page_breaks", "Sauts de page", None, None,
          lambda on: self.doc.apply_settings({"page_breaks": on}), checkable=True,
          tip="Montre où la page sera coupée à l'impression en taille réelle.")
        A("ruler_guides", "Repères", None, None, self.toggle_ruler_guides, checkable=True,
          tip="Affiche les repères tirés depuis les règles et l'accrochage à ces repères.")
        A("arrange_all", "Réorganiser tout", "new_window", None, self.arrange_windows,
          tip="Place toutes les fenêtres LinXdiagram côte à côte.")
        A("cascade", "Cascade", "new_window", None, self.cascade_windows,
          tip="Superpose les fenêtres en les décalant.")
        A("grid", "Grille", None, None, lambda on: self._view_setting("grid", on), checkable=True)
        A("guides", "Grille dynamique", None, None, lambda on: self._view_setting("guides", on), checkable=True)
        A("snap", "Magnétisme", None, None, lambda on: self._view_setting("snap", on), checkable=True)
        A("ports", "Points de connexion", None, None, lambda on: self._view_setting("ports", on), checkable=True)
        A("autoconnect", "AutoConnect", None, None, lambda on: self._view_setting("autoconnect", on),
          checkable=True)
        A("zoom", "Zoom…", "zoom", None, self.zoom_dialog)
        A("zoom_in", "Zoom avant", "zoom_in", [SK.ZoomIn, "Ctrl+="], lambda: self.view.zoom_by(1.25))
        A("zoom_out", "Zoom arrière", "zoom_out", SK.ZoomOut, lambda: self.view.zoom_by(0.8))
        A("fit_page", "Ajuster à la fenêtre", "fit", "Ctrl+Shift+W", lambda: self.view.fit_page())
        A("fit_width", "Largeur de page", "fit_width", None, lambda: self.view.fit_width())
        A("zoom_100", "100 %", "zoom_100", "Ctrl+0", lambda: self.view.set_zoom(1.0))
        A("new_window", "Nouvelle fenêtre", "new_window", None, lambda: self.ctx.new_window().show_backstage("home"))
        A("show_shapes", "Formes", "shapes_panel", None, self._toggle_shapes, checkable=True)
        for key, title, ic in PANES:
            A(f"pane_{key}", title, ic, None, lambda on, k=key: self.task_panes.set_visible(k, on),
              checkable=True)
        A("toggle_ribbon", "Réduire le ruban", "toggle_ribbon", "Ctrl+F1",
          lambda: self.ribbon.set_collapsed(not self.ribbon.is_collapsed()))
        A("next_page", "Page suivante", "nav_next", "Ctrl+PgDown", lambda: self._step_page(1))
        A("prev_page", "Page précédente", "nav_prev", "Ctrl+PgUp", lambda: self._step_page(-1))
        A("shortcuts", "Raccourcis clavier", "keyboard", None, lambda: ShortcutsDialog(self).exec())
        A("about", "À propos", "about", None, self.about)
        A("security", "Sécurité", "shield", None, lambda: self.show_backstage("security"))
        A("command_search", "Rechercher une commande", "search", "Alt+Q", self._focus_search)

    # ================================================================== interface
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("WindowFrame")
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.undo_menu = QMenu(self)
        self.undo_menu.aboutToShow.connect(self._fill_undo_menu)
        if not self.native_frame:
            self.titlebar = TitleBar(self, [self.a["save"], self.a["undo"], self.a["redo"]], self.undo_menu)
            rl.addWidget(self.titlebar)
        else:
            self.titlebar = None
        self.stack = QStackedWidget()
        rl.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        editor = QWidget()
        el = QVBoxLayout(editor)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(0)
        self.ribbon = Ribbon()
        self.ribbon.fileRequested.connect(lambda: self.show_backstage("home"))
        el.addWidget(self.ribbon)
        self.ribbon.set_collapsed(self.settings.value("layout/ribbon_collapsed", False, type=bool))
        if self.native_frame:
            from .titlebar import CommandSearch
            self.search_box = CommandSearch(self)
            self.search_box.setStyleSheet("QLineEdit { background: rgba(255,255,255,0.18); color: white; }")
            self.ribbon.tools_layout.addWidget(self.search_box)
        else:
            self.search_box = self.titlebar.search

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.shapes_panel = ShapesPane()
        self.shapes_panel.shapeActivated.connect(self._add_at_center)
        self.shapes_panel.favorites = self._favorites()
        self.shapes_panel.favoriteMenu.connect(self._favorite_menu)
        self.shapes_panel.quickShapeChanged.connect(lambda t: setattr(self.doc, "quick_shape", t))
        self.shapes_panel.closed.connect(lambda: self.a["show_shapes"].setChecked(False))
        self.shapes_panel.categoriesChanged.connect(lambda: QTimer.singleShot(0, self._update_cff_tab))
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.canvas = CanvasArea()
        self.view = self.canvas.view
        self.view.zoomChanged.connect(self._zoom_changed)
        self.view.contextMenuRequested.connect(self._context_menu)
        self.view.favoriteDropped.connect(self.insert_favorite)
        self.view.imageDropped.connect(self.insert_image)
        cl.addWidget(self.canvas, 1)
        cl.addWidget(self._build_page_bar())
        self.task_panes = TaskPaneArea()
        self.format_pane = FormatPane(self)
        self.size_pane = SizePositionPane(self)
        self.data_pane = ShapeDataPane(self)
        self.comments_pane = CommentsPane(self)
        self.issues_pane = IssuesPane(self)
        self.panzoom_pane = PanZoomPane(self)
        self.drawing_pane = DrawingExplorerPane(self)
        for (key, title, _ic), body in zip(PANES, (self.format_pane, self.size_pane, self.data_pane,
                                                  self.comments_pane, self.issues_pane, self.panzoom_pane,
                                                  self.drawing_pane)):
            self.task_panes.add(key, title, body)
        self.task_panes.visibilityChanged.connect(self._pane_visibility)
        self.task_panes.setMinimumWidth(280)
        self.splitter.addWidget(self.shapes_panel)
        self.splitter.addWidget(center)
        self.splitter.addWidget(self.task_panes)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 900, 300])
        splitter_state = self.settings.value("layout/editor_splitter")
        if splitter_state:
            self.splitter.restoreState(splitter_state)
        el.addWidget(self.splitter, 1)
        self.backstage = Backstage(self)
        self.backstage.back.connect(self.hide_backstage)
        self.backstage.newRequested.connect(self.new_from_template)
        self.backstage.openRequested.connect(self.open_dialog)
        self.backstage.openPath.connect(self.open_path)
        self.backstage.commandRequested.connect(self._backstage_command)
        self.stack.addWidget(editor)
        self.stack.addWidget(self.backstage)
        self.a["show_shapes"].setChecked(self.settings.value("panes/shapes", True, type=bool))
        for key, _t, _i in PANES:
            on = self.settings.value(f"panes/{key}", key == "format", type=bool)
            self.a[f"pane_{key}"].setChecked(on)
        self.task_panes._update_self()

    def _build_page_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("PageBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setFixedHeight(32)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 0, 4, 0)
        bl.setSpacing(0)
        for key in ("prev_page", "next_page"):
            b = QToolButton()
            b.setDefaultAction(self.a[key])
            b.setIconSize(QSize(12, 12))
            bl.addWidget(b)
        self.page_tabs = QTabBar()
        self.page_tabs.setObjectName("PageTabs")
        self.page_tabs.setDocumentMode(True)
        self.page_tabs.setExpanding(False)
        self.page_tabs.setDrawBase(False)
        self.page_tabs.setMovable(True)  # glisser un onglet réordonne les pages, comme Visio
        self.page_tabs.tabMoved.connect(self._page_tab_moved)
        self.page_tabs.currentChanged.connect(self._page_tab_changed)
        self.page_tabs.tabBarDoubleClicked.connect(lambda _i: self.rename_page())
        self.page_tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.page_tabs.customContextMenuRequested.connect(self._page_menu)
        bl.addWidget(self.page_tabs)
        self.all_pages = QToolButton()
        self.all_pages.setText("Tout ")
        self.all_pages.setIcon(icons.icon("nav_all"))
        self.all_pages.setIconSize(QSize(10, 10))
        self.all_pages.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.all_pages.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.all_pages.setToolTip("Toutes les pages")
        self.all_pages.clicked.connect(self._all_pages_menu)
        bl.addWidget(self.all_pages)
        add = QToolButton()
        add.setDefaultAction(self.a["page_add"])
        add.setIconSize(QSize(16, 16))
        add.setToolTip("Insérer une page")
        bl.addWidget(add)
        bl.addStretch(1)
        return bar

    # ------------------------------------------------------------------ ruban
    def _menu(self, *entries) -> QMenu:
        m = QMenu(self)
        for e in entries:
            if e is None:
                m.addSeparator()
            elif isinstance(e, QAction):
                m.addAction(e)
            elif isinstance(e, QMenu):
                m.addMenu(e)
            else:
                text, ic, slot = e
                act = m.addAction(text)
                if ic:
                    act.setIcon(icons.icon(ic))
                act.triggered.connect(lambda _=False, s=slot: s())
        return m

    def _color_button(self, icon_name, text, initial, slot, allow_none=True, none_label="Aucun",
                      kind=SMALL) -> ColorButton:
        b = ColorButton(icon_name, text, initial, allow_none=allow_none, none_label=none_label)
        b.setAutoRaise(True)
        if kind == SMALL:
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setIconSize(QSize(16, 16))
            b.setFixedHeight(22)
        else:
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(34, 22)
        b.colorPicked.connect(slot)
        return b

    def _build_ribbon(self) -> None:
        a = self.a
        R = RibbonButton
        # ======================================================= Accueil
        home = self.ribbon.add_page("Accueil")
        g = RibbonGroup("Presse-papiers")
        g.large(a["paste"], menu=self._menu(a["paste"], a["paste_special"]), split=True)
        painter_btn = R(a["format_painter"], SMALL, text="Reproduire la mise en forme")
        painter_btn.installEventFilter(self)
        self._painter_btn = painter_btn
        g.column(a["cut"], a["copy"], painter_btn)
        home.addWidget(g)

        g = RibbonGroup("Police", self.show_text_format, "Format du texte (police, alignement…)")
        self.font_combo = QFontComboBox()
        self.font_combo.setFixedWidth(140)
        self.font_combo.currentFontChanged.connect(lambda f: self._text_style({"font": f.family()}))
        self.size_combo = QComboBox()
        self.size_combo.setEditable(True)
        self.size_combo.setFixedWidth(56)
        for s in FONT_SIZES:
            self.size_combo.addItem(str(s))
        self.size_combo.lineEdit().editingFinished.connect(self._size_combo_changed)
        self.size_combo.activated.connect(lambda _i: self._size_combo_changed())
        self.text_color = self._color_button("font_color", "Couleur de police", "#c00000",
                                             lambda c: self._text_style({"color": c}), allow_none=False,
                                             kind=ICON)
        case_menu = self._menu(("MAJUSCULES", None, lambda: self.change_case("upper")),
                               ("minuscules", None, lambda: self.change_case("lower")),
                               ("1re Lettre Des Mots En Majuscule", None, lambda: self.change_case("title")),
                               ("Phrase normale.", None, lambda: self.change_case("sentence")))
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 2, 0, 2)
        tl.setSpacing(2)
        tl.addWidget(self.font_combo)
        tl.addWidget(self.size_combo)
        tl.addWidget(R(a["font_grow"], ICON))
        tl.addWidget(R(a["font_shrink"], ICON))
        tl.addWidget(R(a["clear_format"], ICON))
        g.column(top, g.row(a["bold"], a["italic"], a["underline"], a["strike"],
                            R(None, ICON, icon_name="case", menu=case_menu, tooltip="<b>Modifier la casse</b>"),
                            None, self.text_color))
        home.addWidget(g)

        g = RibbonGroup("Paragraphe", self.show_text_format, "Paragraphe")
        spacing = QMenu(self)
        for v in (1.0, 1.15, 1.5, 2.0, 2.5, 3.0):
            act = spacing.addAction(f"{v:g}".replace(".", ","))
            act.setCheckable(True)
            act.setData(v)
            act.triggered.connect(lambda _=False, x=v: self._text_style({"spacing": x}))
        spacing.aboutToShow.connect(lambda m=spacing: self._check_spacing(m))
        g.column(g.row(a["valign_top"], a["valign_middle"], a["valign_bottom"], a["bullets"],
                       R(None, ICON, icon_name="line_spacing", menu=spacing,
                         tooltip="<b>Interligne</b><br>Espace entre les lignes du texte.")),
                 g.row(a["halign_left"], a["halign_center"], a["halign_right"], a["halign_justify"],
                       a["indent_less"], a["indent_more"]))
        home.addWidget(g)

        g = RibbonGroup("Outils")
        g.large(a["tool_select"])
        draw_menu = self._menu(a["tool_rectangle"], a["tool_ellipse"], a["tool_line"], a["tool_pen"],
                               a["tool_freeform"], a["tool_arc"])
        g.column(a["tool_connector"], a["tool_text"],
                 R(None, SMALL, text="Outils de dessin", icon_name="drawing_tools", menu=draw_menu))
        g.column(R(a["tool_port"], ICON), R(a["tool_textblock"], ICON))
        home.addWidget(g)

        g = RibbonGroup("Styles de forme", lambda: self.show_pane("format"), "Format de la forme")
        items = []
        for row, color, tip in quickstyles.gallery_items():
            style, text_color = quickstyles.quick_style(row, color)
            items.append((icons.style_swatch(style, text_color, 40), tip, (row, color)))
        self.style_gallery = RibbonGallery(items, QSize(44, 44), visible=6, popup_cols=7,
                                           section_titles={i * 7: quickstyles.ROWS[i] for i in range(5)})
        self.style_gallery.offset = 14
        self.style_gallery.activated.connect(self._apply_quick_style)
        g.add(self.style_gallery, Qt.AlignmentFlag.AlignVCenter)
        self.fill_btn = self._color_button("fill", "Remplissage", "#5b9bd5",
                                           lambda c: self._shape_style({"fill": c}, "Remplissage"),
                                           none_label="Aucun remplissage")
        self.line_btn = self._color_button("line_color", "Trait", "#41719c",
                                           lambda c: self._sc(lambda s: s.apply_line_to_selection({"line": c}))(),
                                           none_label="Aucun trait")
        line_menu = self.line_btn.menu()
        line_menu.addSeparator()
        line_menu.addMenu(self._weight_menu())
        line_menu.addMenu(self._dash_menu())
        line_menu.addMenu(self._arrow_menu())
        effects = self._menu(self._shadow_menu(), self._glow_menu(),
                             ("Dégradé", "background", lambda: self._shape_style({"gradient": True}, "Dégradé")),
                             ("Remplissage uni", "fill", lambda: self._shape_style({"gradient": False}, "Remplissage uni")))
        g.column(self.fill_btn, self.line_btn, R(None, SMALL, text="Effets", icon_name="effects", menu=effects))
        home.addWidget(g)

        g = RibbonGroup("Organiser")
        g.large(None, text="Aligner", icon_name="align",
                menu=self._menu(a["align_left"], a["align_center"], a["align_right"], None,
                                a["align_top"], a["align_middle"], a["align_bottom"]),
                tooltip="<b>Aligner</b><br>Aligne les formes sélectionnées.")
        g.large(None, text="Position", icon_name="position",
                menu=self._menu(a["auto_align_space"], a["auto_align"], a["auto_space"], None,
                                a["distribute_h"], a["distribute_v"], None, a["rotate_right"],
                                a["rotate_left"], a["flip_h"], a["flip_v"]),
                tooltip="<b>Position</b><br>Distribuer, faire pivoter, retourner.")
        g.column(R(a["front"], SMALL, menu=self._menu(a["front"], a["forward"]), split=True),
                 R(a["back"], SMALL, menu=self._menu(a["back"], a["backward"]), split=True),
                 R(None, SMALL, text="Grouper", icon_name="group", menu=self._menu(a["group"], a["ungroup"])))
        home.addWidget(g)

        g = RibbonGroup("Modification")
        self.change_shape_menu = QMenu(self)
        self.change_shape_menu.aboutToShow.connect(self._fill_change_shape)
        g.large(None, text="Modifier la forme", icon_name="change_shape", menu=self.change_shape_menu,
                tooltip="<b>Modifier la forme</b><br>Remplace la forme en gardant texte, style et connexions.")
        self.layer_menu = QMenu("Affecter au calque", self)
        self.layer_menu.aboutToShow.connect(self._fill_layer_menu)
        select_menu = self._menu(a["select_all"], None,
                                 ("Sélectionner les formes", "select", lambda: self._select_type("shapes")),
                                 ("Sélectionner les connecteurs", "connector", lambda: self._select_type("connectors")),
                                 ("Sélectionner les zones de texte", "textbox", lambda: self._select_type("text")),
                                 ("Sélectionner les images", "image", lambda: self._select_type("images")))
        g.column(R(None, SMALL, text="Calques", icon_name="layers", menu=self._menu(a["layers"], self.layer_menu)),
                 R(None, SMALL, text="Sélectionner", icon_name="select", menu=select_menu),
                 R(None, SMALL, text="Rechercher", icon_name="find", menu=self._menu(a["find"], a["replace"])))
        home.addWidget(g)

        # ======================================================= Insertion
        ins = self.ribbon.add_page("Insertion")
        g = RibbonGroup("Pages")
        g.large(a["page_add"], menu=self._menu(a["page_add"], a["page_background_new"], a["page_dup"],
                                               a["page_rename"], a["page_del"]),
                split=True)
        ins.addWidget(g)
        g = RibbonGroup("Illustrations")
        g.large(a["image"])
        ins.addWidget(g)
        g = RibbonGroup("Composants de diagramme")
        g.large(None, text="Conteneur", icon_name="container", menu=self._container_menu(),
                tooltip="<b>Conteneur</b><br>Regroupe visuellement des formes.")
        g.large(None, text="Légende", icon_name="callout", menu=self._callout_menu(),
                tooltip="<b>Légende</b><br>Bulles, notes et annotations.")
        g.large(None, text="Connecteur", icon_name="connector", menu=self._connector_tool_menu(),
                tooltip="<b>Connecteur</b><br>Choisissez le type puis faites glisser entre deux formes.")
        ins.addWidget(g)
        g = RibbonGroup("Liens")
        g.large(a["link"])
        ins.addWidget(g)
        g = RibbonGroup("Texte")
        g.large(a["textbox"])
        sym = QMenu(self)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(2)
        for i, ch in enumerate(SYMBOLS):
            b = QToolButton()
            b.setText(ch)
            b.setFixedSize(28, 28)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, c=ch: (sym.close(), self.insert_symbol(c)))
            grid.addWidget(b, i // 8, i % 8)
        wa = QWidgetAction(sym)
        wa.setDefaultWidget(holder)
        sym.addAction(wa)
        g.column(a["screentip"], R(None, SMALL, text="Symbole", icon_name="symbol", menu=sym), a["insert_field"])
        ins.addWidget(g)

        # ======================================================= Création
        des = self.ribbon.add_page("Création")
        g = RibbonGroup("Mise en page", self.page_setup_dialog, "Mise en page…")
        g.large(None, text="Orientation", icon_name="orientation", menu=self._menu(a["portrait"], a["landscape"]))
        size_menu = QMenu(self)
        for name, (w, h) in PAGE_SIZES.items():
            act = size_menu.addAction(icons.icon("page_size"), f"{name}\t{w:g} × {h:g} mm")
            act.triggered.connect(lambda _=False, n=name: self.set_page_format(n))
        size_menu.addSeparator()
        size_menu.addAction(a["fit_drawing"])
        size_menu.addAction(a["page_setup"])
        g.large(None, text="Taille", icon_name="page_size", menu=size_menu)
        g.large(a["auto_size"])
        des.addWidget(g)
        g = RibbonGroup("Thèmes")
        self.theme_gallery = RibbonGallery([(icons.theme_swatch(k, 40).pixmap(40, 40), f"Thème {t['name']}", k)
                                            for k, t in THEMES.items()], QSize(46, 46), visible=7, popup_cols=7)
        self.theme_gallery.activated.connect(self.apply_theme)
        g.add(self.theme_gallery, Qt.AlignmentFlag.AlignVCenter)
        des.addWidget(g)
        g = RibbonGroup("Variantes")
        self.variant_gallery = RibbonGallery([], QSize(46, 46), visible=4, popup_cols=4)
        self.variant_gallery.activated.connect(self.apply_variant)
        g.add(self.variant_gallery, Qt.AlignmentFlag.AlignVCenter)
        des.addWidget(g)
        g = RibbonGroup("Arrière-plans")
        bg_menu = QMenu(self)
        for color, name in BACKGROUNDS:
            pm = QPixmap(16, 16)
            pm.fill(QColor(color))
            act = bg_menu.addAction(name)
            act.setIcon(QIcon(pm))
            act.triggered.connect(lambda _=False, c=color: self.set_background(c))
        bg_menu.addSeparator()
        bg_menu.addAction("Autre couleur d'arrière-plan…", self._background_dialog)
        g.large(None, text="Arrière-plans", icon_name="background", menu=bg_menu)
        borders = QMenu(self)
        for key, name in BORDERS:
            borders.addAction(icons.icon("borders_titles"), name).triggered.connect(
                lambda _=False, k=key: self.add_border(k))
        g.large(None, text="Bordures et titres", icon_name="borders_titles", menu=borders)
        des.addWidget(g)
        g = RibbonGroup("Disposition")
        g.large(None, text="Redisposer la page", icon_name="relayout",
                menu=self._menu(a["relayout_tb"], a["relayout_lr"]))
        conn_menu = QMenu(self)
        for r in ROUTES:
            conn_menu.addAction(icons.icon("route"), ROUTE_LABELS[r]).triggered.connect(
                lambda _=False, v=r: self.set_route(v))
        conn_menu.addSeparator()
        conn_menu.addAction(a["line_jumps"])
        g.large(None, text="Connecteurs", icon_name="connectors", menu=conn_menu)
        des.addWidget(g)

        # ======================================================= Données
        data = self.ribbon.add_page("Données")
        g = RibbonGroup("Créer")
        g.large(None, text="Créer à partir de données", icon_name="data_visualizer",
                menu=self._menu(a["data_org"], a["data_flow"]),
                tooltip="<b>Créer à partir de données</b><br>Génère un organigramme ou un diagramme de flux "
                        "à partir d'un fichier CSV.")
        data.addWidget(g)
        g = RibbonGroup("Données liées")
        g.large(a["data_link"])
        g.large(a["data_refresh"])
        g.large(a["data_unlink"])
        data.addWidget(g)
        g = RibbonGroup("Graphiques de données")
        g.large(a["data_graphic"], menu=self._menu(a["data_graphic_clear"]))
        data.addWidget(g)
        g = RibbonGroup("Afficher/Masquer")
        g.column(self._check(a["pane_data"], "Fenêtre Données de forme"))
        data.addWidget(g)
        g = RibbonGroup("Rapports")
        g.large(a["shape_report"])
        data.addWidget(g)

        # ======================================================= Processus
        proc = self.ribbon.add_page("Processus")
        g = RibbonGroup("Sous-processus")
        g.large(a["subprocess"])
        proc.addWidget(g)
        g = RibbonGroup("Validation du diagramme")
        g.large(a["check_diagram"])
        g.column(self._check(a["pane_issues"], "Fenêtre Problèmes"))
        proc.addWidget(g)

        # ======================================================= Révision
        rev = self.ribbon.add_page("Révision")
        g = RibbonGroup("Vérification")
        g.large(a["spelling"])
        rev.addWidget(g)
        g = RibbonGroup("Commentaires")
        g.large(a["new_comment"])
        g.column(R(a["delete_comment"], SMALL, text="Supprimer"), a["prev_comment"], a["next_comment"])
        g.large(a["pane_comments"])
        rev.addWidget(g)
        g = RibbonGroup("Protection")
        g.large(a["lock"], menu=self._menu(a["lock"], a["unlock"]), split=True)
        g.large(a["protect"])
        rev.addWidget(g)

        # ======================================================= Interfonctionnel (contextuel)
        cff = self.ribbon.add_page(CFF_TAB)
        g = RibbonGroup("Insérer")
        g.large(a["cff_lane"], menu=self._menu(a["cff_lane_after"], a["cff_lane_before"]), split=True)
        g.large(a["cff_phase"])
        cff.addWidget(g)
        g = RibbonGroup("Diagramme")
        g.large(None, text="Nouveau diagramme interfonctionnel", icon_name="swimlane",
                menu=self._menu(a["cff_new_h"], a["cff_new_v"]),
                tooltip="<b>Nouveau diagramme interfonctionnel</b><br>Ajoute un cadre avec titre et "
                        "trois couloirs sur la page.")
        g.large(a["cff_layout"])
        cff.addWidget(g)
        g = RibbonGroup("Organiser")
        g.large(None, text="Orientation du diagramme", icon_name="swimlane",
                menu=self._menu(a["cff_dir_h"], a["cff_dir_v"]),
                tooltip="<b>Orientation du diagramme</b><br>Passe des couloirs horizontaux aux couloirs "
                        "verticaux (ou l'inverse) en conservant les formes et leurs connexions.")
        g.large(a["cff_rotate"])
        cff.addWidget(g)
        g = RibbonGroup("Conception")
        self.cff_gallery = RibbonGallery([(icons.cff_style_swatch(st, 40).pixmap(40, 40), st["name"], i)
                                          for i, st in enumerate(swimlanes.STYLES)],
                                         QSize(46, 46), visible=4, popup_cols=4)
        self.cff_gallery.activated.connect(
            lambda i: self.scene() and self.scene().cff_apply_style(swimlanes.STYLES[i]))
        g.add(self.cff_gallery, Qt.AlignmentFlag.AlignVCenter)
        cff.addWidget(g)
        g = RibbonGroup("Afficher/Masquer")
        self._cff_checks = {"cff_title": self._check(a["cff_title"]),
                            "cff_separators": self._check(a["cff_separators"])}
        g.column(*self._cff_checks.values())
        cff.addWidget(g)
        g = RibbonGroup("Formes")
        g.column(R(None, SMALL, text="Gabarit interfonctionnel", icon_name="shapes_panel",
                   menu=self._menu(("Ouvrir le gabarit", "shapes_panel",
                                    lambda: self.shapes_panel.open_category(stencils.CFF)))))
        cff.addWidget(g)

        # ======================================================= Conteneur (contextuel)
        ctab = self.ribbon.add_page(CONTAINER_TAB)
        g = RibbonGroup("Taille")
        g.large(a["container_fit"])
        ctab.addWidget(g)
        g = RibbonGroup("Styles du conteneur")
        self.container_gallery = RibbonGallery(
            [(icons.stencil_pixmap(stencils.get(t), 40), name, t) for t, name in stencils.CONTAINER_STYLES],
            QSize(46, 46), visible=4, popup_cols=4)
        self.container_gallery.activated.connect(self._container_style)
        g.add(self.container_gallery, Qt.AlignmentFlag.AlignVCenter)
        ctab.addWidget(g)
        g = RibbonGroup("Appartenance")
        g.large(a["container_select"])
        g.large(a["container_disband"])
        ctab.addWidget(g)

        # ======================================================= Affichage
        view = self.ribbon.add_page("Affichage")
        g = RibbonGroup("Affichages")
        g.large(a["presentation"])
        view.addWidget(g)
        g = RibbonGroup("Explorateur")
        g.large(a["pane_drawing"])
        view.addWidget(g)
        g = RibbonGroup("Afficher", self.ruler_grid_dialog, "Règle et grille…")
        g.column(self._check(a["rulers"]), self._check(a["page_breaks"]), self._check(a["grid"]))
        g.column(self._check(a["ruler_guides"]))
        view.addWidget(g)
        g = RibbonGroup("Aide visuelle", self.snap_glue_dialog, "Accrocher et coller…")
        g.column(self._check(a["guides"]), self._check(a["autoconnect"]), self._check(a["ports"]))
        g.column(self._check(a["snap"]), self._check(a["line_jumps"], "Sauts de ligne"))
        view.addWidget(g)
        g = RibbonGroup("Zoom")
        g.large(a["zoom"])
        g.large(a["fit_page"])
        g.column(a["zoom_100"], a["fit_width"])
        view.addWidget(g)
        g = RibbonGroup("Fenêtre")
        g.large(a["new_window"])
        self.switch_menu = QMenu(self)
        self.switch_menu.aboutToShow.connect(self._fill_switch_menu)
        g.column(a["arrange_all"], a["cascade"],
                 R(None, SMALL, text="Changer de fenêtre", icon_name="new_window", menu=self.switch_menu))
        panes_menu = self._menu(a["show_shapes"], *[a[f"pane_{k}"] for k, _t, _i in PANES])
        g.large(None, text="Volets des tâches", icon_name="task_panes", menu=panes_menu)
        view.addWidget(g)

        # ======================================================= Développeur
        dev = self.ribbon.add_page("Développeur")
        g = RibbonGroup("Afficher")
        g.large(a["shapesheet"])
        dev.addWidget(g)
        g = RibbonGroup("Conception de formes")
        g.large(None, text="Opérations", icon_name="shape_ops",
                menu=self._menu(*[a[f"op_{op}"] for op in shapeops.OPERATIONS]),
                tooltip="<b>Opérations</b><br>Union, Combiner, Fragmenter, Intersecter ou Soustraire les "
                        "formes sélectionnées (la première sélectionnée sert de référence).")
        g.column(a["tool_freeform"], a["tool_arc"], a["tool_pen"])
        dev.addWidget(g)
        g = RibbonGroup("Interopérabilité")
        g.large(a["import_vsdx"])
        g.large(a["export_vsdx"])
        dev.addWidget(g)
        g = RibbonGroup("Document")
        g.large(a["properties"])
        dev.addWidget(g)

        # ======================================================= Aide
        hlp = self.ribbon.add_page("Aide")
        g = RibbonGroup("Aide")
        g.large(a["shortcuts"])
        g.large(a["security"])
        g.large(a["about"])
        hlp.addWidget(g)
        self.ribbon.finish_pages()

    def _check(self, action: QAction, text: str | None = None) -> QCheckBox:
        cb = QCheckBox(text or action.text())
        cb.setChecked(action.isChecked())
        cb.toggled.connect(action.setChecked)
        action.toggled.connect(lambda on, c=cb: c.isChecked() != on and c.setChecked(on))
        cb.setToolTip(action.toolTip())
        return cb

    def _weight_menu(self) -> QMenu:
        m = QMenu("Épaisseur", self)
        m.setIcon(icons.icon("line_weight"))
        for w in LINE_WEIGHTS:
            pm = QPixmap(60, 12)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setPen(QPen(QColor(T["text"]), max(0.5, w * 96 / 72)))
            p.drawLine(2, 6, 58, 6)
            p.end()
            act = m.addAction(f"{w:g} pt")
            act.setIcon(QIcon(pm))
            act.setCheckable(True)
            act.setData(w)
            act.triggered.connect(lambda _=False, v=w: self.set_line_weight(v))
        m.addSeparator()
        m.addAction("Autres épaisseurs…", self.custom_line_weight)
        m.aboutToShow.connect(lambda menu=m: self._check_current_weight(menu))
        return m

    def _current_line_weight(self) -> float | None:
        """Épaisseur (pt) de l'objet sélectionné, connecteur compris."""
        sc = self.scene()
        sel = sc.selected_all() if sc is not None else []
        return sel[0].style["line_width"] * 72 / 96 if sel else None

    def _check_current_weight(self, menu: QMenu) -> None:
        cur = self._current_line_weight()
        for act in menu.actions():
            if act.isCheckable():
                act.setChecked(cur is not None and abs(act.data() - cur) < 0.01)

    def set_line_weight(self, points: float) -> None:
        """Épaisseur du trait des formes et des connecteurs sélectionnés, en points."""
        sc = self.scene()
        if sc is None:
            return
        if not sc.selected_all():
            self.statusBar().showMessage("Sélectionnez une forme ou un connecteur.", 4000)
            return
        sc.apply_line_to_selection({"line_width": points * 96 / 72}, "Épaisseur du trait")

    def custom_line_weight(self) -> None:
        cur = self._current_line_weight()
        value, ok = QInputDialog.getDouble(self, "Épaisseur du trait", "Épaisseur (pt) :",
                                           cur if cur is not None else 0.75, 0.25, 36.0, 2)
        if ok:
            self.set_line_weight(value)

    def _dash_menu(self) -> QMenu:
        m = QMenu("Tirets", self)
        m.setIcon(icons.icon("line_dash"))
        for d in DASHES:
            m.addAction(DASH_LABELS[d]).triggered.connect(lambda _=False, v=d: self._sc(
                lambda s: s.apply_line_to_selection({"dash": v}, "Type de tiret"))())
        return m

    def _arrow_menu(self) -> QMenu:
        m = QMenu("Flèches", self)
        m.setIcon(icons.icon("arrows"))
        for a in ARROWS:
            m.addAction(f"Fin : {ARROW_LABELS[a]}").triggered.connect(lambda _=False, v=a: self._sc(
                lambda s: s.apply_connector_style({"arrow_end": v}, text="Fin de flèche"))())
        m.addSeparator()
        for a in ARROWS:
            m.addAction(f"Début : {ARROW_LABELS[a]}").triggered.connect(lambda _=False, v=a: self._sc(
                lambda s: s.apply_connector_style({"arrow_start": v}, text="Début de flèche"))())
        return m

    def _shadow_menu(self) -> QMenu:
        m = QMenu("Ombre", self)
        m.setIcon(icons.icon("shadow"))
        m.addAction("Aucune ombre").triggered.connect(lambda: self._shape_style({"shadow": False}, "Ombre"))
        m.addAction(icons.icon("shadow"), "Ombre portée").triggered.connect(
            lambda: self._shape_style({"shadow": True}, "Ombre"))
        return m

    def _glow_menu(self) -> QMenu:
        m = QMenu("Lumière", self)
        m.setIcon(icons.icon("glow"))
        m.addAction("Aucune lumière").triggered.connect(lambda: self._shape_style({"glow": ""}, "Lumière"))
        for color in quickstyles.ACCENTS[:6]:
            pm = QPixmap(16, 16)
            pm.fill(QColor(color))
            act = m.addAction(f"Lumière {color}")
            act.setIcon(QIcon(pm))
            act.triggered.connect(lambda _=False, c=color: self._shape_style({"glow": c}, "Lumière"))
        return m

    def _container_menu(self) -> QMenu:
        m = QMenu(self)
        for name, style, ts in (("Classique", {"fill": "#f2f6fc", "line": "#8eaadb"}, {"color": "#1f3864"}),
                                ("Contour", {"fill": "", "line": "#5b9bd5"}, {"color": "#2e75b6"}),
                                ("Ardoise", {"fill": "#eef0f3", "line": "#44546a"}, {"color": "#222a35"}),
                                ("Ambre", {"fill": "#fdf1e7", "line": "#ed7d31"}, {"color": "#843c0c"})):
            m.addAction(icons.icon("container"), name).triggered.connect(
                lambda _=False, s=style, t=ts: self._insert("basic.container", s, t))
        return m

    def _callout_menu(self) -> QMenu:
        m = QMenu(self)
        for text, type_id in (("Bulle", "basic.callout"), ("Note", "basic.note"),
                              ("Annotation", "flow.annotation"), ("Note UML", "uml.note")):
            m.addAction(icons.icon("callout"), text).triggered.connect(lambda _=False, t=type_id: self._insert(t))
        return m

    def _connector_tool_menu(self) -> QMenu:
        m = QMenu(self)
        for r in ROUTES:
            m.addAction(icons.icon("connector"), ROUTE_LABELS[r]).triggered.connect(
                lambda _=False, v=r: (self._set_default_route(v), self.doc.set_tool("connector")))
        return m

    # ------------------------------------------------------------------ barre d'état
    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.page_label = QLabel()
        self.sel_label = QLabel()
        self.lang_label = QLabel("Français (France)")
        sb.addWidget(self.page_label)
        sb.addWidget(self.sel_label, 1)
        self.secure_label = QLabel()
        sb.addPermanentWidget(self.secure_label)
        sb.addPermanentWidget(self.lang_label)
        pres = QToolButton()
        pres.setDefaultAction(self.a["presentation"])
        pres.setIconSize(QSize(16, 16))
        sb.addPermanentWidget(pres)
        zo = QToolButton()
        zo.setText("−")
        zo.setToolTip("Zoom arrière")
        zo.clicked.connect(self.a["zoom_out"].trigger)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, 1000)
        self.zoom_slider.setFixedWidth(110)
        self.zoom_slider.valueChanged.connect(self._slider_changed)
        zi = QToolButton()
        zi.setText("+")
        zi.setToolTip("Zoom avant")
        zi.clicked.connect(self.a["zoom_in"].trigger)
        self.zoom_label = QToolButton()
        self.zoom_label.setText("100 %")
        self.zoom_label.setToolTip("Zoom…")
        self.zoom_label.clicked.connect(self.zoom_dialog)
        fit = QToolButton()
        fit.setDefaultAction(self.a["fit_page"])
        fit.setIconSize(QSize(16, 16))
        for w in (zo, self.zoom_slider, zi, self.zoom_label, fit):
            sb.addPermanentWidget(w)

    # ------------------------------------------------------------------ recherche de commandes
    def _build_search_entries(self) -> None:
        entries = []
        seen = set()
        for act in self.a.values():
            text = (act.property("search_text") or act.text()).replace("&", "").rstrip("…")
            if text and text not in seen:
                seen.add(text)
                entries.append((text, act.icon(), act))
        for d in stencils.SHAPES.values():
            if d.category:
                label = f"Insérer la forme : {d.name}"
                entries.append((label, None, lambda t=d.type_id: self._add_at_center(t)))
        for k, t in THEMES.items():
            entries.append((f"Thème {t['name']}", None, lambda key=k: self.apply_theme(key)))
        self.search_box.set_entries(entries)

    def _focus_search(self) -> None:
        self.search_box.setFocus()
        self.search_box.selectAll()

    # ================================================================== document
    def scene(self):
        return self.view.scene()

    def user_name(self) -> str:
        # Protection des données dès la conception (RGPD, art. 25) : le nom de connexion du système
        # n'est jamais inscrit dans les documents ; seul le nom choisi dans Fichier > Options l'est.
        name = self.settings.value("user/name", "")
        return security.clean_line(str(name), 100) or "Utilisateur"

    def _detach_document(self) -> None:
        old = self.doc
        if old is None:
            return
        for sig in (old.pagesChanged, old.pageShown, old.settingsChanged, old.toolChanged,
                    old.formatPainterDone, old.undo_stack.cleanChanged, old.undo_stack.indexChanged):
            try:
                sig.disconnect()
            except TypeError:
                pass
        for p in old.pages:
            for sig, slot in ((p.selectionInfo, self._on_selection), (p.autoconnectHover, self._quick_shapes)):
                try:
                    sig.disconnect(slot)
                except TypeError:
                    pass
        self.ctx.remove_autosave(old)

    def set_document(self, doc: Document) -> None:
        self._detach_document()
        self.doc = doc
        self._connected_scenes.clear()
        doc.pagesChanged.connect(self._pages_changed)
        doc.pageShown.connect(self.show_page)
        doc.toolChanged.connect(self._tool_changed)
        doc.formatPainterDone.connect(lambda: self.a["format_painter"].setChecked(False))
        doc.undo_stack.cleanChanged.connect(lambda _c: self._update_title())
        doc.undo_stack.indexChanged.connect(lambda _i: self._after_change())
        self._load_view_settings()
        self._pages_changed()
        self.show_page(doc.pages[0])
        self._update_title()
        self._after_change()
        self._tool_changed(doc.tool)
        self._refresh_variants()

    def is_pristine(self) -> bool:
        d = self.doc
        return d.path is None and not d.is_modified() and len(d.pages) == 1 and not d.pages[0].all_items()

    def _load_view_settings(self) -> None:
        s = self.doc.settings
        for key in ("grid", "guides", "snap", "ports", "autoconnect"):
            stored = self.settings.value(f"view/{key}", s.get(key, True), type=bool)
            s[key] = stored
            self.a[key].setChecked(stored)
        rulers = self.settings.value("view/rulers", True, type=bool)
        self.a["rulers"].setChecked(rulers)
        self.canvas.set_rulers_visible(rulers)
        guides = self.settings.value("view/ruler_guides", True, type=bool)
        self.a["ruler_guides"].setChecked(guides)
        from .scene import DiagramScene
        DiagramScene.show_ruler_guides = guides
        self.a["line_jumps"].setChecked(s.get("line_jumps", True))
        self.a["page_breaks"].setChecked(bool(s.get("page_breaks")))

    def _pages_changed(self) -> None:
        doc = self.doc
        for p in doc.pages:
            if id(p) not in self._connected_scenes:
                p.selectionInfo.connect(self._on_selection)
                p.autoconnectHover.connect(self._quick_shapes)
                self._connected_scenes.add(id(p))
        self.page_tabs.blockSignals(True)
        names = [p.page_name for p in doc.pages]
        if [self.page_tabs.tabText(i) for i in range(self.page_tabs.count())] != names:
            # Reconstruits seulement s'ils diffèrent : un onglet en cours de glissement reste en place.
            while self.page_tabs.count():
                self.page_tabs.removeTab(0)
            for p in doc.pages:
                self.page_tabs.addTab(p.page_name)
        for i, p in enumerate(doc.pages):
            self.page_tabs.setTabIcon(i, icons.icon("background_page") if p.is_background else QIcon())
            self.page_tabs.setTabToolTip(i, "Page d'arrière-plan" if p.is_background else "")
        cur = self.scene()
        if cur in doc.pages:
            self.page_tabs.setCurrentIndex(doc.pages.index(cur))
        self.page_tabs.blockSignals(False)
        if cur is not None and cur not in doc.pages:
            self.show_page(doc.pages[min(self.page_tabs.currentIndex(), len(doc.pages) - 1)])
        self.a["page_del"].setEnabled(len(doc.pages) > 1)
        self._update_status()

    def show_page(self, scene) -> None:
        if scene not in self.doc.pages:
            return
        self.view.show_scene(scene)
        self.drawing_pane.refresh()
        idx = self.doc.pages.index(scene)
        if self.page_tabs.currentIndex() != idx:
            self.page_tabs.blockSignals(True)
            self.page_tabs.setCurrentIndex(idx)
            self.page_tabs.blockSignals(False)
        self.a["auto_size"].blockSignals(True)
        self.a["auto_size"].setChecked(scene.auto_size)
        self.a["auto_size"].blockSignals(False)
        self._on_selection()

    def _shape_op(self, op: str) -> None:
        sc = self.scene()
        if sc is not None and not sc.shape_operation(op):
            self.statusBar().showMessage(f"« {shapeops.OPERATIONS[op]} » : sélectionnez au moins deux formes "
                                         "qui se chevauchent.", 6000)

    def _update_cff_tab(self) -> None:
        """L'onglet interfonctionnel apparaît dès qu'on utilise des couloirs, comme dans Visio."""
        if not hasattr(self, "ribbon") or self.doc is None:
            return
        sc = self.scene()
        visible = (sc is not None and sc.has_cff()) or stencils.CFF in self.shapes_panel.open_cats
        self.ribbon.set_tab_visible(CFF_TAB, visible)
        o = sc.cff_orientation() if sc is not None else None
        _f, lanes, phases = sc.cff_parts(o) if o else ([], [], [])
        states = {"cff_dir_h": (o == "h", bool(lanes)), "cff_dir_v": (o == "v", bool(lanes)),
                  "cff_title": (sc.cff_option("title") if o else True, bool(_f)),
                  "cff_separators": (not sc.cff_option("hidden") if o else True, bool(phases)),
                  "cff_rotate": (sc.cff_option("rotate") if o else False, bool(lanes))}
        for key, (checked, enabled) in states.items():
            act = self.a[key]
            act.blockSignals(True)
            act.setChecked(checked)
            act.blockSignals(False)
            act.setEnabled(enabled)
            cb = getattr(self, "_cff_checks", {}).get(key)
            if cb is not None:  # la case suit l'action sans relancer la commande
                cb.blockSignals(True)
                cb.setChecked(checked)
                cb.setEnabled(enabled)
                cb.blockSignals(False)

    def _cff_option(self, key: str, value: bool) -> None:
        sc = self.scene()
        if sc is not None:
            sc.cff_set_option(key, value)

    def _cff_orientation(self, orientation: str) -> None:
        sc = self.scene()
        if sc is None:
            return
        if sc.cff_orientation() == orientation:
            pass
        elif sc.cff_set_orientation(orientation):
            if (orientation == "h") != (sc.page_w > sc.page_h):
                self.set_orientation(orientation == "h")  # paysage pour l'horizontal, portrait sinon
            self.view.fit_page()
        else:
            self.statusBar().showMessage("Impossible de changer l'orientation : la page contient déjà "
                                         "un diagramme dans l'autre orientation.", 6000)
        self._update_cff_tab()

    def _new_cff(self, orientation: str) -> None:
        sc = self.scene()
        if sc is None:
            return
        if sc.cff_parts(orientation)[1]:
            self.statusBar().showMessage("Cette page contient déjà un diagramme interfonctionnel : "
                                         "utilisez « Couloir » pour en ajouter.", 6000)
            return
        if orientation == "h" and sc.page_h > sc.page_w:
            self.set_orientation(True)
        sc.cff_drop("cff.frame_" + orientation, sc.page_rect().center())
        self.shapes_panel.open_category(stencils.CFF)
        self.view.fit_page()

    def _page_tab_changed(self, index: int) -> None:
        if 0 <= index < len(self.doc.pages):
            self.show_page(self.doc.pages[index])

    def _step_page(self, step: int) -> None:
        idx = (self.page_tabs.currentIndex() + step) % len(self.doc.pages)
        self.show_page(self.doc.pages[idx])

    def _all_pages_menu(self) -> None:
        m = QMenu(self)
        for i, p in enumerate(self.doc.pages):
            act = m.addAction(p.page_name)
            act.setCheckable(True)
            act.setChecked(p is self.scene())
            act.triggered.connect(lambda _=False, sc=p: self.show_page(sc))
        m.exec(self.all_pages.mapToGlobal(QPoint(0, -m.sizeHint().height())))

    def _after_change(self) -> None:
        st = self.doc.undo_stack
        self.a["undo"].setEnabled(st.canUndo())
        self.a["redo"].setEnabled(st.canRedo())
        self.a["undo"].setToolTip(f"<b>Annuler {st.undoText()} (Ctrl+Z)</b>")
        self.a["redo"].setToolTip(f"<b>Rétablir {st.redoText()} (Ctrl+Y)</b>")
        self._update_title()
        self._on_selection()
        for i, p in enumerate(self.doc.pages):
            if i < self.page_tabs.count() and self.page_tabs.tabText(i) != p.page_name:
                self.page_tabs.setTabText(i, p.page_name)
            if i < self.page_tabs.count():
                self.page_tabs.setTabIcon(i, icons.icon("background_page") if p.is_background else QIcon())
        self._update_page_type_actions()
        for p in self.doc.pages:
            p.refresh_fields()
        sc = self.scene()
        if sc is not None:
            self.a["auto_size"].blockSignals(True)
            self.a["auto_size"].setChecked(sc.auto_size)
            self.a["auto_size"].blockSignals(False)
        self._update_cff_tab()

    def _fill_undo_menu(self) -> None:
        self.undo_menu.clear()
        st = self.doc.undo_stack
        for i in range(st.index() - 1, max(-1, st.index() - 16), -1):
            act = self.undo_menu.addAction(st.text(i))
            act.triggered.connect(lambda _=False, k=i: st.setIndex(k))
        if not self.undo_menu.actions():
            self.undo_menu.addAction("Rien à annuler").setEnabled(False)

    def _tool_changed(self, tool: str) -> None:
        act = self.a.get(f"tool_{tool}")
        if act is not None:
            act.setChecked(True)

    def doc_title(self) -> str:
        if self.doc.path:
            return os.path.basename(self.doc.path)
        if self.title_hint:
            return self.title_hint
        return self.ctx.untitled_name(self)

    def _update_title(self) -> None:
        name = self.doc_title()
        mark = " •" if self.doc.is_modified() else ""
        self.setWindowTitle(f"{name}{mark} - {APP_NAME}")
        if self.titlebar is not None:
            self.titlebar.set_title(f"{name}{mark}  -  {APP_NAME}")
        self.secure_label.setText("Chiffré" if self.doc.password else "")

    # ================================================================== sélection
    def _on_selection(self) -> None:
        sc = self.scene()
        if sc is None:
            return
        sel = sc.selected_all()
        shapes = sc.selected_shapes()
        has = bool(sel)
        self.ribbon.set_tab_visible(CONTAINER_TAB, sc.is_plain_container(sc.single_selected))
        for key in ("cut", "copy", "delete", "duplicate", "front", "back", "forward", "backward",
                    "edit_text"):
            self.a[key].setEnabled(has)
        for key in ("rotate_right", "rotate_left", "flip_h", "flip_v", "lock", "unlock"):
            self.a[key].setEnabled(bool(shapes))
        for key in ("align_left", "align_center", "align_right", "align_top", "align_middle",
                    "align_bottom", "group"):
            self.a[key].setEnabled(len(shapes) >= 2)
        self.a["distribute_h"].setEnabled(len(shapes) >= 3)
        self.a["distribute_v"].setEnabled(len(shapes) >= 3)
        self.a["ungroup"].setEnabled(any(s.group for s in shapes))
        single = sc.single_selected
        for key in ("shapesheet", "link", "screentip", "new_comment"):
            self.a[key].setEnabled(isinstance(single, ShapeItem))
        self.a["subprocess"].setEnabled(bool(shapes))
        for op in shapeops.OPERATIONS:
            self.a[f"op_{op}"].setEnabled(len(shapes) >= 2)
        self.a["data_unlink"].setEnabled(any(s.data_links for s in shapes))
        editable_shapes = [s for s in shapes if not s.locked]
        common_fields = set.intersection(*(set(s.data) for s in editable_shapes)) if editable_shapes else set()
        self.a["data_graphic"].setEnabled(bool(common_fields))
        self.a["data_graphic_clear"].setEnabled(any(s.data_graphic for s in editable_shapes))
        self.a["open_link"].setEnabled(isinstance(single, ShapeItem) and bool(single.link))
        self.a["delete_comment"].setEnabled(isinstance(single, ShapeItem) and bool(single.comments))
        self._updating_ui = True
        try:
            ref = sel[0] if sel else None
            if ref is not None or self.doc is not None:
                # Sans sélection, Visio affiche la police par défaut du document (pas celle de l'interface).
                ts = ref.text_style if ref is not None else fileformat.default_shape_styles(
                    "basic.rect", self.doc.settings["theme"])[1]
                self.font_combo.blockSignals(True)
                self.font_combo.setCurrentFont(QFont(ts["font"]))
                self.font_combo.blockSignals(False)
                self.size_combo.setEditText(f"{ts['size']:g}")
                for k in ("bold", "italic", "underline", "strike", "bullets"):
                    self.a[k].blockSignals(True)
                    self.a[k].setChecked(bool(ts.get(k)))
                    self.a[k].blockSignals(False)
            self.theme_gallery.set_current(self.doc.settings["theme"])
            self.variant_gallery.set_current(self.doc.settings.get("variant", "standard"))
        finally:
            self._updating_ui = False
        for pane in (self.format_pane, self.size_pane, self.data_pane, self.comments_pane):
            if pane.isVisible():
                pane.refresh()
        if self.task_panes.is_visible("drawing"):
            self.drawing_pane.sync_selection()
        self._update_status()

    def _update_status(self) -> None:
        sc = self.scene()
        if sc is None or sc not in self.doc.pages:
            return
        fg = [p for p in self.doc.pages if not p.is_background]
        if sc.is_background:
            self.page_label.setText(f"Arrière-plan « {sc.page_name} »")
        else:
            self.page_label.setText(f"Page {fg.index(sc) + 1} sur {len(fg)}")
        single = sc.single_selected
        if isinstance(single, ShapeItem):
            self.sel_label.setText(f"Largeur : {single.w / PX_PER_MM:.0f} mm    Hauteur : "
                                   f"{single.h / PX_PER_MM:.0f} mm    Angle : {single.rotation():.0f}°")
        else:
            n = len(sc.selected_all())
            self.sel_label.setText(f"{n} objets sélectionnés" if n > 1 else "")

    def _zoom_changed(self, z: float) -> None:
        self.zoom_label.setText(f"{z * 100:.0f} %")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(round(1000 * math.log(z / 0.1) / math.log(80)))
        self.zoom_slider.blockSignals(False)

    def _slider_changed(self, v: int) -> None:
        self.view.set_zoom(0.1 * 80 ** (v / 1000))

    def _pane_visibility(self, key: str, on: bool) -> None:
        act = self.a[f"pane_{key}"]
        act.blockSignals(True)
        act.setChecked(on)
        act.blockSignals(False)
        self.settings.setValue(f"panes/{key}", on)
        pane = {"format": self.format_pane, "size": self.size_pane, "data": self.data_pane,
                "comments": self.comments_pane, "panzoom": self.panzoom_pane,
                "drawing": self.drawing_pane}.get(key)
        if on and pane is not None:
            pane.refresh()

    def show_pane(self, key: str) -> None:
        self.a[f"pane_{key}"].setChecked(True)
        self.task_panes.set_visible(key, True)

    def show_text_format(self) -> None:
        self.show_pane("format")
        self.format_pane.tab_buttons[2].click()

    # ================================================================== édition
    def cut(self) -> None:
        self.copy()
        self.scene().delete_items(self.scene().selected_all(), "Couper")

    def copy(self) -> None:
        sc = self.scene()
        data = sc.copy_selection() if sc else None
        if not data:
            return
        md = QMimeData()
        md.setData(CLIP_MIME, data)
        md.setText("\n".join(i.text for i in sc.selected_all() if i.text))
        # Image et SVG : la sélection se colle aussi dans LibreOffice, GIMP ou un courriel.
        picture = export.selection_clipboard(sc)
        if picture is not None:
            md.setImageData(picture[0])
            md.setData("image/svg+xml", picture[1])
        QApplication.clipboard().setMimeData(md)
        self._paste_count = 0

    def paste(self) -> None:
        sc = self.scene()
        md = QApplication.clipboard().mimeData()
        if sc is None or md is None:
            return
        if md.hasFormat(CLIP_MIME):
            self._paste_count += 1
            off = mm_to_px(5) * self._paste_count
            try:
                sc.paste(bytes(md.data(CLIP_MIME)), QPointF(off, off))
            except fileformat.DocumentError as exc:
                self._plain_message(QMessageBox.Icon.Warning, APP_NAME, str(exc))
            return
        if md.hasImage():
            img = md.imageData()
            if img is not None and not img.isNull():
                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                img.save(buf, "PNG")
                self._insert_image_bytes(bytes(buf.data()), self._view_center())
                return
        if md.hasText() and md.text().strip():
            text = security.clean_text(md.text(), fileformat.MAX_TEXT)
            st = sc.new_shape_state("basic.text", self._view_center())
            st["text"] = text
            st["h"] = max(st["h"], mm_to_px(6) * (text.count("\n") + 1))
            sc.add_states([st], "Coller du texte")

    def paste_special(self) -> None:
        """Accueil > Coller > Collage spécial : choix du format parmi ceux du presse-papiers."""
        md = QApplication.clipboard().mimeData()
        sc = self.scene()
        if md is None or sc is None:
            return
        choices = []
        if md.hasFormat(CLIP_MIME):
            choices.append(("shapes", f"Formes {APP_NAME}"))
        if md.hasImage():
            choices.append(("image", "Image (PNG)"))
        if md.hasText() and md.text().strip():
            choices.append(("text", "Texte non mis en forme"))
        if not choices:
            self.statusBar().showMessage("Le presse-papiers ne contient rien à coller.", 4000)
            return
        label, ok = QInputDialog.getItem(self, "Collage spécial", "Coller en tant que :",
                                         [c[1] for c in choices], 0, False)
        if not ok:
            return
        kind = next(k for k, t in choices if t == label)
        if kind == "shapes":
            self.paste()
        elif kind == "image":
            img = md.imageData()
            if img is not None and not img.isNull():
                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                img.save(buf, "PNG")
                self._insert_image_bytes(bytes(buf.data()), self._view_center())
        else:
            text = security.clean_text(md.text(), fileformat.MAX_TEXT)
            st = sc.new_shape_state("basic.text", self._view_center())
            st["text"] = text
            st["h"] = max(st["h"], mm_to_px(6) * (text.count("\n") + 1))
            sc.add_states([st], "Coller du texte")

    def duplicate(self) -> None:
        sc = self.scene()
        data = sc.copy_selection() if sc else None
        if data:
            sc.paste(data, QPointF(mm_to_px(5), mm_to_px(5)), "Dupliquer")

    def delete(self) -> None:
        sc = self.scene()
        if sc is None:
            return
        if sc.selected_guide is not None and not sc.selected_all():
            sc.remove_guide(sc.selected_guide)
            return
        if self.doc.tool == "port" and sc.remove_selected_port():
            return
        locked = [s for s in sc.selected_shapes() if s.locked]
        sc.delete_selection()
        if locked:
            self.statusBar().showMessage(f"{len(locked)} forme(s) verrouillée(s) non supprimée(s).", 5000)

    def edit_text(self) -> None:
        sc = self.scene()
        if sc is not None and sc.single_selected is not None:
            sc.single_selected.start_edit()

    def format_painter_sticky(self) -> None:
        sc = self.scene()
        if sc is None or sc.single_selected is None:
            self.statusBar().showMessage("Sélectionnez d'abord la forme dont copier la mise en forme.", 5000)
            return
        act = self.a["format_painter"]
        if not act.isChecked():
            act.setChecked(True)
        if sc.format_painter is None:
            self.format_painter(True)
        if sc.format_painter is not None:
            sc.format_painter["sticky"] = True
            self.statusBar().showMessage("Cliquez sur les formes à mettre en forme ; Échap pour terminer.")

    def format_painter(self, on: bool) -> None:
        sc = self.scene()
        if not on:
            if sc is not None:
                sc.format_painter = None
            return
        item = sc.single_selected if sc is not None else None
        if item is None:
            self.a["format_painter"].setChecked(False)
            self.statusBar().showMessage("Sélectionnez d'abord la forme dont copier la mise en forme.", 5000)
            return
        sc.format_painter = {"kind": item.kind, "style": dict(item.style), "text_style": dict(item.text_style)}
        self.statusBar().showMessage("Cliquez sur la forme à mettre en forme (Échap pour annuler).")

    def _text_style(self, changes: dict) -> None:
        if not self._updating_ui:
            self._sc(lambda s: s.apply_text_style(changes))()

    def _shape_style(self, changes: dict, text: str) -> None:
        self._sc(lambda s: s.apply_shape_style(changes, text))()

    def _size_combo_changed(self) -> None:
        try:
            v = float(self.size_combo.currentText().replace(",", "."))
        except ValueError:
            return
        if 1 <= v <= 400:
            self._text_style({"size": v})

    def _indent_step(self, direction: int) -> None:
        """Augmente ou diminue le retrait de chaque objet sélectionné d'un niveau (0,25 pouce)."""
        sc = self.scene()
        sel = [i for i in (sc.selected_all() if sc else []) if not getattr(i, "locked", False)]
        if not sel:
            return

        def step(_it, st):
            st["text_style"]["indent"] = min(fileformat.MAX_INDENT,
                                             max(0, int(st["text_style"].get("indent", 0)) + direction))
        sc.modify(sel, step, "Augmenter le retrait" if direction > 0 else "Diminuer le retrait")

    def _check_spacing(self, menu: QMenu) -> None:
        sc = self.scene()
        sel = sc.selected_all() if sc else []
        cur = sel[0].text_style.get("spacing", 1.0) if sel else None
        for act in menu.actions():
            act.setChecked(cur is not None and abs(act.data() - cur) < 1e-6)

    def _font_step(self, direction: int) -> None:
        sc = self.scene()
        sel = sc.selected_all() if sc else []
        if not sel:
            return
        cur = sel[0].text_style["size"]
        sizes = sorted(set(FONT_SIZES) | {cur})
        i = sizes.index(cur) + direction
        self._text_style({"size": float(sizes[min(max(i, 0), len(sizes) - 1)])})

    def clear_format(self) -> None:
        from .units import text_style
        base = text_style(self.doc.settings["theme"])
        self._text_style({k: base[k] for k in ("font", "size", "bold", "italic", "underline", "strike")})

    def change_case(self, mode: str) -> None:
        def conv(t: str) -> str:
            if mode == "upper":
                return t.upper()
            if mode == "lower":
                return t.lower()
            if mode == "title":
                return t.title()
            return t[:1].upper() + t[1:].lower()

        def fn(it, st):
            st["text"] = conv(st["text"])
        self._sc(lambda s: s.modify(s.selected_all(), fn, "Modifier la casse"))()

    def _reorder(self, mode: str) -> None:
        self._sc(lambda s: s.reorder(mode))()

    def _view_center(self) -> QPointF:
        return self.view.mapToScene(self.view.viewport().rect().center())

    def _add_at_center(self, type_id: str) -> None:
        sc = self.scene()
        if sc is None:
            return
        fav = favorites.Favorites.index_of(type_id)
        if fav is not None:
            self.insert_favorite(fav, self._view_center())
        else:
            sc.add_shape(type_id, self._view_center())
        self.view.setFocus()

    # ------------------------------------------------------------------ Favoris (Mes formes)
    def _favorites(self):
        if getattr(self.ctx, "favorites", None) is None:
            folder = security.private_dir(compat.config_dir())
            self.ctx.favorites = favorites.Favorites(os.path.join(folder, "favoris.json"))
        return self.ctx.favorites

    def add_to_favorites(self) -> None:
        """« Ajouter aux Favoris » : la sélection devient une forme réutilisable (Mes formes)."""
        sc = self.scene()
        data = sc.copy_selection() if sc is not None else None
        if not data:
            return
        single = sc.single_selected
        default = (single.text.strip().splitlines() or [""])[0] if single is not None else ""
        if not default and isinstance(single, ShapeItem):
            default = single.sdef.name
        name, ok = QInputDialog.getText(self, "Ajouter aux Favoris", "Nom de la forme :",
                                        text=default or "Ma forme")
        if not ok:
            return
        if not self._favorites().add(name, data):
            self.statusBar().showMessage("Le gabarit Favoris est plein ou la forme est trop volumineuse.", 6000)
            return
        for w in self.ctx.windows:
            w.shapes_panel.favorites = self._favorites()
            w.shapes_panel.refresh_favorites()
        self.shapes_panel.open_category(favorites.CATEGORY)

    def insert_favorite(self, index: int, pos) -> None:
        sc = self.scene()
        favs = self._favorites()
        if sc is None or not 0 <= index < len(favs.items):
            return
        try:
            sc.paste(favs.items[index][1], pos - favs.center_of(index), "Insérer une forme favorite")
        except fileformat.DocumentError as exc:
            self._plain_message(QMessageBox.Icon.Warning, APP_NAME, str(exc))

    def _favorite_menu(self, index: int, global_pos) -> None:
        favs = self._favorites()
        m = QMenu(self)
        m.addAction("Renommer…", lambda: self._rename_favorite(index))
        m.addAction(icons.icon("delete"), "Supprimer des Favoris", lambda: self._remove_favorite(index))
        m.exec(global_pos)

    def _rename_favorite(self, index: int) -> None:
        favs = self._favorites()
        name, ok = QInputDialog.getText(self, "Renommer", "Nom de la forme :", text=favs.items[index][0])
        if ok:
            favs.rename(index, name)
            for w in self.ctx.windows:
                w.shapes_panel.refresh_favorites()

    def _remove_favorite(self, index: int) -> None:
        self._favorites().remove(index)
        for w in self.ctx.windows:
            w.shapes_panel.refresh_favorites()

    def _insert(self, type_id: str, style: dict | None = None, text_style: dict | None = None) -> None:
        sc = self.scene()
        if sc is None:
            return
        if stencils.get(type_id).container and sc.selected_shapes():
            sc.wrap_in_container(type_id, style, text_style)  # comme Visio : autour de la sélection
            self.view.setFocus()
            return
        st = sc.new_shape_state(type_id, self._view_center())
        if style:
            st["style"].update(style, themed=False)
        if text_style:
            st["text_style"].update(text_style)
        sc.add_states([st], "Insérer")
        item = sc.item_by_id(st["id"])
        self.view.setFocus()
        if item is not None and type_id in ("basic.text", "basic.callout", "basic.note"):
            item.start_edit()

    def insert_symbol(self, ch: str) -> None:
        sc = self.scene()
        if sc is None:
            return
        if sc.editing_item is not None:
            cur = sc.editing_item.label.textCursor()
            cur.insertText(ch)
            sc.editing_item.label.setTextCursor(cur)
            return
        st = sc.new_shape_state("basic.text", self._view_center())
        st["text"] = ch
        sc.add_states([st], "Insérer un symbole")

    def _select_type(self, kind: str) -> None:
        sc = self.scene()
        if sc is not None:
            n = sc.select_by_type(kind)
            self.statusBar().showMessage(f"{n} objet(s) sélectionné(s).", 4000)

    def _fill_change_shape(self) -> None:
        m = self.change_shape_menu
        m.clear()
        cat = self.shapes_panel.current if self.shapes_panel.current in stencils.CATEGORIES else stencils.FLOW
        for d in stencils.by_category(cat):
            m.addAction(QIcon(icons.stencil_pixmap(d, 20)), d.name).triggered.connect(
                lambda _=False, t=d.type_id: self._sc(lambda s: s.change_shape(t))())
        m.addSeparator()
        for other in stencils.CATEGORIES:
            if other == cat:
                continue
            sub = m.addMenu(other)
            for d in stencils.by_category(other):
                sub.addAction(QIcon(icons.stencil_pixmap(d, 20)), d.name).triggered.connect(
                    lambda _=False, t=d.type_id: self._sc(lambda s: s.change_shape(t))())

    def _fill_layer_menu(self) -> None:
        m = self.layer_menu
        m.clear()
        sc = self.scene()
        if sc is None:
            return
        m.addAction("(aucun calque)").triggered.connect(lambda: sc.assign_layer(sc.selected_all(), ""))
        for lay in sc.layers:
            m.addAction(lay["name"]).triggered.connect(
                lambda _=False, n=lay["name"]: sc.assign_layer(sc.selected_all(), n))
        m.addSeparator()
        m.addAction("Nouveau calque…", self._new_layer_for_selection)

    def _new_layer_for_selection(self) -> None:
        sc = self.scene()
        name, ok = QInputDialog.getText(self, "Nouveau calque", "Nom du calque :")
        name = security.clean_line(name, 64)
        if not ok or not name or sc is None:
            return
        self.doc.undo_stack.beginMacro("Nouveau calque")
        if sc.layer(name) is None:
            before = sc.page_props()
            layers = before["layers"] + [{"name": name, "visible": True, "locked": False, "printable": True}]
            self.doc.undo_stack.push(PageCommand(self.doc, "Nouveau calque", scene=sc, before=before,
                                                 after=dict(before, layers=layers)))
        sc.assign_layer(sc.selected_all(), name)
        self.doc.undo_stack.endMacro()

    def layers_dialog(self) -> None:
        sc = self.scene()
        dlg = LayersDialog(self, sc)
        if dlg.exec() == LayersDialog.DialogCode.Accepted:
            before = sc.page_props()
            after = dict(before, layers=dlg.layers())
            if after != before:
                self.doc.undo_stack.push(PageCommand(self.doc, "Propriétés des calques", scene=sc,
                                                     before=before, after=after))

    # ================================================================== styles, thèmes
    def _apply_quick_style(self, data) -> None:
        row, color = data
        changes, text_color = quickstyles.quick_style(row, color)
        self._sc(lambda s: s.apply_quick_style(changes, text_color))()

    def apply_theme(self, theme: str) -> None:
        variant = self.doc.settings.get("variant", "standard")
        self.doc.undo_stack.beginMacro(f"Thème {THEMES[theme]['name']}")
        self.doc.undo_stack.push(DocSettingsCommand(self.doc, {"theme": self.doc.settings["theme"]},
                                                    {"theme": theme}, "Thème"))
        for p in self.doc.pages:
            p.apply_theme(theme, variant)
        self.doc.undo_stack.endMacro()
        self._refresh_variants()
        self._on_selection()

    def apply_variant(self, variant: str) -> None:
        theme = self.doc.settings["theme"]
        self.doc.undo_stack.beginMacro("Variante")
        self.doc.undo_stack.push(DocSettingsCommand(self.doc, {"variant": self.doc.settings.get("variant", "standard")},
                                                    {"variant": variant}, "Variante"))
        for p in self.doc.pages:
            p.apply_theme(theme, variant)
        self.doc.undo_stack.endMacro()
        self._on_selection()

    def _refresh_variants(self) -> None:
        theme = self.doc.settings["theme"]
        items = []
        for key, name in quickstyles.VARIANTS:
            t = quickstyles.theme_colors(theme, key)
            pm = icons.style_swatch({"fill": t["fill"], "line": t["line"]}, t["text"], 40)
            items.append((pm, f"Variante {name}", key))
        self.variant_gallery.set_items(items)

    def set_route(self, route: str) -> None:
        sc = self.scene()
        self.doc.undo_stack.beginMacro(f"Connecteurs : {ROUTE_LABELS[route]}")
        self._set_default_route(route)
        targets = sc.selected_connectors() or sc.connectors()
        sc.apply_connector_style({"route": route}, items=targets, text="Style des connecteurs")
        self.doc.undo_stack.endMacro()

    def _set_default_route(self, route: str) -> None:
        before = self.doc.settings["route"]
        if before != route:
            self.doc.undo_stack.push(DocSettingsCommand(self.doc, {"route": before}, {"route": route},
                                                        "Style de connecteur par défaut"))

    def toggle_line_jumps(self, on: bool) -> None:
        self.doc.settings["line_jumps"] = on
        for p in self.doc.pages:
            p.request_jump_refresh()

    def set_background(self, color: str) -> None:
        sc = self.scene()
        before = sc.page_props()
        if before["background"] != color:
            self.doc.undo_stack.push(PageCommand(self.doc, "Arrière-plan", scene=sc, before=before,
                                                 after=dict(before, background=color)))

    def _background_dialog(self) -> None:
        c = QColorDialog.getColor(QColor(self.scene().page_bg), self, "Couleur d'arrière-plan")
        if c.isValid():
            self.set_background(c.name())

    def add_border(self, style: str) -> None:
        sc = self.scene()
        title = self.doc.properties.get("title") or sc.page_name
        sc.add_border_title(style, title)

    # ================================================================== liens, commentaires
    def edit_link(self) -> None:
        sc = self.scene()
        shape = sc.single_selected if sc else None
        if not isinstance(shape, ShapeItem):
            return
        pages = [f"page:{p.page_name}" for p in self.doc.pages if p is not sc]
        text, ok = QInputDialog.getItem(self, "Lien hypertexte",
                                        "Adresse (https://…, mailto:…) ou page du document :",
                                        [shape.link] + pages if shape.link else [""] + pages, 0, True)
        if not ok:
            return
        text = text.strip()
        url = fileformat.clean_link(text) if text else ""
        if text and not url:
            QMessageBox.warning(self, "Lien refusé", "Seuls les liens http://, https://, mailto: et les "
                                "pages du document sont autorisés.")
            return

        def set_link(it, st):
            st["link"] = url
        sc.modify([shape], set_link, "Lien hypertexte")

    def open_link(self) -> None:
        sc = self.scene()
        shape = sc.single_selected if sc else None
        if not isinstance(shape, ShapeItem) or not shape.link:
            return
        if shape.link.startswith("page:"):
            for p in self.doc.pages:
                if p.page_name == shape.link[5:]:
                    self.show_page(p)
                    return
            return
        url = security.safe_url(shape.link)
        if url is None:
            return
        box = QMessageBox(QMessageBox.Icon.Question, "Ouvrir un lien externe",
                          "Ce lien va être ouvert dans votre navigateur. Continuer ?", parent=self)
        box.setInformativeText(url)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setStandardButtons(QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Open:
            QDesktopServices.openUrl(QUrl(url, QUrl.ParsingMode.StrictMode))

    def edit_tip(self) -> None:
        sc = self.scene()
        shape = sc.single_selected if sc else None
        if isinstance(shape, ShapeItem):
            text, ok = QInputDialog.getText(self, "Info-bulle d'écran",
                                            "Texte affiché au survol de la forme :", text=shape.tip)
            if ok:
                sc.set_tip(shape, security.clean_line(text, 500))

    def new_comment(self) -> None:
        sc = self.scene()
        shape = sc.single_selected if sc else None
        if not isinstance(shape, ShapeItem):
            self.statusBar().showMessage("Sélectionnez la forme à commenter.", 4000)
            return
        self.show_pane("comments")
        self.comments_pane.refresh()
        self.comments_pane.edit.setFocus()

    def step_comment(self, step: int) -> None:
        sc = self.scene()
        shapes = sc.commented_shapes() if sc else []
        if not shapes:
            self.statusBar().showMessage("Aucun commentaire sur cette page.", 4000)
            return
        cur = sc.single_selected
        idx = shapes.index(cur) + step if cur in shapes else (0 if step > 0 else len(shapes) - 1)
        target = shapes[idx % len(shapes)]
        sc.select_items([target])
        self.view.centerOn(target)
        self.show_pane("comments")

    def show_shapesheet(self) -> None:
        sc = self.scene()
        if sc is not None and isinstance(sc.single_selected, ShapeItem):
            ShapeSheetDialog(self, sc, sc.single_selected).exec()

    # ================================================================== données / processus
    def create_from_data(self, kind: str) -> None:
        dlg = DataImportDialog(self)
        dlg.kind.setCurrentIndex(0 if kind == "org" else 1)
        if dlg.exec() != DataImportDialog.DialogCode.Accepted:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choisir le fichier de données", self._last_dir(),
                                              "Fichiers CSV (*.csv *.txt)")
        if not path:
            return
        try:
            raw = security.read_file_limited(path, 5 * 1024 * 1024)
            headers, rows = datavis.parse_csv(raw)
            name = self.doc.unique_page_name("Données")
            page = datavis.build_page(dlg.kind.currentData(), headers, rows, name, self.doc.settings["theme"])
        except (security.SecurityError, datavis.DataError, fileformat.DocumentError) as exc:
            self._plain_message(QMessageBox.Icon.Warning, "Créer à partir de données", str(exc))
            return
        sc = self.scene()
        if dlg.new_page.isChecked() or sc.all_items():
            new = self.doc.make_page(data=page)
            self.doc.undo_stack.push(PageCommand(self.doc, "Créer à partir de données", add=new,
                                                 index=len(self.doc.pages)))
            self.view.fit_page()
        else:
            self.doc.undo_stack.beginMacro("Créer à partir de données")
            before = sc.page_props()
            self.doc.undo_stack.push(PageCommand(self.doc, "Taille de page", scene=sc, before=before,
                                                 after=dict(before, width=page["width"], height=page["height"])))
            sc.add_states(page["shapes"] + page["connectors"], "Créer à partir de données")
            self.doc.undo_stack.endMacro()
            self.view.fit_page()
        self.statusBar().showMessage(f"{len(page['shapes'])} formes créées à partir de {os.path.basename(path)}.",
                                     6000)

    def link_data(self) -> None:
        sc = self.scene()
        if sc is None:
            return
        selected = sc.selected_all()
        candidates = [it for it in (sc.selected_shapes() if selected else sc.shapes()) if not it.locked]
        if not candidates:
            QMessageBox.information(self, "Lier les données", "Aucune forme modifiable sur cette page.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier de données local", self._last_dir(),
                                              "Fichiers CSV (*.csv *.txt)")
        if not path:
            return
        if path.startswith(("//", "\\\\")):
            QMessageBox.warning(self, "Lier les données", "Choisissez un fichier enregistré sur cet ordinateur.")
            return
        try:
            headers, rows = datavis.parse_csv(security.read_file_limited(path, 5 * 1024 * 1024))
            headers = _clean_data_headers(headers)
        except (security.SecurityError, datavis.DataError) as exc:
            self._plain_message(QMessageBox.Icon.Warning, "Lier les données", str(exc))
            return
        dlg = DataLinkDialog(headers, rows, candidates, self)
        if dlg.exec() != DataLinkDialog.DialogCode.Accepted:
            return
        source_key, shape_key = dlg.mapping()
        source_index = headers.index(source_key)
        row_by_key: dict[str, list[str]] = {}
        duplicate = False
        for row in rows:
            value = row[source_index].strip() if source_index < len(row) else ""
            if value:
                if value in row_by_key:
                    duplicate = True
                    break
                row_by_key[value] = row
        if duplicate:
            self._plain_message(QMessageBox.Icon.Warning, "Lier les données",
                                f"La colonne « {source_key} » contient des clés en double.")
            return

        def shape_value(shape):
            return shape.text.strip() if shape_key == "__text__" else str(shape.data.get(shape_key, "")).strip()

        matched = [shape for shape in candidates if shape_value(shape) in row_by_key and shape_value(shape)]
        if not matched:
            QMessageBox.information(self, "Lier les données", "Aucune forme ne correspond à cette clé.")
            return
        link_path = os.path.abspath(path)
        identity = (os.path.normcase(os.path.normpath(link_path)), source_key, shape_key)
        omitted = 0
        skipped_sources = skipped_capacity = 0
        skipped_fields = 0
        updates: dict[str, tuple[dict, list[dict]]] = {}
        for shape in matched:
            links = [dict(link, fields=list(link.get("fields", [])),
                          field_map=dict(link.get("field_map", {}))) for link in shape.data_links]
            old_index = next((i for i, link in enumerate(links)
                              if _data_link_identity(link) == identity), None)
            old_link = links[old_index] if old_index is not None else None
            if old_link is None and len(links) >= fileformat.MAX_DATA_LINKS_PER_SHAPE:
                skipped_sources += 1
                continue
            field_map = _data_link_field_map(shape, link_path, headers, old_link, source_key=source_key)
            if not field_map:
                skipped_capacity += 1
                continue
            skipped_fields += len(headers) - len(field_map)
            linked_fields = list(field_map.values())
            row = row_by_key[shape_value(shape)]
            data, removed = _merge_linked_data(shape.data, old_link.get("fields", []) if old_link else [],
                                               headers, row, field_map)
            omitted += removed
            link = {"path": link_path, "source_key": source_key, "shape_key": shape_key,
                    "fields": linked_fields, "field_map": field_map}
            if old_index is None:
                links.append(link)
            else:
                links[old_index] = link
            updates[shape.id] = (data, links)

        if not updates:
            reason = (f"Limite de {fileformat.MAX_DATA_LINKS_PER_SHAPE} sources CSV par forme atteinte."
                      if skipped_sources else
                      f"Limite de {fileformat.MAX_DATA_FIELDS} propriétés de données par forme atteinte.")
            QMessageBox.information(self, "Lier les données", reason)
            return

        def update(_it, state):
            state["data"], state["data_links"] = updates[_it.id]
        sc.modify([shape for shape in matched if shape.id in updates], update, "Lier les données CSV")
        self.show_pane("data")
        msg = f"{len(updates)} forme(s) liée(s) à {os.path.basename(path)}."
        if skipped_sources:
            msg += f" {skipped_sources} forme(s) ignorée(s), limite de {fileformat.MAX_DATA_LINKS_PER_SHAPE} sources par forme."
        if skipped_capacity:
            msg += f" {skipped_capacity} forme(s) ignorée(s), limite de {fileformat.MAX_DATA_FIELDS} propriétés de données par forme."
        if skipped_fields:
            msg += f" {skipped_fields} colonne(s) CSV ignorée(s), limite de {fileformat.MAX_DATA_FIELDS} données par forme."
        if omitted:
            msg += f" {omitted} propriété(s) manuelle(s) retirée(s), limite de {fileformat.MAX_DATA_FIELDS} champs par forme."
        self.statusBar().showMessage(msg, 8000)

    def refresh_linked_data(self) -> None:
        groups: dict[tuple[str, str, str], list[tuple[object, ShapeItem, dict]]] = {}
        for page in self.doc.pages:
            for shape in page.shapes():
                for link in shape.data_links:
                    key = (link.get("path", ""), link.get("source_key", ""), link.get("shape_key", ""))
                    groups.setdefault(key, []).append((page, shape, link))
        if not groups:
            QMessageBox.information(self, "Actualiser les données", "Aucune forme n'est liée à un fichier CSV.")
            return

        parsed: dict[str, tuple[list[str], list[list[str]]]] = {}
        errors: list[str] = []
        updates_by_page: dict[object, dict[str, tuple[dict, list[dict]]]] = {}
        working: dict[tuple[object, str], tuple[dict, list[dict]]] = {}
        updated_shapes: set[tuple[object, str]] = set()
        unmatched = omitted = skipped_fields = 0
        for (path, source_key, shape_key), entries in groups.items():
            if path not in parsed:
                try:
                    headers, rows = datavis.parse_csv(security.read_file_limited(path, 5 * 1024 * 1024))
                    parsed[path] = (_clean_data_headers(headers), rows)
                except (OSError, security.SecurityError, datavis.DataError) as exc:
                    errors.append(f"{os.path.basename(path) or path} : {exc}")
                    parsed[path] = ([], [])
            headers, rows = parsed[path]
            if not headers:
                continue
            if source_key not in headers:
                errors.append(f"{os.path.basename(path)} : colonne « {source_key} » introuvable.")
                continue
            source_index = headers.index(source_key)
            row_by_key: dict[str, list[str]] = {}
            duplicate = False
            for row in rows:
                value = row[source_index].strip() if source_index < len(row) else ""
                if not value:
                    continue
                if value in row_by_key:
                    duplicate = True
                    break
                row_by_key[value] = row
            if duplicate:
                errors.append(f"{os.path.basename(path)} : la colonne « {source_key} » contient des clés en double.")
                continue
            for page, shape, original_link in entries:
                token = (page, shape.id)
                current_data, current_links = working.get(token, (shape.data, shape.data_links))
                value = shape.text.strip() if shape_key == "__text__" else str(current_data.get(shape_key, "")).strip()
                row = row_by_key.get(value) if value else None
                if row is None:
                    unmatched += 1
                    continue
                links = [dict(link, fields=list(link.get("fields", [])),
                              field_map=dict(link.get("field_map", {}))) for link in current_links]
                identity = _data_link_identity(original_link)
                link_index = next((i for i, link in enumerate(links)
                                   if _data_link_identity(link) == identity), None)
                if link_index is None:
                    errors.append(f"{os.path.basename(path)} : liaison devenue indisponible pour une forme.")
                    continue
                old_link = links[link_index]
                field_map = _data_link_field_map(shape, path, headers, old_link, current_data)
                if not field_map:
                    errors.append(f"{os.path.basename(path)} : aucune colonne disponible pour actualiser une forme.")
                    continue
                skipped_fields += len(headers) - len(field_map)
                data, removed = _merge_linked_data(current_data, old_link.get("fields", []), headers, row,
                                                   field_map)
                links[link_index] = dict(old_link, fields=list(field_map.values()), field_map=field_map)
                working[token] = (data, links)
                updated_shapes.add(token)
                omitted += removed

        for (page, shape_id), values in working.items():
            updates_by_page.setdefault(page, {})[shape_id] = values
        if updates_by_page:
            self.doc.undo_stack.beginMacro("Actualiser les données liées")
            for page, updates in updates_by_page.items():
                def update(_it, state, values=updates):
                    state["data"], state["data_links"] = values[_it.id]
                page.modify([page.item_by_id(item_id) for item_id in updates], update,
                            "Actualiser les données CSV")
            self.doc.undo_stack.endMacro()
        msg = f"{len(updated_shapes)} forme(s) actualisée(s)."
        if unmatched:
            msg += f" {unmatched} forme(s) sans ligne correspondante ont gardé leurs anciennes données."
        if omitted:
            msg += f" {omitted} propriété(s) manuelle(s) retirée(s) pour respecter la limite de champs."
        if skipped_fields:
            msg += f" {skipped_fields} colonne(s) CSV ignorée(s), limite de {fileformat.MAX_DATA_FIELDS} données par forme."
        if errors:
            msg += "\n\n" + "\n".join(dict.fromkeys(errors))
            self._plain_message(QMessageBox.Icon.Warning, "Actualisation des données", msg)
        elif updated_shapes:
            self.statusBar().showMessage(msg, 8000)
        else:
            self._plain_message(QMessageBox.Icon.Information, "Actualisation des données", msg)

    def unlink_data(self) -> None:
        sc = self.scene()
        shapes = [s for s in sc.selected_shapes() if s.data_links and not s.locked] if sc else []
        if not shapes:
            return
        relations: dict[tuple[str, str, str], str] = {}
        used_labels: set[str] = set()
        for shape in shapes:
            for link in shape.data_links:
                identity = _data_link_identity(link)
                if identity in relations:
                    continue
                path = link.get("path", "")
                source = os.path.basename(path) or "fichier local"
                target = "texte" if link.get("shape_key") == "__text__" else link.get("shape_key", "")
                label = f"{source} · {link.get('source_key', '')} ↔ {target}"
                if label in used_labels:
                    label = f"{label} — {os.path.dirname(path) or path}"
                    suffix_index = 2
                    base_label = label
                    while label in used_labels:
                        label = f"{base_label} ({suffix_index})"
                        suffix_index += 1
                used_labels.add(label)
                relations[identity] = label
        all_label = "— Tous les liens CSV —"
        choices = list(relations.values())
        if len(choices) > 1:
            choices.insert(0, all_label)
        if len(choices) == 1:
            selected = choices[0]
        else:
            selected, ok = QInputDialog.getItem(self, "Dissocier les données", "Source à dissocier :",
                                                choices, 0, False)
            if not ok:
                return
        selected_id = next((identity for identity, label in relations.items() if label == selected), None)
        targets = [shape for shape in shapes if selected == all_label or
                   any(_data_link_identity(link) == selected_id for link in shape.data_links)]
        removed = 0

        def update(_it, state):
            nonlocal removed
            links = state.get("data_links", [])
            if selected == all_label:
                removed += len(links)
                state.pop("data_links", None)
            else:
                kept = [link for link in links if _data_link_identity(link) != selected_id]
                removed += len(links) - len(kept)
                if kept:
                    state["data_links"] = kept
                else:
                    state.pop("data_links", None)

        sc.modify(targets, update, "Dissocier les données CSV")
        self.statusBar().showMessage(f"{removed} lien(s) CSV retiré(s) ; les données importées sont conservées.",
                                     6000)

    def set_data_graphic(self) -> None:
        sc = self.scene()
        shapes = [s for s in sc.selected_shapes() if not s.locked] if sc else []
        if not shapes:
            return
        fields = set(shapes[0].data)
        for shape in shapes[1:]:
            fields.intersection_update(shape.data)
        if not fields:
            QMessageBox.information(self, "Graphique de données",
                                    "Les formes sélectionnées doivent partager au moins une propriété.")
            return
        dlg = DataGraphicDialog(self, sorted(fields, key=str.casefold), shapes[0].data_graphic)
        if dlg.exec() != DataGraphicDialog.DialogCode.Accepted:
            return
        config = dlg.config()
        sc.modify(shapes, lambda _it, state: state.__setitem__("data_graphic", config),
                  "Configurer un graphique de données")

    def clear_data_graphic(self) -> None:
        sc = self.scene()
        shapes = [s for s in sc.selected_shapes() if s.data_graphic and not s.locked] if sc else []
        if not shapes:
            return
        sc.modify(shapes, lambda _it, state: state.pop("data_graphic", None),
                  "Supprimer les graphiques de données")

    def shape_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Rapport de formes",
                                              os.path.join(self._last_dir(), "rapport-formes.csv"),
                                              "Fichier CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        keys: list[str] = []
        rows = []
        for p in self.doc.pages:
            for s in p.shapes():
                for k in s.data:
                    if k not in keys:
                        keys.append(k)
                rows.append((p.page_name, s))
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\n")
        header = ["Page", "Forme", "Texte", "Largeur (mm)", "Hauteur (mm)", "X (mm)",
                  "Y (mm)", "Calque"] + keys
        w.writerow([_csv_safe_cell(value) for value in header])
        for page_name, s in rows:
            row = [_csv_safe_cell(page_name), _csv_safe_cell(s.sdef.name), _csv_safe_cell(s.text),
                   f"{s.w / PX_PER_MM:.1f}", f"{s.h / PX_PER_MM:.1f}",
                   f"{s.pos().x() / PX_PER_MM:.1f}", f"{s.pos().y() / PX_PER_MM:.1f}",
                   _csv_safe_cell(s.layer)]
            row.extend(_csv_safe_cell(s.data.get(k, "")) for k in keys)
            w.writerow(row)
        try:
            security.atomic_write(path, ("﻿" + buf.getvalue()).encode("utf-8"), private=False)
        except OSError as exc:
            self._plain_message(QMessageBox.Icon.Critical, "Rapports de forme", str(exc))
            return
        self.statusBar().showMessage(f"Rapport enregistré : {path}", 6000)

    def create_subprocess(self) -> None:
        sc = self.scene()
        shapes = [s for s in sc.selected_shapes() if not s.locked]
        if not shapes:
            return
        ids = {s.id for s in shapes}
        inner = [c for c in sc.connectors() if c.src.get("shape") in ids and c.dst.get("shape") in ids]
        outer = [c for c in sc.connectors() if (c.src.get("shape") in ids) != (c.dst.get("shape") in ids)]
        name = self.doc.unique_page_name("Sous-processus")
        page = fileformat.default_page(name)
        page["width"], page["height"] = sc.page_w, sc.page_h
        r = QRectF()
        for s in shapes:
            r = s.scene_box() if r.isNull() else r.united(s.scene_box())
        dx, dy = mm_to_px(20) - r.left(), mm_to_px(20) - r.top()
        for s in shapes:
            st = s.state()
            st["x"] += dx
            st["y"] += dy
            page["shapes"].append(st)
        for c in inner:
            st = c.state()
            page["connectors"].append(st)
        new_page = self.doc.make_page(data=page)
        self.doc.undo_stack.beginMacro("Créer un sous-processus")
        self.doc.undo_stack.push(PageCommand(self.doc, "Nouvelle page", add=new_page, index=len(self.doc.pages)))
        self.show_page(sc)
        center = r.center()
        sub = sc.new_shape_state("flow.subprocess", center)
        sub["text"] = name
        sub["link"] = f"page:{name}"
        sc.add_states([sub], "Sous-processus")

        def reglue(it, st):
            for end in (st["src"], st["dst"]):
                if end["shape"] in ids:
                    end["shape"], end["port"] = sub["id"], -1
        sc.modify(outer, reglue, "Recoller les connecteurs")
        sc.delete_items(shapes + inner, "Déplacer vers la page du sous-processus")
        self.doc.undo_stack.endMacro()
        self.statusBar().showMessage(f"Sous-processus créé sur la page « {name} » (Ctrl+clic sur la forme "
                                     "ou menu contextuel pour y aller).", 7000)

    def check_diagram(self) -> None:
        self.show_pane("issues")
        n = self.issues_pane.run()
        self.statusBar().showMessage("Aucun problème trouvé." if not n else f"{n} problème(s) trouvé(s).", 5000)

    # ================================================================== images
    def insert_image_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Insérer une image", self._last_dir(),
                                              "Images (*.png *.jpg *.jpeg)")
        if path:
            self.insert_image(path, self._view_center())

    def insert_image(self, path: str, pos: QPointF) -> None:
        try:
            data = security.read_file_limited(path, fileformat.MAX_IMAGE_BYTES)
        except security.SecurityError as exc:
            self._plain_message(QMessageBox.Icon.Warning, "Image refusée", str(exc))
            return
        self._insert_image_bytes(data, pos)

    def _insert_image_bytes(self, data: bytes, pos: QPointF) -> None:
        sc = self.scene()
        if sc is None:
            return
        if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
            QMessageBox.warning(self, "Image refusée", "Seules les images PNG et JPEG sont acceptées.")
            return
        pm = decode_image(data)
        if pm.isNull():
            QMessageBox.warning(self, "Image refusée", "Image illisible ou trop grande.")
            return
        jpeg = data.startswith(b"\xff\xd8\xff")
        img = pm.toImage()
        if max(img.width(), img.height()) > 3000:
            img = img.scaled(3000, 3000, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "JPEG" if jpeg else "PNG", 92)
        clean = bytes(buf.data())
        if len(clean) > fileformat.MAX_IMAGE_BYTES:
            QMessageBox.warning(self, "Image refusée", "Image trop volumineuse.")
            return
        w, h = float(img.width()), float(img.height())
        scale = min(1.0, mm_to_px(120) / max(w, h))
        st = sc.new_shape_state("special.image", pos, w * scale, h * scale)
        st["image"] = base64.b64encode(clean).decode("ascii")
        st["text"] = ""
        sc.add_states([st], "Insérer une image")

    # ================================================================== pages
    def add_page(self) -> None:
        sc = self.scene()
        page = self.doc.make_page(like=sc)
        idx = self.doc.pages.index(sc) + 1 if sc in self.doc.pages else len(self.doc.pages)
        self.doc.undo_stack.push(PageCommand(self.doc, "Insérer une page", add=page, index=idx))

    def duplicate_page(self) -> None:
        sc = self.scene()
        data = sc.to_dict()
        data["name"] = self.doc.unique_page_name(sc.page_name)
        page = self.doc.make_page(data=data)
        self.doc.undo_stack.push(PageCommand(self.doc, "Dupliquer la page", add=page,
                                             index=self.doc.pages.index(sc) + 1))

    def delete_page(self) -> None:
        sc = self.scene()
        if len(self.doc.pages) <= 1:
            return
        if sc.all_items():
            r = QMessageBox.question(self, "Supprimer la page",
                                     f"Supprimer la page « {sc.page_name} » et son contenu ?")
            if r != QMessageBox.StandardButton.Yes:
                return
        self.doc.undo_stack.push(PageCommand(self.doc, "Supprimer la page", remove=sc))

    def rename_page(self) -> None:
        sc = self.scene()
        name, ok = QInputDialog.getText(self, "Renommer la page", "Nom de la page :", text=sc.page_name)
        name = security.clean_line(name, 100)
        if ok and name and name != sc.page_name:
            name = self.doc.unique_page_name(name) if any(p.page_name == name for p in self.doc.pages) else name
            old = sc.page_name
            self.doc.undo_stack.beginMacro("Renommer la page")
            try:
                before = sc.page_props()
                self.doc.undo_stack.push(PageCommand(self.doc, "Renommer la page", scene=sc, before=before,
                                                     after=dict(before, name=name)))
                # Les pages qui utilisaient cet arrière-plan le gardent.
                for p in self.doc.pages:
                    if sc.is_background and p.backpage == old:
                        b = p.page_props()
                        self.doc.undo_stack.push(PageCommand(self.doc, "Renommer la page", scene=p, before=b,
                                                             after=dict(b, backpage=name)))
            finally:
                self.doc.undo_stack.endMacro()
            self.show_page(sc)

    def _with_container(self, fn) -> None:
        sc = self.scene()
        c = sc.single_selected if sc is not None else None
        if sc is not None and sc.is_plain_container(c):
            fn(sc, c)

    def _container_style(self, type_id: str) -> None:
        sc = self.scene()
        c = sc.single_selected if sc is not None else None
        if not sc or not sc.is_plain_container(c) or c.type_id == type_id:
            return
        style, ts = fileformat.default_shape_styles(type_id, self.doc.settings["theme"])

        def fn(_it, st):
            st["type"] = type_id
            st["style"] = dict(style)
            st["text_style"] = {**st["text_style"], **{k: ts[k] for k in ("color", "bold", "halign", "valign")}}
        sc.modify([c], fn, "Style du conteneur")

    def check_spelling(self) -> None:
        """Révision > Orthographe (F7) : page active d'abord, puis les autres pages."""
        if getattr(self.ctx, "speller", None) is None:
            folder = security.private_dir(compat.config_dir())
            self.ctx.speller = spellcheck.SpellChecker(os.path.join(folder, "dictionnaire.txt"))
        checker = self.ctx.speller
        if not checker.available:
            QMessageBox.information(self, "Orthographe", "Aucun dictionnaire Hunspell n'est installé.\n"
                                    + spellcheck.install_hint())
            return
        sc = self.scene()
        if sc is not None and sc.editing_item is not None:
            sc.editing_item.finish_edit()
        pages = ([sc] if sc in self.doc.pages else []) + [p for p in self.doc.pages if p is not sc]
        targets = []
        for p in pages:
            items = [it for it in p.all_items() if it.text.strip()]
            items.sort(key=lambda it: (round(it.sceneBoundingRect().top() / 20), it.sceneBoundingRect().left()))
            targets += [(p, it) for it in items]
        dlg = SpellDialog(self, checker, targets)
        if not dlg.start():
            QMessageBox.information(self, "Orthographe", "La vérification orthographique est terminée : "
                                    "aucune faute trouvée.")
            return
        dlg.exec()

    def insert_field(self) -> None:
        """Insertion > Champ : ajoute un champ au texte en cours, à la forme sélectionnée ou à une zone
        de texte nouvelle, comme dans Visio."""
        sc = self.scene()
        if sc is None:
            return
        dlg = FieldDialog(self, sc)
        if not dlg.exec():
            return
        tok = fields.token(dlg.field())
        if sc.editing_item is not None:
            sc.editing_item.label.textCursor().insertText(tok)
            return
        single = sc.single_selected
        if single is not None and not getattr(single, "locked", False):
            sc.modify([single], lambda _it, st: st.update(text=(st["text"] + " " + tok).strip()), "Insérer un champ")
            return
        st = sc.new_shape_state("basic.text", sc.page_rect().center())
        st["text"] = tok
        sc.add_states([st], "Insérer un champ")
        sc.select_items([sc.item_by_id(st["id"])])

    def add_background_page(self) -> None:
        """Insertion > Page d'arrière-plan : nouvelle page affectée à la page active si elle n'en a pas."""
        sc = self.scene()
        data = fileformat.default_page(self.doc.unique_page_name("Arrière-plan"))
        if sc is not None:
            data.update(width=sc.page_w, height=sc.page_h)
        data["is_background"] = True
        page = self.doc.make_page(data=data)
        self.doc.undo_stack.beginMacro("Insérer une page d'arrière-plan")
        try:
            self.doc.undo_stack.push(PageCommand(self.doc, "Insérer une page d'arrière-plan", add=page,
                                                 index=len(self.doc.pages)))
            if sc is not None and not sc.is_background and not sc.backpage:
                b = sc.page_props()
                self.doc.undo_stack.push(PageCommand(self.doc, "Arrière-plan", scene=sc, before=b,
                                                     after=dict(b, backpage=page.page_name)))
        finally:
            self.doc.undo_stack.endMacro()
        self.show_page(page)

    def set_backpage(self, name: str) -> None:
        sc = self.scene()
        if sc is None or sc.page_name == name or sc.backpage == name:
            return
        b = sc.page_props()
        self.doc.undo_stack.push(PageCommand(self.doc, "Arrière-plan de la page", scene=sc, before=b,
                                             after=dict(b, backpage=name)))

    def toggle_background_page(self, on: bool) -> None:
        sc = self.scene()
        if sc is None or sc.is_background == on:
            return
        if on and sum(1 for p in self.doc.pages if not p.is_background) <= 1:
            self.statusBar().showMessage("Le document doit garder au moins une page de premier plan.", 6000)
            self._update_page_type_actions()
            return
        b = sc.page_props()
        self.doc.undo_stack.push(PageCommand(self.doc, "Type de page", scene=sc, before=b,
                                             after=dict(b, is_background=on, backpage="" if on else b["backpage"])))

    def _backpage_menu(self) -> QMenu:
        m = QMenu("Arrière-plan de la page", self)
        m.setIcon(icons.icon("background_page"))

        def fill():
            m.clear()
            sc = self.scene()
            group = QActionGroup(m)
            for name in [""] + [p.page_name for p in self.doc.pages if p.is_background and p is not sc]:
                act = m.addAction(name or "Aucun")
                act.setCheckable(True)
                act.setChecked(sc is not None and sc.backpage == name)
                group.addAction(act)
                act.triggered.connect(lambda _=False, n=name: self.set_backpage(n))
            m.addSeparator()
            m.addAction(self.a["page_background_new"])
        m.aboutToShow.connect(fill)
        return m

    def _update_page_type_actions(self) -> None:
        sc = self.scene()
        act = self.a.get("page_is_background")
        if act is not None and sc is not None:
            act.blockSignals(True)
            act.setChecked(sc.is_background)
            act.blockSignals(False)

    def _page_tab_moved(self, src: int, dst: int) -> None:
        order = list(self.doc.pages)
        if not (0 <= src < len(order) and 0 <= dst < len(order)):
            return
        order.insert(dst, order.pop(src))
        self.doc.undo_stack.push(ReorderPagesCommand(self.doc, self.doc.pages, order))

    def reorder_pages_dialog(self) -> None:
        """« Réorganiser les pages » : liste à glisser ou boutons Monter / Descendre."""
        dlg = ReorderPagesDialog(self, self.doc.pages)
        if dlg.exec() == ReorderPagesDialog.DialogCode.Accepted:
            order = dlg.order()
            if order != self.doc.pages:
                self.doc.undo_stack.push(ReorderPagesCommand(self.doc, self.doc.pages, order))

    def _page_menu(self, pos) -> None:
        idx = self.page_tabs.tabAt(pos)
        if idx >= 0:
            self.show_page(self.doc.pages[idx])
        self._update_page_type_actions()
        m = self._menu(self.a["page_add"], self.a["page_dup"], self.a["page_rename"], self.a["page_del"],
                       ("Réorganiser les pages…", "page_dup", self.reorder_pages_dialog), None,
                       self.a["page_background_new"], self.a["page_is_background"], self._backpage_menu(), None,
                       self.a["page_setup"])
        m.exec(self.page_tabs.mapToGlobal(pos))

    def _set_page_size(self, w: float, h: float, text: str) -> None:
        sc = self.scene()
        before = sc.page_props()
        after = dict(before, width=w, height=h)
        if after != before:
            self.doc.undo_stack.push(PageCommand(self.doc, text, scene=sc, before=before, after=after))
            self.view.fit_page()

    def set_orientation(self, landscape: bool) -> None:
        sc = self.scene()
        if (sc.page_w > sc.page_h) != landscape:
            self._set_page_size(sc.page_h, sc.page_w, "Orientation de la page")

    def set_page_format(self, name: str) -> None:
        sc = self.scene()
        w, h = (mm_to_px(v) for v in PAGE_SIZES[name])
        if sc.page_w > sc.page_h:
            w, h = h, w
        self._set_page_size(w, h, f"Format {name}")

    def fit_page_to_drawing(self) -> None:
        sc = self.scene()
        r = sc.drawing_rect()
        if r.isNull():
            return
        margin = mm_to_px(10)
        self.doc.undo_stack.beginMacro("Ajuster la page au dessin")
        sc.select_all()
        sc.nudge(margin - r.left(), margin - r.top())
        sc.clearSelection()
        self._set_page_size(r.width() + 2 * margin, r.height() + 2 * margin, "Ajuster la page")
        self.doc.undo_stack.endMacro()

    def toggle_auto_size(self, on: bool) -> None:
        sc = self.scene()
        before = sc.page_props()
        if before["auto_size"] != on:
            self.doc.undo_stack.push(PageCommand(self.doc, "Taille automatique", scene=sc, before=before,
                                                 after=dict(before, auto_size=on)))
            if on:
                sc.maybe_auto_size()

    def page_setup_dialog(self) -> None:
        sc = self.scene()
        dlg = PageSetupDialog(self, sc)
        if dlg.exec() == PageSetupDialog.DialogCode.Accepted:
            before = sc.page_props()
            after = dlg.props(before)
            if after != before:
                self.doc.undo_stack.push(PageCommand(self.doc, "Mise en page", scene=sc, before=before, after=after))
                self.view.fit_page()

    # ================================================================== affichage
    def _view_setting(self, key: str, on: bool) -> None:
        self.settings.setValue(f"view/{key}", on)
        if self.doc is not None:
            self.doc.apply_settings({key: on})

    def _change_doc_settings(self, values: dict, text: str) -> None:
        before = {k: self.doc.settings.get(k) for k in values}
        if before != values:
            self.doc.undo_stack.push(DocSettingsCommand(self.doc, before, dict(values), text))
            self._sync_view_checks()

    def _sync_view_checks(self) -> None:
        for key in ("snap", "guides"):
            act = self.a[key]
            if act.isChecked() != bool(self.doc.settings.get(key)):
                act.setChecked(bool(self.doc.settings.get(key)))

    def ruler_grid_dialog(self) -> None:
        dlg = RulerGridDialog(self, self.doc.settings)
        if dlg.exec() == RulerGridDialog.DialogCode.Accepted:
            self._change_doc_settings(dlg.values(), "Règle et grille")

    def snap_glue_dialog(self) -> None:
        dlg = SnapGlueDialog(self, self.doc.settings)
        if dlg.exec() == SnapGlueDialog.DialogCode.Accepted:
            self._change_doc_settings(dlg.values(), "Accrocher et coller")

    def toggle_ruler_guides(self, on: bool) -> None:
        self.settings.setValue("view/ruler_guides", on)
        from .scene import DiagramScene
        DiagramScene.show_ruler_guides = on
        for w in self.ctx.windows:
            if w is not self and w.a["ruler_guides"].isChecked() != on:
                w.a["ruler_guides"].setChecked(on)
            if w.doc is not None:
                for p in w.doc.pages:
                    p.update()

    # ------------------------------------------------------------------ fenêtres
    def _fill_switch_menu(self) -> None:
        self.switch_menu.clear()
        for i, w in enumerate(self.ctx.windows, start=1):
            act = self.switch_menu.addAction(f"{i} {w.doc_title()}")
            act.setCheckable(True)
            act.setChecked(w is self)
            act.triggered.connect(lambda _=False, win=w: (win.showNormal() if win.isMinimized() else None,
                                                          win.raise_(), win.activateWindow()))

    def _screen_area(self):
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry()

    def arrange_windows(self) -> None:
        """Affichage > Réorganiser tout : fenêtres côte à côte sur l'écran."""
        wins = [w for w in self.ctx.windows if w.isVisible()]
        if not wins:
            return
        for w, rect in zip(wins, tile_rects(len(wins), self._screen_area())):
            w.showNormal()
            w.setGeometry(rect)

    def cascade_windows(self) -> None:
        wins = [w for w in self.ctx.windows if w.isVisible()]
        area = self._screen_area()
        w0, h0 = int(area.width() * 0.7), int(area.height() * 0.75)
        for i, w in enumerate(wins):
            w.showNormal()
            off = (i % 10) * 32
            w.setGeometry(area.x() + off, area.y() + off, w0, h0)
            w.raise_()

    def toggle_rulers(self, on: bool) -> None:
        self.settings.setValue("view/rulers", on)
        self.canvas.set_rulers_visible(on)

    def _toggle_shapes(self, on: bool) -> None:
        self.shapes_panel.setVisible(on)
        self.settings.setValue("panes/shapes", on)

    def zoom_dialog(self) -> None:
        dlg = ZoomDialog(self, self.view.zoom)
        if dlg.exec() == ZoomDialog.DialogCode.Accepted:
            v = dlg.result_value()
            if v == "page":
                self.view.fit_page()
            elif v == "width":
                self.view.fit_width()
            else:
                self.view.set_zoom(v)

    def start_presentation(self) -> None:
        sc = self.scene()
        if sc is not None and sc.editing_item is not None:
            sc.editing_item.finish_edit()
        self._presentation = PresentationView(self.doc, self.doc.pages.index(sc) if sc in self.doc.pages else 0)
        self._presentation.destroyed.connect(lambda: self.view.viewport().update())
        self._presentation.showFullScreen()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.stack.currentIndex() == 1:
            self.hide_backstage()
            return
        super().keyPressEvent(event)

    def changeEvent(self, e):  # noqa: N802
        if e.type() == e.Type.WindowStateChange and self.titlebar is not None:
            self.titlebar.update_state()
            m = 0 if (self.isMaximized() or self.isFullScreen()) else 1
            self.setContentsMargins(m, m, m, m)
        super().changeEvent(e)

    def paintEvent(self, e):  # noqa: N802
        if not self.native_frame and not self.isMaximized():
            p = QPainter(self)
            p.setPen(QPen(QColor(T["titlebar"]), 1))
            p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
            p.end()
        super().paintEvent(e)

    # ================================================================== Formes rapides (AutoConnect)
    def _quick_shapes(self, shape, direction: int, scene_pt: QPointF) -> None:
        if shape is None:
            self._quick_hide.start(450)
            return
        self._quick_hide.stop()
        if self.quick_popup is None:
            self.quick_popup = QFrame(self, Qt.WindowType.ToolTip)
            self.quick_popup.setStyleSheet(f"QFrame {{ background: {T['surface']}; border: 1px solid {T['border']}; }}"
                                           f"QToolButton {{ border: none; padding: 3px; }}"
                                           f"QToolButton:hover {{ background: {T['hover']}; }}")
            QHBoxLayout(self.quick_popup).setContentsMargins(3, 3, 3, 3)
            self.quick_popup.installEventFilter(self)
        lay = self.quick_popup.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for d in self.shapes_panel.quick_shapes():
            b = QToolButton()
            b.setIcon(QIcon(icons.stencil_pixmap(d, 24)))
            b.setIconSize(QSize(24, 24))
            b.setToolTip(d.name)
            b.clicked.connect(lambda _=False, sh=shape, di=direction, t=d.type_id: self._quick_add(sh, di, t))
            lay.addWidget(b)
        self.quick_popup.adjustSize()
        vp = self.view.viewport()
        g = vp.mapToGlobal(self.view.mapFromScene(scene_pt))
        dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[direction]
        size = self.quick_popup.size()
        x = g.x() + dx * 18 - (size.width() // 2 if dx == 0 else (0 if dx > 0 else size.width()))
        y = g.y() + dy * 18 - (size.height() // 2 if dy == 0 else (0 if dy > 0 else size.height()))
        self.quick_popup.move(QPoint(x, y))
        self.quick_popup.show()

    def _quick_add(self, shape, direction: int, type_id: str) -> None:
        self._hide_quick_shapes(force=True)
        sc = self.scene()
        if sc is not None and shape.scene() is sc:
            sc.autoconnect(shape, direction, type_id)

    def _hide_quick_shapes(self, force: bool = False) -> None:
        if self.quick_popup is not None and (force or not self.quick_popup.underMouse()):
            self.quick_popup.hide()

    def eventFilter(self, obj, ev):  # noqa: N802
        # Double-clic sur « Reproduire la mise en forme » : le pinceau reste actif (Office).
        if obj is getattr(self, "_painter_btn", None) and ev.type() == QEvent.Type.MouseButtonDblClick:
            self.format_painter_sticky()
            return True
        quick = getattr(self, "quick_popup", None)
        if quick is None:
            return super().eventFilter(obj, ev)
        if obj is self.quick_popup and ev.type() == ev.Type.Leave:
            self._quick_hide.start(300)
        elif obj is self.quick_popup and ev.type() == ev.Type.Enter:
            self._quick_hide.stop()
        return super().eventFilter(obj, ev)

    # ================================================================== menu contextuel + mini-barre
    def _mini_toolbar(self, menu: QMenu) -> QWidgetAction:
        w = QWidget()
        lay = QGridLayout(w)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        font = QFontComboBox()
        font.setFixedWidth(130)
        sc = self.scene()
        sel = sc.selected_all()
        if sel:
            font.setCurrentFont(QFont(sel[0].text_style["font"]))
        font.currentFontChanged.connect(lambda f: self._text_style({"font": f.family()}))
        size = QComboBox()
        size.setEditable(True)
        size.setFixedWidth(52)
        size.addItems([str(s) for s in FONT_SIZES])
        if sel:
            size.setEditText(f"{sel[0].text_style['size']:g}")
        size.activated.connect(lambda _i: self._text_style({"size": float(size.currentText())}))
        lay.addWidget(font, 0, 0, 1, 4)
        lay.addWidget(size, 0, 4, 1, 2)
        for col, key in enumerate(("font_grow", "font_shrink")):
            lay.addWidget(RibbonButton(self.a[key], ICON), 0, 6 + col)
        row_items = [self.a["bold"], self.a["italic"], self.a["underline"], self.a["halign_center"]]
        for col, act in enumerate(row_items):
            lay.addWidget(RibbonButton(act, ICON), 1, col)
        style_btn = RibbonButton(None, ICON, icon_name="quick_styles", tooltip="<b>Style</b>",
                                 menu=self._quick_style_menu())
        lay.addWidget(style_btn, 1, 4)
        fill = self._color_button("fill", "Remplissage", self.fill_btn.current,
                                  lambda c: (menu.close(), self._shape_style({"fill": c}, "Remplissage")),
                                  none_label="Aucun remplissage", kind=ICON)
        line = self._color_button("line_color", "Trait", self.line_btn.current,
                                  lambda c: (menu.close(), self._sc(lambda s: s.apply_line_to_selection({"line": c}))()),
                                  none_label="Aucun trait", kind=ICON)
        # Comme la mini-barre de Visio : le bouton Trait propose aussi épaisseur, tirets et flèches.
        line_menu = line.menu()
        line_menu.addSeparator()
        line_menu.addMenu(self._weight_menu())
        line_menu.addMenu(self._dash_menu())
        if any(isinstance(i, ConnectorItem) for i in sel):
            line_menu.addMenu(self._arrow_menu())
        lay.addWidget(fill, 1, 5)
        lay.addWidget(line, 1, 6)
        lay.addWidget(RibbonButton(self.a["format_painter"], ICON), 1, 7)
        act = QWidgetAction(menu)
        act.setDefaultWidget(w)
        return act

    def _quick_style_menu(self) -> QMenu:
        m = QMenu(self)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(2)
        for i, (row, color, tip) in enumerate(quickstyles.gallery_items()):
            style, text_color = quickstyles.quick_style(row, color)
            b = QToolButton()
            b.setIcon(QIcon(icons.style_swatch(style, text_color, 36)))
            b.setIconSize(QSize(36, 36))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, d=(row, color): (m.close(), self._apply_quick_style(d)))
            grid.addWidget(b, i // 7, i % 7)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(holder)
        m.addAction(wa)
        return m

    def _context_menu(self, global_pos) -> None:
        sc = self.scene()
        a = self.a
        menu = QMenu(self)
        sel = sc.selected_all()
        if sel:
            menu.addAction(self._mini_toolbar(menu))
            menu.addSeparator()
            for key in ("cut", "copy", "paste", "duplicate", "delete"):
                menu.addAction(a[key])
            menu.addSeparator()
            menu.addAction(a["edit_text"])
            single = sc.single_selected
            if isinstance(single, ShapeItem):
                self._fill_change_shape()
                cs = menu.addMenu(icons.icon("change_shape"), "Modifier la forme")
                for act in self.change_shape_menu.actions():
                    cs.addAction(act)
            arrange = menu.addMenu(icons.icon("front"), "Organiser")
            for key in ("front", "forward", "back", "backward", None, "rotate_right", "rotate_left",
                        "flip_h", "flip_v"):
                arrange.addSeparator() if key is None else arrange.addAction(a[key])
            grp = menu.addMenu(icons.icon("group"), "Groupe")
            grp.addAction(a["group"])
            grp.addAction(a["ungroup"])
            menu.addAction(a["add_favorite"])
            if isinstance(single, ShapeItem):
                menu.addSeparator()
                menu.addAction(a["link"])
                if single.link:
                    menu.addAction(icons.icon("link"), "Atteindre la page" if single.link.startswith("page:")
                                   else "Ouvrir le lien hypertexte", self.open_link)
                menu.addAction(a["new_comment"])
                data_menu = menu.addMenu(icons.icon("shape_data"), "Données")
                data_menu.addAction(icons.icon("shape_data"), "Fenêtre Données de forme",
                                    lambda: self.show_pane("data"))
                data_menu.addAction(a["data_link"])
                data_menu.addAction(a["data_refresh"])
                if single.data_links:
                    data_menu.addAction(a["data_unlink"])
                data_menu.addSeparator()
                data_menu.addAction(a["data_graphic"])
                if single.data_graphic:
                    data_menu.addAction(a["data_graphic_clear"])
                data_menu.addAction(a["shapesheet"])
                menu.addAction(a["lock"] if not single.locked else a["unlock"])
            if any(isinstance(i, ConnectorItem) for i in sel):
                menu.addSeparator()
                menu.addMenu(self._weight_menu())
                menu.addMenu(self._dash_menu())
                menu.addMenu(self._arrow_menu())
                for r in ROUTES:
                    act = menu.addAction(icons.icon("route"), f"Connecteur {ROUTE_LABELS[r].lower()}")
                    act.triggered.connect(lambda _=False, v=r: sc.apply_connector_style(
                        {"route": v}, text="Type de connecteur"))
            menu.addSeparator()
            menu.addAction(icons.icon("format_panel"), "Format de la forme", lambda: self.show_pane("format"))
        else:
            menu.addAction(a["paste"])
            menu.addAction(a["select_all"])
            menu.addSeparator()
            menu.addAction(a["grid"])
            menu.addAction(a["rulers"])
            menu.addAction(a["fit_page"])
            menu.addSeparator()
            menu.addAction(a["page_add"])
            menu.addAction(a["page_setup"])
            menu.addAction(icons.icon("format_panel"), "Format de la page", lambda: self.show_pane("format"))
        menu.exec(global_pos)

    # ================================================================== backstage
    def show_backstage(self, page: str = "home") -> None:
        self.backstage.set_recent(self.ctx.recent_files())
        self.backstage.sync_print_options()
        self.backstage.select(page)
        self.stack.setCurrentIndex(1)
        self.statusBar().hide()

    def hide_backstage(self) -> None:
        self.stack.setCurrentIndex(0)
        self.statusBar().show()
        self.view.setFocus()

    def _backstage_command(self, cmd: str) -> None:
        handlers = {
            "save": self.save, "save_as": self.save_as, "close": self.close,
            "export_pdf": self.export_pdf, "export_png": lambda: self.export_image("png"),
            "export_jpg": lambda: self.export_image("jpg"), "export_svg": self.export_svg,
            "export_html": self.export_html,
            "export_vsdx": self.export_vsdx, "import_vsdx": self.import_vsdx_dialog,
            "protect": self.protect, "unprotect": self.unprotect, "properties": self.edit_properties,
            "options": self.show_options, "check_diagram": self.check_diagram,
            "clear_recent": self._clear_recent, "clear_autosave": self._clear_autosave,
        }
        fn = handlers.get(cmd)
        if fn is None:
            return
        if cmd not in ("protect", "unprotect", "properties", "options", "clear_recent", "clear_autosave"):
            self.hide_backstage()
        fn()
        if self.stack.currentIndex() == 1:
            self.backstage.set_info()
            self.backstage.set_recent(self.ctx.recent_files())

    def _clear_recent(self) -> None:
        self.ctx.clear_recent()
        self.backstage.set_recent([])

    def _clear_autosave(self) -> None:
        n = self.ctx.clear_autosaves()
        QMessageBox.information(self, APP_NAME, f"{n} fichier(s) de récupération supprimé(s).")

    def new_from_template(self, template: str) -> None:
        data = templates.build_blank(template)
        doc = Document(data)
        hint = None
        if self.is_pristine():
            self.title_hint = hint
            self.set_document(doc)
            target = self
        else:
            target = self.ctx.new_window(doc, title_hint=hint)
        cat = templates.category_for(template)
        if template == "cff":
            cats = [stencils.CFF, stencils.FLOW, stencils.BASIC]
            cat = stencils.FLOW
        elif cat == stencils.BASIC:
            cats = [stencils.BASIC, stencils.FLOW, stencils.ARROWS_CAT]
        else:
            cats = [cat, stencils.BASIC, stencils.ARROWS_CAT]
        target.shapes_panel.set_open(cats, cat)
        target._update_cff_tab()
        target.hide_backstage()
        target.view.fit_page()

    # ================================================================== fichiers
    def _last_dir(self) -> str:
        return self.settings.value("files/last_dir", compat.documents_dir())

    def _remember_dir(self, path: str) -> None:
        self.settings.setValue("files/last_dir", os.path.dirname(os.path.abspath(path)))

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir", self._last_dir(),
                                              f"Tous les dessins (*{FILE_EXT} *.vsdx);;{LXD_FILTER};;{VSDX_FILTER}")
        if path:
            self.open_path(path)

    def import_vsdx_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer un fichier Visio", self._last_dir(), VSDX_FILTER)
        if path:
            self.open_path(path)

    def ask_password(self, filename: str):
        attempts = [0]

        def ask():
            dlg = PasswordDialog(self, "enter", filename, "Mot de passe incorrect." if attempts[0] else "")
            attempts[0] += 1
            if dlg.exec() != PasswordDialog.DialogCode.Accepted:
                return None
            return dlg.password()
        return ask

    def open_path(self, path: str) -> None:
        path = os.path.abspath(path)
        existing = self.ctx.find_window(path)
        if existing is not None:
            existing.hide_backstage()
            existing.raise_()
            existing.activateWindow()
            return
        try:
            if path.lower().endswith(".vsdx"):
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    data, warnings = vsdx.import_vsdx(path)
                finally:
                    QApplication.restoreOverrideCursor()
                password = None
            else:
                data, warnings, password = fileformat.load_file(path, self.ask_password(os.path.basename(path)))
            doc = Document(data)
        except fileformat.PasswordRequired:
            return
        except (fileformat.DocumentError, security.SecurityError, OSError) as exc:
            self._plain_message(QMessageBox.Icon.Critical, "Impossible d'ouvrir le document",
                                f"{os.path.basename(path)}\n\n{exc}")
            return
        doc.path = path
        doc.password = password
        self._remember_dir(path)
        self.ctx.add_recent(path)
        if self.is_pristine():
            self.title_hint = None
            self.set_document(doc)
            target = self
        else:
            target = self.ctx.new_window(doc)
        target.hide_backstage()
        target.view.fit_page()
        if warnings:
            box = QMessageBox(QMessageBox.Icon.Information, "Document ouvert avec des remarques",
                              "\n".join(f"• {w}" for w in warnings[:12]), QMessageBox.StandardButton.Ok,
                              target)
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.exec()

    def save(self) -> bool:
        if self.doc.path is None:
            return self.save_as()
        return self._write(self.doc.path)

    def save_as(self) -> bool:
        start = self.doc.path or os.path.join(self._last_dir(), self.doc_title())
        path, chosen = QFileDialog.getSaveFileName(self, "Enregistrer sous", start, f"{LXD_FILTER};;{VSDX_FILTER}")
        if not path:
            return False
        if chosen == VSDX_FILTER and not path.lower().endswith(".vsdx"):
            path += ".vsdx"
        elif not path.lower().endswith((".vsdx", FILE_EXT)):
            path = fileformat.ensure_extension(path)
        return self._write(path)

    def _write(self, path: str) -> bool:
        is_vsdx = path.lower().endswith(".vsdx")
        if is_vsdx and self.doc.password:
            QMessageBox.warning(self, "Format incompatible", "Le format Visio (.vsdx) ne permet pas le "
                                f"chiffrement. Enregistrez au format {FILE_EXT} pour conserver la protection.")
            return self.save_as()
        try:
            sc = self.scene()
            if sc is not None and sc.editing_item is not None:
                sc.editing_item.finish_edit()
            if is_vsdx:
                vsdx.export_vsdx(self.doc, path)
                self.doc.path = path
                self.doc.undo_stack.setClean()
            else:
                self.doc.save(path)
        except (OSError, security.SecurityError, fileformat.DocumentError, ValueError) as exc:
            self._plain_message(QMessageBox.Icon.Critical, "Échec de l'enregistrement",
                                f"{path}\n\n{exc}")
            return False
        self._remember_dir(path)
        self.ctx.add_recent(path)
        self.ctx.remove_autosave(self.doc)
        self.title_hint = None
        self._update_title()
        self.statusBar().showMessage(f"Enregistré : {path}", 5000)
        return True

    def _export_path(self, title: str, filt: str, ext: str) -> str | None:
        base = os.path.splitext(self.doc_title())[0]
        path, _ = QFileDialog.getSaveFileName(self, title, os.path.join(self._last_dir(), base + ext), filt)
        if not path:
            return None
        if not path.lower().endswith(ext) and not (ext == ".jpg" and path.lower().endswith(".jpeg")):
            path += ext
        return path

    def _run_export(self, fn, path: str) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            fn()
        except (OSError, security.SecurityError, fileformat.DocumentError, ValueError) as exc:
            QApplication.restoreOverrideCursor()
            self._plain_message(QMessageBox.Icon.Critical, "Échec de l'export", f"{path}\n\n{exc}")
            return
        QApplication.restoreOverrideCursor()
        self._remember_dir(path)
        self.statusBar().showMessage(f"Exporté : {path}", 6000)

    def export_pdf(self) -> None:
        path = self._export_path("Exporter en PDF", "Document PDF (*.pdf)", ".pdf")
        if path:
            title = self.doc.properties.get("title") or self.doc_title()
            pages = [p for p in self.doc.pages if not p.is_background] or list(self.doc.pages)
            self._run_export(lambda: export.export_pdf(pages, path, title), path)

    def export_image(self, kind: str) -> None:
        sc = self.scene()
        dlg = ImageExportDialog(self, bool(sc.selected_all()), kind == "jpg")
        if dlg.exec() != ImageExportDialog.DialogCode.Accepted:
            return
        opts = dlg.options()
        ext = ".jpg" if kind == "jpg" else ".png"
        filt = "Image JPEG (*.jpg *.jpeg)" if kind == "jpg" else "Image PNG (*.png)"
        path = self._export_path("Exporter en image", filt, ext)
        if path:
            self._run_export(lambda: export.export_image(sc, path, opts["mode"], opts["dpi"], opts["transparent"]),
                             path)

    def export_html(self) -> None:
        path = self._export_path("Enregistrer comme page web", "Page web (*.html *.htm)", ".html")
        if path:
            title = self.doc.properties.get("title") or self.doc_title()
            pages = [p for p in self.doc.pages if not p.is_background] or list(self.doc.pages)
            self._run_export(lambda: export.export_html(pages, path, title), path)

    def export_svg(self) -> None:
        sc = self.scene()
        path = self._export_path("Exporter en SVG", "Image SVG (*.svg)", ".svg")
        if path:
            self._run_export(lambda: export.export_svg(sc, path, "page"), path)

    def export_vsdx(self) -> None:
        path = self._export_path("Exporter au format Visio", VSDX_FILTER, ".vsdx")
        if path:
            self._run_export(lambda: vsdx.export_vsdx(self.doc, path), path)

    # ================================================================== sécurité
    def protect(self) -> None:
        if not security.encryption_available():
            QMessageBox.warning(self, APP_NAME, "Le chiffrement nécessite la bibliothèque OpenSSL.")
            return
        dlg = PasswordDialog(self, "set")
        if dlg.exec() != PasswordDialog.DialogCode.Accepted:
            return
        self.doc.password = dlg.password()
        if self.doc.path and self.doc.path.lower().endswith(".vsdx"):
            self.doc.path = None
        self.doc.undo_stack.resetClean()
        self._update_title()
        self.statusBar().showMessage("Le document sera chiffré au prochain enregistrement.", 6000)

    def unprotect(self) -> None:
        r = QMessageBox.question(self, "Supprimer le mot de passe",
                                 "Le document sera enregistré sans chiffrement. Continuer ?")
        if r == QMessageBox.StandardButton.Yes:
            self.doc.password = None
            self.doc.undo_stack.resetClean()
            self._update_title()

    def edit_properties(self) -> None:
        dlg = PropertiesDialog(self, self.doc.properties)
        if dlg.exec() == PropertiesDialog.DialogCode.Accepted:
            values = dlg.values()
            if values != self.doc.properties:
                self.doc.properties = values
                self.doc.undo_stack.resetClean()
                self._update_title()

    def show_options(self) -> None:
        dlg = OptionsDialog(self, self.settings)
        if dlg.exec() == OptionsDialog.DialogCode.Accepted:
            dlg.save()
            for w in self.ctx.windows:
                w.apply_autosave_interval()

    def about(self) -> None:
        QMessageBox.about(self, f"À propos de {APP_NAME}",
                          f"<h3>{APP_NAME} {__version__}</h3><p>Éditeur de diagrammes libre pour Linux, "
                          "Windows et macOS, compatible avec les fichiers .vsdx, sans macros ni connexion réseau.</p>"
                          "<p>© 2026 Joss943 et les contributeurs — licence MIT.<br>"
                          "Interface Qt 6 via PyQt6 (GPL v3).</p>"
                          "<p><small>Projet indépendant, non affilié à Microsoft, ni approuvé ou soutenu "
                          "par Microsoft. Microsoft et Visio sont des marques du groupe Microsoft, citées "
                          "uniquement pour indiquer la compatibilité.</small></p>"
                          "<p><small>Aucune donnée personnelle n'est collectée ni transmise.</small></p>")

    # ================================================================== sauvegarde auto, fermeture
    def apply_autosave_interval(self) -> None:
        minutes = self.settings.value("autosave/minutes", 3, type=int)
        if minutes > 0:
            self.autosave_timer.start(minutes * 60 * 1000)
        else:
            self.autosave_timer.stop()

    def autosave(self) -> None:
        if self.doc is None or not self.doc.is_modified():
            return
        try:
            self.ctx.write_autosave(self.doc)
        except (OSError, security.SecurityError, ValueError):
            self.statusBar().showMessage("Échec de la sauvegarde de récupération.", 5000)

    def maybe_save(self) -> bool:
        if self.doc is None or not self.doc.is_modified():
            return True
        self.hide_backstage()
        box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME,
                          f"Voulez-vous enregistrer les modifications apportées à « {self.doc_title()} » ?",
                          parent=self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        save = box.addButton("Enregistrer", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Ne pas enregistrer", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel:
            return False
        if clicked is save:
            return self.save()
        return True

    def closeEvent(self, event):  # noqa: N802
        if not self.maybe_save():
            event.ignore()
            return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("layout/editor_splitter", self.splitter.saveState())
        self.settings.setValue("layout/ribbon_collapsed", self.ribbon.is_collapsed())
        self.autosave_timer.stop()
        if self.quick_popup is not None:
            self.quick_popup.hide()
        self._detach_document()
        self.view.setScene(None)
        self.panzoom_pane.overview.setScene(None)
        self.ctx.window_closed(self)
        event.accept()

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls() and any(u.isLocalFile() and u.toLocalFile().lower().endswith((FILE_EXT, ".vsdx"))
                                              for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        for u in event.mimeData().urls():
            if u.isLocalFile() and u.toLocalFile().lower().endswith((FILE_EXT, ".vsdx")):
                self.open_path(u.toLocalFile())
