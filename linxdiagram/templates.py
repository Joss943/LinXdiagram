"""Modèles de démarrage (écran « Nouveau »)."""

from __future__ import annotations

from . import fileformat, stencils, swimlanes
from .units import PAGE_SIZES, connector_style, connector_text_style, mm_to_px

# modèle -> (catégorie de formes à ouvrir, style de connecteur, paysage)
TEMPLATE_SETUP = {
    "blank": (stencils.BASIC, "orthogonal", False),
    "flow": (stencils.FLOW, "orthogonal", False),
    "bpmn": (stencils.BPMN, "orthogonal", True),
    "org": (stencils.ORG, "orthogonal", True),
    "network": (stencils.NET, "straight", True),
    "floorplan": (stencils.FLOORPLAN, "orthogonal", True),
    "circuit": (stencils.CIRCUIT, "straight", False),
    "uml": (stencils.UML, "straight", False),
    "sample": (stencils.FLOW, "orthogonal", False),
    "cff": (stencils.CFF, "orthogonal", True),
}


def cff_states(orientation: str, left_mm: float, top_mm: float, lanes: list[str], title: str,
               length_mm: float = 230, lane_mm: float = 35) -> list[dict]:
    """États d'une structure interfonctionnelle (cadre + couloirs nommés)."""
    out = []
    items = swimlanes.new_structure(orientation, mm_to_px(left_mm), mm_to_px(top_mm), len(lanes),
                                    mm_to_px(length_mm), mm_to_px(lane_mm))
    names = iter(lanes)
    for n, (role, type_id, b) in enumerate(items):
        st = _shape(f"cff{n}", type_id, 0, 0, title if role == "frame" else next(names), 0)
        st.update(x=b.cx, y=b.cy, w=b.w, h=b.h,
                  z=swimlanes.Z_FRAME if role == "frame" else swimlanes.Z_LANE + n)
        out.append(st)
    return out


def _shape(sid, type_id, x_mm, y_mm, text, z):
    style, ts = fileformat.default_shape_styles(type_id, "office")
    sdef = stencils.get(type_id)
    return {"id": sid, "type": type_id, "x": mm_to_px(x_mm), "y": mm_to_px(y_mm),
            "w": mm_to_px(sdef.size_mm[0] + 10), "h": mm_to_px(sdef.size_mm[1] + 2),
            "rotation": 0.0, "flip_h": False, "flip_v": False, "z": float(z), "text": text,
            "style": style, "text_style": ts, "data": {}, "link": "", "group": ""}


def _conn(cid, a, b, z, text=""):
    return {"id": cid, "kind": "connector", "src": {"shape": a, "port": -1, "x": 0, "y": 0},
            "dst": {"shape": b, "port": -1, "x": 0, "y": 0}, "z": float(z), "text": text,
            "style": connector_style("office", "orthogonal"),
            "text_style": connector_text_style("office"), "data": {}}


