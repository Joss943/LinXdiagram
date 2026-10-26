"""Boîtes de dialogue : mot de passe, export d'image, ShapeSheet, raccourcis, récupération."""

from __future__ import annotations

import copy
import os
import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                             QHBoxLayout, QPushButton,
                             QFormLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QProgressBar, QSpinBox, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

from . import compat, security
from .fileformat import clean_shape_style, clean_text_style, normalize_status_key
from .units import PX_PER_INCH


class PasswordDialog(QDialog):
    """Saisie (ouverture) ou définition (chiffrement) d'un mot de passe."""

    def __init__(self, parent, mode: str = "enter", filename: str = "", error: str = ""):
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle("Mot de passe" if mode == "enter" else "Chiffrer avec un mot de passe")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        if mode == "enter":
            intro = f"Le document « {filename} » est protégé.\nSaisissez son mot de passe :"
        else:
            intro = ("Le document sera chiffré (AES-256-GCM, clé dérivée par scrypt).\n"
                     "Attention : sans le mot de passe, il sera impossible de le récupérer.")
        lab = QLabel(intro)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        if error:
            err = QLabel(error)
            err.setStyleSheet("color: #dc2626; font-weight: 600;")
            lay.addWidget(err)
        form = QFormLayout()
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Mot de passe", self.pw)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.strength = QProgressBar()
        self.strength.setRange(0, 4)
        self.strength.setTextVisible(True)
        self.strength.setFormat("")
        if mode == "set":
            form.addRow("Confirmation", self.confirm)
            form.addRow("Robustesse", self.strength)
        lay.addLayout(form)
        self.show_pw = QCheckBox("Afficher le mot de passe")
        self.show_pw.toggled.connect(self._toggle)
        lay.addWidget(self.show_pw)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color: #dc2626;")
        lay.addWidget(self.msg)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.pw.textChanged.connect(self._update_strength)
        self._update_strength("")

    def _toggle(self, on: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        self.pw.setEchoMode(mode)
        self.confirm.setEchoMode(mode)

    def _update_strength(self, text: str) -> None:
        score, label = security.password_strength(text)
        self.strength.setValue(score)
        self.strength.setFormat(label)
        colors = ["#dc2626", "#dc2626", "#f59e0b", "#16a34a", "#15803d"]
        self.strength.setStyleSheet(f"QProgressBar::chunk {{ background: {colors[score]}; }}")

    def _accept(self) -> None:
        if self.mode == "set":
            if len(self.pw.text()) < 8:
                self.msg.setText("Utilisez au moins 8 caractères.")
                return
            if self.pw.text() != self.confirm.text():
                self.msg.setText("Les deux mots de passe ne correspondent pas.")
                return
        elif not self.pw.text():
            return
        self.accept()

    def password(self) -> str:
        return self.pw.text()


class ImageExportDialog(QDialog):
    def __init__(self, parent, has_selection: bool, jpeg: bool):
        super().__init__(parent)
        self.setWindowTitle("Exporter en image")
        form = QFormLayout(self)
        self.zone = QComboBox()
        self.zone.addItem("Page entière", "page")
        self.zone.addItem("Dessin (ajusté au contenu)", "drawing")
        if has_selection:
            self.zone.addItem("Sélection", "selection")
        form.addRow("Zone", self.zone)
        self.dpi = QComboBox()
        for d in (96, 150, 200, 300, 600):
            self.dpi.addItem(f"{d} ppp", d)
        self.dpi.setCurrentIndex(1)
        form.addRow("Résolution", self.dpi)
        self.transparent = QCheckBox("Fond transparent")
        self.transparent.setEnabled(not jpeg)
        form.addRow("", self.transparent)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def options(self) -> dict:
        return {"mode": self.zone.currentData(), "dpi": self.dpi.currentData(),
                "transparent": self.transparent.isChecked()}


class PropertiesDialog(QDialog):
    FIELDS = (("title", "Titre"), ("subject", "Objet"), ("author", "Auteur"),
              ("company", "Société"), ("keywords", "Mots-clés"))

    def __init__(self, parent, props: dict):
        super().__init__(parent)
        self.setWindowTitle("Propriétés du document")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.edits = {}
        for key, label in self.FIELDS:
            e = QLineEdit(props.get(key, ""))
            e.setMaxLength(300)
            self.edits[key] = e
            form.addRow(label, e)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {k: security.clean_line(e.text(), 300) for k, e in self.edits.items()}


# ------------------------------------------------------------------------ ShapeSheet

def _yn(v: bool) -> str:
    return "1" if v else "0"


class ShapeSheetDialog(QDialog):
    """Vue « ShapeSheet » : les cellules Visio de la forme, éditables en valeurs.

    Pour la sécurité, seules des valeurs littérales sont acceptées : aucune
    formule n'est interprétée.
    """

    def __init__(self, parent, scene, shape):
        super().__init__(parent)
        self.scene = scene
        self.shape = shape
        self.setWindowTitle(f"ShapeSheet — {shape.sdef.name}")
        self.resize(520, 600)
        lay = QVBoxLayout(self)
        info = QLabel("Cellules au format Visio (pouces, origine en bas à gauche de la page). "
                      "Modifiez une valeur puis validez. Les formules ne sont pas acceptées.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Section", "Cellule", "Valeur"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay.addWidget(self.table, 1)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color: #dc2626;")
        lay.addWidget(self.msg)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._fill()

    def _cells(self) -> list[tuple[str, str, str, bool]]:
        st = self.shape.state()
        ph = self.scene.page_h
        s, ts = st["style"], st["text_style"]
        style_bits = (1 if ts["bold"] else 0) | (2 if ts["italic"] else 0) | (4 if ts["underline"] else 0)
        return [
            ("Shape Transform", "PinX", f"{st['x'] / PX_PER_INCH:.4f}", True),
            ("Shape Transform", "PinY", f"{(ph - st['y']) / PX_PER_INCH:.4f}", True),
            ("Shape Transform", "Width", f"{st['w'] / PX_PER_INCH:.4f}", True),
            ("Shape Transform", "Height", f"{st['h'] / PX_PER_INCH:.4f}", True),
            ("Shape Transform", "LocPinX", f"{st['w'] / 2 / PX_PER_INCH:.4f}", False),
            ("Shape Transform", "LocPinY", f"{st['h'] / 2 / PX_PER_INCH:.4f}", False),
            ("Shape Transform", "Angle", f"{-st['rotation']:.2f} deg", True),
            ("Shape Transform", "FlipX", _yn(st["flip_h"]), True),
            ("Shape Transform", "FlipY", _yn(st["flip_v"]), True),
            ("Line Format", "LineWeight", f"{s['line_width'] * 72 / PX_PER_INCH:.2f} pt", True),
            ("Line Format", "LineColor", s["line"] or "Themed", True),
            ("Line Format", "LinePattern",
             str({"solid": 1, "dash": 2, "dot": 3, "dashdot": 4}[s["dash"]] if s["line"] else 0), True),
            ("Line Format", "Rounding", f"{s['rounding']:.2f} mm", True),
            ("Fill Format", "FillForegnd", s["fill"] or "Themed", True),
            ("Fill Format", "FillPattern", _yn(bool(s["fill"])), False),
            ("Fill Format", "FillForegndTrans", f"{s['transparency']:.0f}%", True),
            ("Character", "Font", ts["font"], True),
            ("Character", "Size", f"{ts['size']:.1f} pt", True),
            ("Character", "Color", ts["color"], True),
            ("Character", "Style", str(style_bits), True),
            ("Paragraph", "HorzAlign", str({"left": 0, "center": 1, "right": 2}[ts["halign"]]), True),
            ("Text Block Format", "VerticalAlign", str({"top": 0, "middle": 1, "bottom": 2}[ts["valign"]]), True),
            ("User-defined Cells", "User.LinXType", st["type"], False),
        ] + [("Shape Data", f"Prop.{k}", v, False) for k, v in st["data"].items()]

    def _fill(self) -> None:
        cells = self._cells()
        self.table.setRowCount(len(cells))
        for r, (sec, name, val, editable) in enumerate(cells):
            for c, text in enumerate((sec, name, val)):
                it = QTableWidgetItem(text)
                if c < 2 or not editable:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if c == 2:
                        it.setForeground(QColor("#6b7280"))
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()

    @staticmethod
    def _number(text: str) -> float:
        t = text.strip().lower()
        for unit in ("deg", "pt", "mm", "%", "in"):
            if t.endswith(unit):
                t = t[: -len(unit)].strip()
        v = float(t.replace(",", "."))  # une formule n'est jamais un nombre : refusée
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("valeur")
        return v

    def _apply(self) -> None:
        st = copy.deepcopy(self.shape.state())
        ph = self.scene.page_h
        try:
            for r in range(self.table.rowCount()):
                name = self.table.item(r, 1).text()
                val = self.table.item(r, 2).text().strip()
                if name == "PinX":
                    st["x"] = self._number(val) * PX_PER_INCH
                elif name == "PinY":
                    st["y"] = ph - self._number(val) * PX_PER_INCH
                elif name == "Width":
                    st["w"] = max(1.0, self._number(val) * PX_PER_INCH)
                elif name == "Height":
                    st["h"] = max(1.0, self._number(val) * PX_PER_INCH)
                elif name == "Angle":
                    st["rotation"] = -self._number(val)
                elif name == "FlipX":
                    st["flip_h"] = val == "1"
                elif name == "FlipY":
                    st["flip_v"] = val == "1"
                elif name == "LineWeight":
                    st["style"]["line_width"] = self._number(val) * PX_PER_INCH / 72
                elif name == "LineColor" and val != "Themed":
                    st["style"]["line"] = val
                elif name == "LinePattern":
                    p = int(self._number(val))
                    if p == 0:
                        st["style"]["line"] = ""
                    else:
                        st["style"]["dash"] = {1: "solid", 2: "dash", 3: "dot", 4: "dashdot"}.get(p, "solid")
                elif name == "Rounding":
                    st["style"]["rounding"] = self._number(val)
                elif name == "FillForegnd" and val != "Themed":
                    st["style"]["fill"] = val
                elif name == "FillForegndTrans":
                    st["style"]["transparency"] = self._number(val)
                elif name == "Font":
                    st["text_style"]["font"] = security.clean_line(val, 100)
                elif name == "Size":
                    st["text_style"]["size"] = self._number(val)
                elif name == "Color":
                    st["text_style"]["color"] = val
                elif name == "Style":
                    bits = int(self._number(val))
                    st["text_style"].update(bold=bool(bits & 1), italic=bool(bits & 2),
                                            underline=bool(bits & 4))
                elif name == "HorzAlign":
                    st["text_style"]["halign"] = ("left", "center", "right")[min(max(int(self._number(val)), 0), 2)]
                elif name == "VerticalAlign":
                    st["text_style"]["valign"] = ("top", "middle", "bottom")[min(max(int(self._number(val)), 0), 2)]
        except (ValueError, TypeError):
            self.msg.setText(f"Valeur invalide pour {name} : seules des valeurs numériques "
                             "ou des couleurs #RRGGBB sont acceptées.")
            return
        # Validation stricte identique à celle des fichiers.
        st["style"] = clean_shape_style(st["style"], self.shape.style)
        st["style"]["themed"] = False
        st["text_style"] = clean_text_style(st["text_style"], self.shape.text_style)
        target = st

        def apply(it, s):
            s.update(target)
        self.scene.modify([self.shape], apply, "Modifier la ShapeSheet")
        self.accept()


# ------------------------------------------------------------------------ divers

SHORTCUTS = [
    ("Outils", [("Ctrl+1", "Outil Pointeur"), ("Ctrl+2", "Outil Texte"), ("Ctrl+3", "Outil Connecteur"),
                ("Ctrl+6", "Outil Ligne"), ("Ctrl+8", "Outil Rectangle"), ("Ctrl+9", "Outil Ellipse"),
                ("Échap", "Revenir au Pointeur / désélectionner")]),
    ("Édition", [("Ctrl+Z / Ctrl+Y", "Annuler / Rétablir"), ("Ctrl+X / C / V", "Couper / Copier / Coller"),
                 ("Ctrl+D", "Dupliquer"), ("Suppr", "Supprimer"), ("Ctrl+A", "Tout sélectionner"),
                 ("F2 ou saisie directe", "Modifier le texte de la forme"), ("Ctrl+F", "Rechercher"),
                 ("Flèches / Maj+Flèches", "Déplacer d'un pas de grille / d'un pixel")]),
    ("Organiser", [("Ctrl+Maj+F / Ctrl+Maj+B", "Premier plan / Arrière-plan"),
                   ("Ctrl+Maj+G / Ctrl+Maj+U", "Grouper / Dissocier"),
                   ("Ctrl+R / Ctrl+L", "Rotation droite / gauche"),
                   ("Ctrl+H / Ctrl+J", "Retourner horizontalement / verticalement")]),
    ("Texte", [("Ctrl+B / I / U", "Gras / Italique / Souligné"),
               ("Ctrl+Maj+L / C / R", "Aligner à gauche / centrer / à droite"),
               ("Ctrl+Maj+T / M / V", "Texte en haut / au milieu / en bas"),
               ("Ctrl+Maj+> / <", "Agrandir / réduire la police"), ("Ctrl+K", "Lien hypertexte")]),
    ("Affichage", [("Ctrl+molette", "Zoom"), ("Clic milieu ou Espace+glisser", "Se déplacer"),
                   ("Ctrl+Maj+W", "Ajuster la page à la fenêtre"), ("Ctrl+0", "Zoom 100 %"),
                   ("Ctrl+Pg.Suiv / Pg.Préc", "Page suivante / précédente"), ("F5", "Plein écran"),
                   ("Ctrl+F1", "Réduire le ruban")]),
    ("Fichier", [("Ctrl+N", "Nouveau"), ("Ctrl+O", "Ouvrir"), ("Ctrl+S", "Enregistrer"),
                 ("F12", "Enregistrer sous"), ("Ctrl+P", "Imprimer"), ("Ctrl+W", "Fermer")]),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Raccourcis clavier")
        self.resize(560, 620)
        lay = QVBoxLayout(self)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Touches", "Action"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for group, entries in SHORTCUTS:
            r = table.rowCount()
            table.insertRow(r)
            head = QTableWidgetItem(group)
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            table.setItem(r, 0, head)
            for keys, action in entries:
                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem(keys))
                table.setItem(r, 1, QTableWidgetItem(action))
        table.resizeColumnToContents(0)
        lay.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class RecoveryDialog(QDialog):
    def __init__(self, parent, files: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Récupération de documents")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lab = QLabel("LinXdiagram s'est fermé de façon inattendue. Les documents suivants ont été "
                     "enregistrés automatiquement. Cochez ceux à récupérer :")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.list = QListWidget()
        for f in files:
            it = QListWidgetItem(f"Récupération du {time.strftime('%d/%m/%Y à %H:%M', time.localtime(os.path.getmtime(f)))}")
            it.setData(Qt.ItemDataRole.UserRole, f)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(it)
        lay.addWidget(self.list)
        buttons = QDialogButtonBox()
        buttons.addButton("Récupérer", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Supprimer tout", QDialogButtonBox.ButtonRole.DestructiveRole).clicked.connect(
            self._discard)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)
        self.discard_all = False

    def _discard(self) -> None:
        self.discard_all = True
        self.reject()

    def selected(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out


class OptionsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Options de LinXdiagram")
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.recent = QCheckBox("Mémoriser les documents récents")
        self.recent.setChecked(settings.value("privacy/remember_recent", True, type=bool))
        form.addRow("Confidentialité", self.recent)
        self.autosave = QSpinBox()
        self.autosave.setRange(0, 60)
        self.autosave.setSuffix(" min")
        self.autosave.setSpecialValueText("Désactivée")
        self.autosave.setValue(settings.value("autosave/minutes", 3, type=int))
        form.addRow("Récupération automatique", self.autosave)
        self.theme = QComboBox()
        for key, label in (("light", "En couleur"), ("dark", "Noir"),
                           ("system", "Utiliser le paramètre système")):
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.value("ui/theme", "light"))))
        self.native = QCheckBox("Utiliser la barre de titre du système")
        self.native.setChecked(settings.value("ui/native_titlebar", compat.IS_MACOS, type=bool))
        form.addRow("Fenêtre", self.native)
        self.user = QLineEdit(settings.value("user/name", ""))
        self.user.setPlaceholderText("Nom affiché dans les commentaires")
        form.addRow("Nom d'utilisateur", self.user)
        form.addRow("Thème de l'interface", self.theme)
        self.delete_conn = QCheckBox("Supprimer les connecteurs avec les formes reliées")
        self.delete_conn.setChecked(True)
        self.delete_conn.setEnabled(False)
        form.addRow("Édition", self.delete_conn)
        note = QLabel("Le thème et la barre de titre s'appliquent au prochain démarrage.")
        note.setObjectName("hint")
        form.addRow("", note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self) -> None:
        self.settings.setValue("privacy/remember_recent", self.recent.isChecked())
        self.settings.setValue("autosave/minutes", self.autosave.value())
        self.settings.setValue("ui/theme", self.theme.currentData())
        self.settings.setValue("ui/native_titlebar", self.native.isChecked())
        self.settings.setValue("user/name", security.clean_line(self.user.text(), 100))
        if not self.recent.isChecked():
            self.settings.setValue("recent/files", [])