def build(template: str) -> dict:
    category, route, landscape = TEMPLATE_SETUP.get(template, TEMPLATE_SETUP["blank"])
    page = fileformat.default_page("Page-1")
    if landscape:
        w, h = PAGE_SIZES["A4"]
        page["width"], page["height"] = mm_to_px(h), mm_to_px(w)
    doc = {"settings": {"route": route, "theme": "office"}, "properties": {}, "pages": [page]}
    if template == "cff":
        page["shapes"] = cff_states("h", 15, 15, ["Fonction", "Fonction", "Fonction"],
                                    "Titre du diagramme", length_mm=265, lane_mm=48)
    if template == "org":
        shapes = [("a", "org.executive", 105, 30, "Direction"),
                  ("b", "org.manager", 55, 75, "Ventes"),
                  ("c", "org.manager", 155, 75, "Production"),
                  ("d", "org.employee", 30, 120, ""), ("e", "org.employee", 80, 120, ""),
                  ("f", "org.employee", 155, 120, "")]
        page["shapes"] = [_shape(i, t, x, y, text, n) for n, (i, t, x, y, text) in enumerate(shapes)]
        links = [("a", "b"), ("a", "c"), ("b", "d"), ("b", "e"), ("c", "f")]
        page["connectors"] = [_conn(f"oc{n}", a, b, 100 + n) for n, (a, b) in enumerate(links)]
    if template == "network":
        shapes = [
            ("client", "net.user", 28, 60, "Utilisateur distant"),
            ("vpn", "net.vpn", 72, 60, "VPN"),
            ("internet", "net.cloud", 174, 25, "Internet"),
            ("firewall", "net.firewall", 174, 65, "Pare-feu"),
            ("balancer", "net.load_balancer", 174, 101, "Équilibreur"),
            ("app1", "net.vm", 118, 137, "Application 1"),
            ("app2", "net.vm", 174, 137, "Application 2"),
            ("db", "net.database", 233, 137, "Données"),
            ("storage", "net.storage", 233, 178, "Stockage"),
        ]
        page["shapes"] = [_shape(i, t, x, y, text, n) for n, (i, t, x, y, text) in enumerate(shapes)]
        boundary = _shape("subnet", "net.subnet", 174, 155, "Réseau applicatif", -10)
        boundary.update(w=mm_to_px(228), h=mm_to_px(104))
        page["shapes"].insert(0, boundary)
        links = [("client", "vpn"), ("vpn", "firewall"), ("internet", "firewall"),
                 ("firewall", "balancer"), ("balancer", "app1"), ("balancer", "app2"),
                 ("app1", "db"), ("app2", "db"), ("db", "storage")]
        page["connectors"] = [_conn(f"nc{n}", a, b, 100 + n) for n, (a, b) in enumerate(links)]
        for conn in page["connectors"]:
            conn["style"].update(route="straight", arrow_end="triangle", line="#356e9f")
        doc["properties"]["title"] = "Architecture réseau et serveurs"
    if template == "uml":
        shapes = [("a", "uml.class", 60, 55, "Client"), ("b", "uml.class", 150, 55, "Commande"),
                  ("c", "uml.class", 105, 135, "Produit")]
        page["shapes"] = [_shape(i, t, x, y, text, n) for n, (i, t, x, y, text) in enumerate(shapes)]
        links = [("a", "b"), ("b", "c")]
        page["connectors"] = [_conn(f"uc{n}", a, b, 100 + n) for n, (a, b) in enumerate(links)]
        for conn in page["connectors"]:
            conn["style"].update(route="straight", arrow_end="triangle")
    if template == "bpmn":
        shapes = [
            ("b1", "bpmn.start", 30, 105, "Début"),
            ("b2", "bpmn.task", 78, 105, "Recevoir la demande"),
            ("b3", "bpmn.gateway_xor", 137, 105, "Complète ?"),
            ("b4", "bpmn.task", 190, 70, "Analyser"),
            ("b5", "bpmn.task", 190, 140, "Demander les pièces"),
            ("b6", "bpmn.end", 250, 105, "Traitement terminé"),
        ]
        page["shapes"] = [_shape(i, t, x, y, text, n) for n, (i, t, x, y, text) in enumerate(shapes)]
        links = [("b1", "b2", ""), ("b2", "b3", ""), ("b3", "b4", "Oui"),
                 ("b3", "b5", "Non"), ("b4", "b6", ""), ("b5", "b2", "")]
        page["connectors"] = [_conn(f"bc{n}", a, b, 100 + n, text)
                              for n, (a, b, text) in enumerate(links)]
        for conn in page["connectors"]:
            conn["style"]["line"] = "#404040"
    if template == "floorplan":
        room = _shape("room", "floor.room", 148, 105, "Bureau", 0)
        room.update(w=mm_to_px(240), h=mm_to_px(160))
        objects = [("window", "floor.window", 145, 27, ""), ("door", "floor.door", 35, 165, ""),
                   ("desk", "floor.desk", 82, 70, "Poste de travail"),
                   ("chair", "floor.chair", 82, 104, ""), ("table", "floor.table", 180, 80, "Réunion"),
                   ("stairs", "floor.stairs", 230, 145, "")]
        page["shapes"] = [room] + [_shape(i, t, x, y, text, n + 1)
                                    for n, (i, t, x, y, text) in enumerate(objects)]
    if template == "circuit":
        components = [("battery", "circuit.battery", 35, 90, "Alimentation"),
                      ("resistor", "circuit.resistor", 85, 90, "R1"),
                      ("capacitor", "circuit.capacitor", 135, 90, "C1"),
                      ("lamp", "circuit.lamp", 190, 90, "L1"),
                      ("ground", "circuit.ground", 135, 145, "")]
        page["shapes"] = [_shape(i, t, x, y, text, n) for n, (i, t, x, y, text) in enumerate(components)]
        links = [("battery", "resistor"), ("resistor", "capacitor"), ("capacitor", "lamp"),
                 ("capacitor", "ground")]
        page["connectors"] = [_conn(f"cc{n}", a, b, 100 + n) for n, (a, b) in enumerate(links)]
        for conn in page["connectors"]:
            conn["style"]["arrow_end"] = "none"
            conn["style"]["line"] = "#202020"
    if template == "sample":
        doc["properties"]["title"] = "Traitement d'une commande"
        shapes = [
            ("title", "basic.title", 105, 22, "Traitement d'une commande"),
            ("s1", "flow.terminator", 105, 45, "Commande reçue"),
            ("s2", "flow.process", 105, 75, "Vérifier le stock"),
            ("s3", "flow.decision", 105, 110, "Article en stock ?"),
            ("s4", "flow.process", 105, 148, "Préparer le colis"),
            ("s5", "flow.process", 165, 110, "Commander au fournisseur"),
            ("s6", "flow.data", 45, 148, "Facture"),
            ("s7", "flow.process", 105, 183, "Expédier"),
            ("s8", "flow.terminator", 105, 215, "Commande livrée"),
            ("note", "basic.note", 165, 160, "Astuce : déplacez une forme,\nles connecteurs suivent."),
        ]
        page["shapes"] = [_shape(i, t, x, y, txt, n) for n, (i, t, x, y, txt) in enumerate(shapes)]
        page["shapes"][0]["w"] = mm_to_px(150)
        page["shapes"][-1]["w"] = mm_to_px(48)
        page["shapes"][-1]["h"] = mm_to_px(22)
        page["shapes"][-1]["text_style"]["size"] = 9.0
        links = [("s1", "s2", ""), ("s2", "s3", ""), ("s3", "s4", "Oui"), ("s3", "s5", "Non"),
                 ("s5", "s2", ""), ("s4", "s6", ""), ("s4", "s7", ""), ("s7", "s8", "")]
        page["connectors"] = [_conn(f"c{n}", a, b, 100 + n, t) for n, (a, b, t) in enumerate(links)]
        page["shapes"][6]["data"] = {"Montant": "149,90 €", "TVA": "20 %"}
    clean, _warnings = fileformat.validate_document(
        {"format": fileformat.FORMAT, "version": fileformat.VERSION, **doc})
    return clean


def category_for(template: str) -> str:
    return TEMPLATE_SETUP.get(template, TEMPLATE_SETUP["blank"])[0]


# ---------------------------------------------------------------------- vignettes

TEMPLATES = [
    ("blank", "Dessin vierge"),
    ("flow", "Diagramme de flux de base"),
    ("bpmn", "Diagramme de processus BPMN"),
    ("org", "Organigramme hiérarchique"),
    ("network", "Architecture réseau et serveurs"),
    ("floorplan", "Plan de bureau"),
    ("circuit", "Schéma électrique"),
    ("cff", "Diagramme de flux interfonctionnel"),
    ("uml", "Diagramme de classes UML"),
    ("sample", "Exemple : traitement de commande"),
]


def preview(template: str) -> dict:
    """Petit diagramme d'illustration pour la vignette du modèle (comme dans Visio)."""
    if template in ("sample", "bpmn", "floorplan", "circuit", "org", "network", "uml"):
        return build(template)
    page = fileformat.default_page("Aperçu")
    if template == "cff":
        page["shapes"] = cff_states("h", 10, 10, ["Client", "Ventes", "Logistique"], "Commande",
                                    length_mm=180, lane_mm=32)
        for n, (sid, t, x, y, txt) in enumerate((("a", "flow.terminator", 50, 36, ""),
                                                 ("b", "flow.process", 90, 68, ""),
                                                 ("c", "flow.decision", 130, 68, ""),
                                                 ("d", "flow.process", 165, 100, ""))):
            st = _shape(sid, t, x, y, txt, 10 + n)
            st["w"], st["h"] = mm_to_px(26), mm_to_px(16)
            page["shapes"].append(st)
        page["connectors"] = [_conn(f"c{n}", a, b, 100 + n) for n, (a, b) in
                              enumerate((("a", "b"), ("b", "c"), ("c", "d")))]
        doc, _w = fileformat.validate_document({"format": fileformat.FORMAT, "version": fileformat.VERSION,
                                                 "settings": {}, "properties": {}, "pages": [page]})
        return doc
    shapes, links = [], []
    if template == "flow":
        shapes = [("a", "flow.terminator", 60, 30, "Début"), ("b", "flow.process", 60, 70, "Étape"),
                  ("c", "flow.decision", 60, 115, "Choix ?"), ("d", "flow.process", 140, 115, "Action"),
                  ("e", "flow.terminator", 60, 160, "Fin")]
        links = [("a", "b"), ("b", "c"), ("c", "d"), ("c", "e")]
    for n, (sid, t, x, y, txt) in enumerate(shapes):
        page["shapes"].append(_shape(sid, t, x, y, txt, n))
    for n, (a, b) in enumerate(links):
        c = _conn(f"c{n}", a, b, 100 + n)
        if template in ("network", "uml"):
            c["style"]["route"] = "straight"
            c["style"]["arrow_end"] = "none" if template == "network" else "triangle"
        page["connectors"].append(c)
    doc, _w = fileformat.validate_document({"format": fileformat.FORMAT, "version": fileformat.VERSION,
                                             "settings": {}, "properties": {}, "pages": [page]})
    return doc


def thumbnail(template: str, w: int = 176, h: int = 132):
    """Rendu de la vignette du modèle."""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
    from .document import Document
    from .export import exporting
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if template != "blank":
        doc = Document(preview(template))
        sc = doc.pages[0]
        src = sc.drawing_rect().adjusted(-12, -12, 12, 12)
        with exporting(sc):
            sc.render(p, QRectF(6, 6, w - 12, h - 12), src, Qt.AspectRatioMode.KeepAspectRatio)
    p.setPen(QPen(QColor("#d2d0ce"), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
    p.end()
    return pm