# ------------------------------------------------------------------------ dialogues Visio

def _buttons(dlg, ok_text: str = "OK") -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    b.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    b.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


class ReorderPagesDialog(QDialog):
    """« Réorganiser les pages » de Visio : glisser les pages ou utiliser Monter / Descendre."""

    def __init__(self, parent, pages):
        super().__init__(parent)
        self.setWindowTitle("Réorganiser les pages")
        self._pages = list(pages)
        lay = QHBoxLayout(self)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for i, p in enumerate(self._pages):
            it = QListWidgetItem(p.page_name)
            it.setData(Qt.ItemDataRole.UserRole, i)
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        lay.addWidget(self.list)
        side = QVBoxLayout()
        for text, step in (("Monter", -1), ("Descendre", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, d=step: self.move(d))
            side.addWidget(b)
        side.addStretch(1)
        side.addWidget(_buttons(self))
        lay.addLayout(side)

    def move(self, step: int) -> None:
        row = self.list.currentRow()
        dst = row + step
        if row < 0 or not 0 <= dst < self.list.count():
            return
        it = self.list.takeItem(row)
        self.list.insertItem(dst, it)
        self.list.setCurrentRow(dst)

    def order(self) -> list:
        return [self._pages[self.list.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.list.count())]


class ZoomDialog(QDialog):
    PRESETS = ((4.0, "400 %"), (2.0, "200 %"), (1.5, "150 %"), (1.0, "100 %"), (0.75, "75 %"),
               (0.5, "50 %"), ("page", "Page entière"), ("width", "Largeur de page"))

    def __init__(self, parent, current: float):
        super().__init__(parent)
        from PyQt6.QtWidgets import QButtonGroup, QRadioButton
        self.setWindowTitle("Zoom")
        lay = QVBoxLayout(self)
        self.group = QButtonGroup(self)
        self.choice = None
        for i, (val, label) in enumerate(self.PRESETS):
            rb = QRadioButton(label)
            self.group.addButton(rb, i)
            lay.addWidget(rb)
            if isinstance(val, float) and abs(val - current) < 1e-3:
                rb.setChecked(True)
        row = QFormLayout()
        self.percent = QSpinBox()
        self.percent.setRange(10, 800)
        self.percent.setSuffix(" %")
        self.percent.setValue(round(current * 100))
        row.addRow("Pourcentage :", self.percent)
        lay.addLayout(row)
        lay.addWidget(_buttons(self))
        self.group.idClicked.connect(self._preset)

    def _preset(self, i: int) -> None:
        val = self.PRESETS[i][0]
        if isinstance(val, float):
            self.percent.setValue(round(val * 100))

    def result_value(self):
        i = self.group.checkedId()
        if i >= 0 and not isinstance(self.PRESETS[i][0], float):
            return self.PRESETS[i][0]
        return self.percent.value() / 100.0


class FindReplaceDialog(QDialog):
    """Rechercher / Remplacer dans le texte des formes (page ou document)."""

    def __init__(self, parent, window, replace: bool = False):
        super().__init__(parent)
        self.win = window
        self.setWindowTitle("Rechercher et remplacer" if replace else "Rechercher")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.find = QLineEdit()
        form.addRow("Rechercher :", self.find)
        self.repl = QLineEdit()
        if replace:
            form.addRow("Remplacer par :", self.repl)
        self.case = QCheckBox("Respecter la casse")
        self.all_pages = QCheckBox("Toutes les pages")
        form.addRow("", self.case)
        form.addRow("", self.all_pages)
        self.msg = QLabel("")
        form.addRow("", self.msg)
        bb = QDialogButtonBox()
        b_find = bb.addButton("Rechercher", QDialogButtonBox.ButtonRole.ActionRole)
        b_find.clicked.connect(self._find)
        if replace:
            b_all = bb.addButton("Remplacer tout", QDialogButtonBox.ButtonRole.ActionRole)
            b_all.clicked.connect(self._replace_all)
        bb.addButton("Fermer", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        form.addRow(bb)

    def _pages(self):
        return self.win.doc.pages if self.all_pages.isChecked() else [self.win.scene()]

    def _match(self, text: str, q: str) -> bool:
        return (q in text) if self.case.isChecked() else (q.lower() in text.lower())

    def _find(self) -> None:
        q = self.find.text()
        if not q:
            return
        total = 0
        for sc in self._pages():
            hits = [it for it in sc.all_items() if self._match(it.text, q)]
            if hits and sc is self.win.scene():
                sc.select_items(hits)
            total += len(hits)
        self.msg.setText(f"{total} forme(s) trouvée(s).")

    def _replace_all(self) -> None:
        import re as _re
        q, r = self.find.text(), security.clean_text(self.repl.text(), 2000)
        if not q:
            return
        flags = 0 if self.case.isChecked() else _re.IGNORECASE
        pattern = _re.compile(_re.escape(q), flags)
        total = 0
        self.win.doc.undo_stack.beginMacro("Remplacer tout")
        for sc in self._pages():
            items = [it for it in sc.all_items() if pattern.search(it.text)]
            total += len(items)

            def rep(it, st):
                st["text"] = pattern.sub(lambda _m: r, st["text"])
            if items:
                sc.modify(items, rep, "Remplacer")
        self.win.doc.undo_stack.endMacro()
        self.msg.setText(f"{total} forme(s) modifiée(s).")


class LayersDialog(QDialog):
    """Propriétés des calques : nom, visible, imprimable, verrouillé."""

    COLS = ("Nom", "Visible", "Imprimable", "Verrouillé", "Objets")

    def __init__(self, parent, scene):
        super().__init__(parent)
        self.scene = scene
        self.setWindowTitle("Propriétés des calques")
        self.resize(520, 360)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        counts: dict[str, int] = {}
        for it in scene.all_items():
            counts[it.layer] = counts.get(it.layer, 0) + 1
        for layer in scene.layers:
            self._add_row(layer, counts.get(layer["name"], 0))
        row = QHBoxLayout()
        add = QPushButton("Nouveau…")
        add.clicked.connect(self._new)
        rem = QPushButton("Supprimer")
        rem.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_buttons(self))

    def _add_row(self, layer: dict, count: int = 0) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(layer["name"]))
        for c, key in ((1, "visible"), (2, "printable"), (3, "locked")):
            it = QTableWidgetItem()
            it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            it.setCheckState(Qt.CheckState.Checked if layer[key] else Qt.CheckState.Unchecked)
            self.table.setItem(r, c, it)
        n = QTableWidgetItem(str(count))
        n.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(r, 4, n)

    def _new(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Nouveau calque", "Nom du calque :")
        name = security.clean_line(name, 64)
        if ok and name:
            self._add_row({"name": name, "visible": True, "printable": True, "locked": False})

    def layers(self) -> list[dict]:
        out, seen = [], set()
        for r in range(self.table.rowCount()):
            name = security.clean_line(self.table.item(r, 0).text(), 64)
            if not name or name in seen:
                continue
            seen.add(name)
            out.append({"name": name,
                        "visible": self.table.item(r, 1).checkState() == Qt.CheckState.Checked,
                        "printable": self.table.item(r, 2).checkState() == Qt.CheckState.Checked,
                        "locked": self.table.item(r, 3).checkState() == Qt.CheckState.Checked})
        return out


class PageSetupDialog(QDialog):
    """Mise en page : format, orientation, dimensions, arrière-plan."""

    def __init__(self, parent, scene):
        super().__init__(parent)
        from .units import PAGE_SIZES, PX_PER_MM
        self._px = PX_PER_MM
        self._sizes = PAGE_SIZES
        self.setWindowTitle("Mise en page")
        form = QFormLayout(self)
        self.name = QLineEdit(scene.page_name)
        form.addRow("Nom de la page :", self.name)
        self.fmt = QComboBox()
        for n, (w, h) in PAGE_SIZES.items():
            self.fmt.addItem(f"{n} ({w:g} × {h:g} mm)", n)
        self.fmt.addItem("Personnalisé", "")
        form.addRow("Format :", self.fmt)
        self.orient = QComboBox()
        self.orient.addItems(["Portrait", "Paysage"])
        self.orient.setCurrentIndex(1 if scene.page_w > scene.page_h else 0)
        form.addRow("Orientation :", self.orient)
        from PyQt6.QtWidgets import QDoubleSpinBox
        self.w = QDoubleSpinBox()
        self.h = QDoubleSpinBox()
        for s, v in ((self.w, scene.page_w), (self.h, scene.page_h)):
            s.setRange(20, 10000)
            s.setSuffix(" mm")
            s.setDecimals(1)
            s.setValue(v / PX_PER_MM)
        form.addRow("Largeur :", self.w)
        form.addRow("Hauteur :", self.h)
        self.auto = QCheckBox("Agrandir automatiquement la page")
        self.auto.setChecked(scene.auto_size)
        form.addRow("", self.auto)
        self.bg = scene.page_bg
        self.fmt.setCurrentIndex(self.fmt.count() - 1)
        for i in range(self.fmt.count() - 1):
            w, h = PAGE_SIZES[self.fmt.itemData(i)]
            if {round(w), round(h)} == {round(self.w.value()), round(self.h.value())}:
                self.fmt.setCurrentIndex(i)
        self.fmt.activated.connect(self._fmt)
        self.orient.activated.connect(self._orient)
        form.addRow(_buttons(self))

    def _fmt(self, i: int) -> None:
        n = self.fmt.itemData(i)
        if n:
            w, h = self._sizes[n]
            if self.orient.currentIndex() == 1:
                w, h = h, w
            self.w.setValue(w)
            self.h.setValue(h)

    def _orient(self, i: int) -> None:
        w, h = self.w.value(), self.h.value()
        if (w > h) != (i == 1):
            self.w.setValue(h)
            self.h.setValue(w)

    def props(self, base: dict) -> dict:
        return dict(base, name=security.clean_line(self.name.text(), 100) or base["name"],
                    width=self.w.value() * self._px, height=self.h.value() * self._px,
                    auto_size=self.auto.isChecked())


class DataImportDialog(QDialog):
    """« Créer à partir de données » : organigramme ou diagramme de flux depuis un CSV."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Créer un diagramme à partir de données")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Choisissez le type de diagramme puis un fichier CSV (séparateur virgule, point-virgule "
            "ou tabulation, première ligne = en-têtes).\n\n"
            "• Organigramme : colonnes ID, Nom, Fonction (facultatif), Responsable (ID du supérieur).\n"
            "• Diagramme de flux : colonnes ID, Description, Type (Processus, Décision, Début, Fin, "
            "Données, Document), Suivant (ID des étapes suivantes, séparés par « ; »), "
            "Libellé (facultatif, texte du connecteur), Fonction (facultatif : crée un diagramme "
            "interfonctionnel avec un couloir par fonction).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("Organigramme hiérarchique", "org")
        self.kind.addItem("Diagramme de flux", "flow")
        form.addRow("Type de diagramme :", self.kind)
        self.new_page = QCheckBox("Créer une nouvelle page")
        self.new_page.setChecked(True)
        form.addRow("", self.new_page)
        lay.addLayout(form)
        lay.addWidget(_buttons(self, "Choisir le fichier…"))


class DataGraphicDialog(QDialog):
    """Configure un graphique de données et ses couleurs de statut locales."""

    DEFAULT_COLORS = (("Terminé", "#e7f4e4"), ("En cours", "#fff4ce"), ("Bloqué", "#fde7e9"))

    def __init__(self, parent, fields: list[str], config: dict | None = None):
        super().__init__(parent)
        config = config or {}
        self.setWindowTitle("Configurer un graphique de données")
        self.resize(520, 430)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.field = QComboBox()
        for value in sorted(fields, key=str.casefold):
            self.field.addItem(value, value)
        current_field = config.get("field", "")
        index = self.field.findData(current_field)
        if index >= 0:
            self.field.setCurrentIndex(index)
        form.addRow("Propriété à afficher :", self.field)
        self.display = QComboBox()
        for label, value in (("Étiquette et valeur", "label_value"), ("Valeur seule", "value"),
                             ("Pastille de statut colorée", "status")):
            self.display.addItem(label, value)
        index = self.display.findData(config.get("display", "label_value"))
        if index >= 0:
            self.display.setCurrentIndex(index)
        form.addRow("Présentation :", self.display)
        lay.addLayout(form)
        self.rules_hint = QLabel("Les règles personnalisées ignorent la casse et les accents. "
                                 "Les autres valeurs gardent les couleurs de statut automatiques.")
        self.rules_hint.setWordWrap(True)
        lay.addWidget(self.rules_hint)
        self.rules = QTableWidget(0, 2)
        self.rules.setHorizontalHeaderLabels(["Valeur du statut", "Couleur de fond"])
        self.rules.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.rules.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.rules.verticalHeader().setVisible(False)
        self.rules.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rules.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.rules.cellDoubleClicked.connect(self._choose_color)
        lay.addWidget(self.rules, 1)
        row = QHBoxLayout()
        self.add_rule = QPushButton("Ajouter une règle")
        self.remove_rule = QPushButton("Supprimer")
        self.add_rule.clicked.connect(lambda _checked=False: self._add_rule())
        self.remove_rule.clicked.connect(lambda _checked=False: self._remove_rules())
        row.addWidget(self.add_rule)
        row.addWidget(self.remove_rule)
        row.addStretch(1)
        lay.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        rules = config.get("status_colors")
        if isinstance(rules, list):
            for rule in rules[:50]:
                if isinstance(rule, dict):
                    self._add_rule(rule.get("value", ""), rule.get("color", "#fff4ce"), edit=False)
        else:
            for value, color in self.DEFAULT_COLORS:
                self._add_rule(value, color, edit=False)
        self.display.currentIndexChanged.connect(self._refresh_rules)
        self._refresh_rules()

    def _add_rule(self, value: str = "", color: str = "#fff4ce", edit: bool = True) -> None:
        if self.rules.rowCount() >= 50:
            return
        row = self.rules.rowCount()
        self.rules.insertRow(row)
        value_item = QTableWidgetItem(str(value)[:200])
        value_item.setToolTip("Valeur exacte après normalisation de la casse et des accents")
        self.rules.setItem(row, 0, value_item)
        self._set_color(row, color)
        self.rules.setCurrentCell(row, 0)
        if edit:
            self.rules.editItem(value_item)
        self._refresh_rules()

    def _set_color(self, row: int, color: str) -> None:
        parsed = QColor(color)
        if not parsed.isValid():
            parsed = QColor("#fff4ce")
        item = QTableWidgetItem(parsed.name())
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setBackground(parsed)
        item.setForeground(QColor("#27313d" if parsed.lightness() >= 145 else "#ffffff"))
        item.setToolTip("Double-cliquez pour choisir une couleur")
        self.rules.setItem(row, 1, item)

    def _choose_color(self, row: int, column: int) -> None:
        if column != 1:
            return
        current = QColor(self.rules.item(row, column).text())
        color = QColorDialog.getColor(current, self, "Couleur de statut")
        if color.isValid():
            self._set_color(row, color.name())

    def _remove_rules(self) -> None:
        rows = sorted({index.row() for index in self.rules.selectionModel().selectedRows()}, reverse=True)
        if not rows and self.rules.currentRow() >= 0:
            rows = [self.rules.currentRow()]
        for row in rows:
            self.rules.removeRow(row)
        self._refresh_rules()

    def _refresh_rules(self, *_args) -> None:
        enabled = self.display.currentData() == "status"
        self.rules_hint.setEnabled(enabled)
        self.rules.setEnabled(enabled)
        self.add_rule.setEnabled(enabled and self.rules.rowCount() < 50)
        self.remove_rule.setEnabled(enabled and self.rules.rowCount() > 0)

    def config(self) -> dict:
        result = {"field": str(self.field.currentData()), "display": str(self.display.currentData())}
        if result["display"] == "status":
            rules, seen = [], set()
            for row in range(self.rules.rowCount()):
                value = security.clean_line(self.rules.item(row, 0).text(), 200)
                color = self.rules.item(row, 1).text()
                key = normalize_status_key(value)
                if not key or key in seen or not QColor(color).isValid():
                    continue
                seen.add(key)
                rules.append({"value": value, "color": QColor(color).name()})
            if rules:
                result["status_colors"] = rules
        return result


class DataLinkDialog(QDialog):
    """Associe les colonnes d'un CSV local aux formes via une clé stable."""

    def __init__(self, headers: list[str], rows: list[list[str]], shapes: list, parent=None):
        super().__init__(parent)
        self.headers = headers
        self.rows = rows
        self.shapes = shapes
        self.setWindowTitle("Lier les formes à un fichier CSV")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        intro = QLabel("Choisissez la colonne du CSV à comparer au texte d'une forme ou à une propriété "
                       "existante. Les colonnes sont ajoutées aux données des formes ; vous pouvez lier "
                       "plusieurs fichiers locaux au même dessin. Si un nom existe déjà, le nom du fichier "
                       "est ajouté à la colonne pour éviter d'écraser les autres données. Les chemins locaux "
                       "sont conservés dans le dessin .lxd pour actualiser les sources à la demande.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.source_key = QComboBox()
        for header in headers:
            self.source_key.addItem(header, header)
        for i, header in enumerate(headers):
            if header.casefold() in ("id", "identifiant", "code"):
                self.source_key.setCurrentIndex(i)
                break
        form.addRow("Colonne clé du CSV :", self.source_key)
        self.shape_key = QComboBox()
        self.shape_key.addItem("Texte de la forme", "__text__")
        keys = sorted({key for shape in shapes for key in shape.data}, key=str.casefold)
        for key in keys:
            self.shape_key.addItem(f"Donnée : {key}", key)
        form.addRow("Comparer avec :", self.shape_key)
        lay.addLayout(form)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        lay.addWidget(self.preview)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                        QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.source_key.currentIndexChanged.connect(self._update_preview)
        self.shape_key.currentIndexChanged.connect(self._update_preview)
        self._update_preview()

    def mapping(self) -> tuple[str, str]:
        return str(self.source_key.currentData()), str(self.shape_key.currentData())

    def _update_preview(self) -> None:
        source_key, shape_key = self.mapping()
        try:
            source_index = self.headers.index(source_key)
        except ValueError:
            source_index = -1
        values = [row[source_index].strip() for row in self.rows
                  if source_index >= 0 and source_index < len(row) and row[source_index].strip()]
        duplicates = len(values) - len(set(values))
        source_values = set(values)
        def shape_value(shape):
            return shape.text.strip() if shape_key == "__text__" else str(shape.data.get(shape_key, "")).strip()
        matched = sum(1 for shape in self.shapes if shape_value(shape) in source_values and shape_value(shape))
        if duplicates:
            message = f"La colonne contient {duplicates} clé(s) en double. Choisissez une colonne unique."
            valid = False
        elif not matched:
            message = "Aucune forme ne correspond. Vérifiez la clé ou modifiez les données des formes."
            valid = False
        else:
            message = f"Aperçu : {matched} forme(s) correspondent à {len(source_values)} ligne(s) du CSV."
            valid = True
        self.preview.setText(message)
        self.preview.setStyleSheet("color: #b42318;" if not valid else "color: #16803c;")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)


class FieldDialog(QDialog):
    """Insertion > Champ : choix d'un champ avec aperçu de sa valeur actuelle."""

    def __init__(self, parent, scene):
        super().__init__(parent)
        from . import fields
        self.setWindowTitle("Champ")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Catégorie de champ et valeur actuelle :"))
        self.list = QListWidget()
        vals = fields.values(scene)
        for key, label in fields.FIELDS.items():
            value = vals.get(key) or "(vide)"
            it = QListWidgetItem(f"{label}  —  {value}")
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _it: self.accept())
        lay.addWidget(self.list)
        hint = QLabel("Le champ se met à jour automatiquement. En modification de texte, il apparaît sous "
                      "la forme {{nom}}.")
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        lay.addWidget(hint)
        lay.addWidget(_buttons(self))

    def field(self) -> str:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else "date"


class SpellDialog(QDialog):
    """Révision > Orthographe (F7) : parcourt les textes du document, comme dans Visio."""

    def __init__(self, window, checker, targets: list):
        super().__init__(window)
        import re
        self._re = re
        self.win = window
        self.checker = checker
        self.targets = targets          # [(scène, objet)]
        self.index = 0
        self.offset = 0
        self.current = None             # (scène, objet, début, fin, mot)
        self.changes = 0
        self.setWindowTitle("Orthographe")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        self.where = QLabel()
        self.where.setObjectName("Hint")
        lay.addWidget(self.where)
        lay.addWidget(QLabel("Absent du dictionnaire :"))
        self.context = QLabel()
        self.context.setWordWrap(True)
        self.context.setTextFormat(Qt.TextFormat.RichText)
        self.context.setStyleSheet("padding: 6px; border: 1px solid palette(mid); border-radius: 4px;")
        lay.addWidget(self.context)
        row = QFormLayout()
        self.replacement = QLineEdit()
        row.addRow("Remplacer par :", self.replacement)
        lay.addLayout(row)
        lay.addWidget(QLabel("Suggestions :"))
        self.suggestions = QListWidget()
        self.suggestions.setMaximumHeight(140)
        self.suggestions.currentTextChanged.connect(lambda t: t and self.replacement.setText(t))
        self.suggestions.itemDoubleClicked.connect(lambda _it: self._change())
        lay.addWidget(self.suggestions)
        buttons = QHBoxLayout()
        for text, slot in (("Ignorer", self._ignore), ("Ignorer tout", self._ignore_all),
                           ("Ajouter au dictionnaire", self._add), ("Modifier", self._change),
                           ("Modifier tout", self._change_all)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
            if text == "Modifier":
                b.setDefault(True)
        lay.addLayout(buttons)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.button(QDialogButtonBox.StandardButton.Close).setText("Fermer")
        lay.addWidget(close)
        lang = {"fr": "Français", "en": "Anglais"}.get(checker.lang[:2], checker.lang)
        self.setWindowTitle(f"Orthographe — {lang}")

    def start(self) -> bool:
        """Cherche la première faute ; False si le document n'en contient aucune."""
        return self._next()

    def _next(self) -> bool:
        while self.index < len(self.targets):
            scene, item = self.targets[self.index]
            if item.scene() is scene:
                for start, end, word in self.checker.errors(item.text):
                    if start >= self.offset:
                        self._show(scene, item, start, end, word)
                        return True
            self.index += 1
            self.offset = 0
        self.current = None
        return False

    def _show(self, scene, item, start, end, word) -> None:
        self.current = (scene, item, start, end, word)
        esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
        text = item.text
        a, b = max(0, start - 60), min(len(text), end + 60)
        self.context.setText(("…" if a else "") + esc(text[a:start]) + "<b><u>" + esc(word) + "</u></b>"
                             + esc(text[end:b]) + ("…" if b < len(text) else ""))
        self.where.setText(f"Page « {scene.page_name} »")
        self.suggestions.clear()
        sugg = self.checker.suggest(word)
        self.suggestions.addItems(sugg)
        self.replacement.setText(sugg[0] if sugg else word)
        if sugg:
            self.suggestions.setCurrentRow(0)
        self.win.show_page(scene)
        scene.select_items([item])
        self.win.view.ensureVisible(item.sceneBoundingRect(), 40, 40)

    def _advance(self) -> None:
        if not self._next():
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Orthographe", "La vérification orthographique est terminée.")
            self.accept()

    def _ignore(self) -> None:
        if self.current:
            self.offset = self.current[3]
        self._advance()

    def _ignore_all(self) -> None:
        if self.current:
            self.checker.ignore_all(self.current[4])
        self._advance()

    def _add(self) -> None:
        if self.current:
            self.checker.add_to_dictionary(self.current[4])
        self._advance()

    def _replace_in(self, scene, item, start, end, new) -> None:
        text = item.text[:start] + new + item.text[end:]
        scene.modify([item], lambda _it, st: st.update(text=text), "Orthographe")
        self.changes += 1

    def _change(self) -> None:
        if not self.current:
            return self._advance()
        scene, item, start, end, _word = self.current
        new = security.clean_line(self.replacement.text(), 200)
        self._replace_in(scene, item, start, end, new)
        self.offset = start + len(new)
        self._advance()

    def _change_all(self) -> None:
        if not self.current:
            return self._advance()
        word = self.current[4]
        new = security.clean_line(self.replacement.text(), 200)
        pattern = self._re.compile(r"(?<![\w’'-])" + self._re.escape(word) + r"(?![\w’'-])")
        for scene, item in self.targets[self.index:]:
            if item.scene() is scene and pattern.search(item.text):
                text = pattern.sub(new, item.text)
                scene.modify([item], lambda _it, st, t=text: st.update(text=t), "Orthographe")
                self.changes += 1
        self.checker.ignore_all(word)
        self._advance()
