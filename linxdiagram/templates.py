"""Catalogue hors ligne de types de diagrammes et préparation de pages vierges.

Chaque entrée règle la palette de formes, le routage des connecteurs et
l'orientation de la page. Aucun modèle ne place d'exemple sur le dessin.
"""

from __future__ import annotations

from functools import lru_cache

from . import fileformat, stencils
from .units import PAGE_SIZES, mm_to_px

# Catégorie Visio de l'écran Nouveau, gabarit ouvert dans le volet Formes,
# mode de connexion et orientation. Les dessins créés restent vides.
TEMPLATE_CATEGORIES = (
    "Tous les diagrammes", "Général", "Processus", "Entreprise", "Réseau",
    "Plans et bâtiments", "Logiciel et données", "Calendrier", "Ingénierie",
)

# key, titre, catégorie, palette, routage, paysage, description, mots-clés
_CATALOG = (
    ("blank", "Dessin vierge", "Général", stencils.BASIC, "orthogonal", False,
     "Page vierge et formes générales.", "vide commencer formes"),

    ("flow", "Diagramme de flux", "Processus", stencils.FLOW, "orthogonal", False,
     "Formes de processus, décisions, données et connecteurs.", "flowchart organigramme processus workflow"),
    ("cff", "Diagramme interfonctionnel", "Processus", stencils.CFF, "orthogonal", True,
     "Gabarits de couloirs et de phases interfonctionnels.", "couloir swimlane fonction phase"),
    ("bpmn", "Diagramme BPMN", "Processus", stencils.BPMN, "orthogonal", True,
     "Événements, tâches et passerelles BPMN.", "bpmn processus métier"),
    ("workflow", "Flux de travail", "Processus", stencils.FLOW, "orthogonal", True,
     "Étapes et décisions d’un flux de travail.", "workflow activité procédure"),
    ("process_flow", "Flux de processus", "Processus", stencils.FLOW, "orthogonal", True,
     "Formes de processus et de matières.", "processus fabrication production"),
    ("data_flow", "Flux de données", "Processus", stencils.FLOW, "orthogonal", True,
     "Sources, transformations et destinations de données.", "données dfd informatique"),
    ("value_stream", "Cartographie de la chaîne de valeur", "Processus", stencils.FLOW, "orthogonal", True,
     "Éléments de flux et d’analyse de valeur.", "lean vsm valeur stream"),
    ("six_sigma", "Diagramme Six Sigma", "Processus", stencils.FLOW, "orthogonal", True,
     "Étapes DMAIC et outils de processus.", "dmaic amélioration qualité"),
    ("idef0", "Diagramme IDEF0", "Processus", stencils.FLOW, "orthogonal", True,
     "Fonctions, entrées, contrôles, sorties et mécanismes.", "idef0 fonction"),
    ("idef1", "Modèle IDEF1X", "Processus", stencils.UML, "orthogonal", True,
     "Gabarits pour modèles d’information IDEF1X.", "idef1x données"),
    ("sdl", "Diagramme SDL", "Processus", stencils.FLOW, "orthogonal", True,
     "Symboles de spécification et description SDL.", "sdl système description"),
    ("fault_tree", "Arbre de défaillances", "Processus", stencils.FLOW, "orthogonal", True,
     "Éléments logiques pour l’analyse des défaillances.", "fta risque fiabilité"),

    ("org", "Organigramme", "Entreprise", stencils.ORG, "orthogonal", True,
     "Gabarits hiérarchiques pour équipes et organisations.", "organisation hiérarchie équipe"),
    ("brainstorming", "Brainstorming", "Entreprise", stencils.BASIC, "straight", False,
     "Formes libres pour organiser des idées.", "idée remue méninges carte mentale"),
    ("cause_effect", "Cause et effet", "Entreprise", stencils.BASIC, "orthogonal", True,
     "Structure pour représenter causes et effets.", "ishikawa poisson qualité"),
    ("swot", "Analyse SWOT", "Entreprise", stencils.BASIC, "straight", False,
     "Matrice pour forces, faiblesses, opportunités et menaces.", "ffom swot stratégie"),
    ("matrix", "Diagramme matriciel", "Entreprise", stencils.BASIC, "straight", False,
     "Formes de base pour composer une matrice.", "matrice comparaison"),
    ("pyramid", "Diagramme pyramidal", "Entreprise", stencils.BASIC, "straight", False,
     "Formes empilables pour représenter des niveaux.", "pyramide niveaux hiérarchie"),
    ("venn", "Diagramme de Venn", "Entreprise", stencils.BASIC, "straight", False,
     "Formes de base pour représenter des ensembles.", "venn ensemble intersection"),
    ("marketing", "Diagramme marketing", "Entreprise", stencils.BASIC, "orthogonal", True,
     "Formes pour parcours et processus marketing.", "marketing parcours campagne"),
    ("tqm", "Gestion de la qualité (TQM)", "Entreprise", stencils.FLOW, "orthogonal", True,
     "Outils de diagramme pour la gestion de la qualité.", "tqm qualité amélioration"),
    ("epc", "Chaîne de processus pilotée par événements", "Entreprise", stencils.FLOW, "orthogonal", True,
     "Formes de processus métier et d’événements.", "epc événement métier"),
    ("audit", "Diagramme d’audit", "Entreprise", stencils.FLOW, "orthogonal", True,
     "Étapes de vérification et de décision.", "audit conformité contrôle"),

    ("network", "Réseau détaillé", "Réseau", stencils.NET, "straight", True,
     "Équipements et liaisons réseau détaillés.", "serveur internet infrastructure"),
    ("logical_network", "Réseau logique", "Réseau", stencils.NET, "straight", True,
     "Éléments pour décrire une topologie logique.", "topologie logique lan"),
    ("home_network", "Réseau domestique", "Réseau", stencils.NET, "straight", True,
     "Routeurs, appareils et connexions domestiques.", "wifi routeur maison"),
    ("star_network", "Réseau en étoile", "Réseau", stencils.NET, "straight", True,
     "Équipements pour une topologie en étoile.", "topologie étoile switch"),
    ("physical_network", "Réseau physique", "Réseau", stencils.NET, "straight", True,
     "Équipements et connexions d’infrastructure physique.", "câblage physique infrastructure"),
    ("rack_diagram", "Rack de serveurs", "Réseau", stencils.NET, "straight", True,
     "Équipements réseau et serveurs pour baies.", "rack armoire serveur"),
    ("active_directory", "Services Active Directory", "Réseau", stencils.NET, "orthogonal", True,
     "Serveurs, utilisateurs et ressources d’annuaire.", "ad domaine annuaire"),
    ("ldap", "Annuaire LDAP", "Réseau", stencils.NET, "orthogonal", True,
     "Éléments de structure d’annuaire.", "ldap directory annuaire"),
    ("azure_architecture", "Architecture Azure", "Réseau", stencils.NET, "straight", True,
     "Gabarits génériques pour architecture cloud Azure.", "azure cloud microsoft"),
    ("aws_architecture", "Architecture AWS", "Réseau", stencils.NET, "straight", True,
     "Gabarits génériques pour architecture AWS.", "aws cloud amazon"),

    ("floorplan", "Plan d’aménagement", "Plans et bâtiments", stencils.FLOORPLAN, "orthogonal", True,
     "Gabarits de murs, ouvertures et mobilier.", "plan bâtiment pièce"),
    ("office_layout", "Plan de bureau", "Plans et bâtiments", stencils.FLOORPLAN, "orthogonal", True,
     "Formes d’aménagement de bureaux et d’espaces de travail.", "bureau mobilier espace"),
    ("home_plan", "Plan de maison", "Plans et bâtiments", stencils.FLOORPLAN, "orthogonal", True,
     "Éléments de plan résidentiel.", "maison logement résidence"),
    ("site_plan", "Plan de site", "Plans et bâtiments", stencils.FLOORPLAN, "orthogonal", True,
     "Formes pour terrains, bâtiments et accès.", "site terrain extérieur"),
    ("plant_layout", "Plan d’usine", "Plans et bâtiments", stencils.FLOORPLAN, "orthogonal", True,
     "Zones et équipements d’aménagement industriel.", "usine atelier industriel"),
    ("hvac", "Systèmes CVC", "Plans et bâtiments", stencils.FLOORPLAN, "orthogonal", True,
     "Gabarits de ventilation et de climatisation.", "hvac cvc ventilation climatisation"),

    ("uml", "Diagramme de classes UML", "Logiciel et données", stencils.UML, "straight", False,
     "Classes et relations UML.", "uml classe logiciel"),
    ("uml_sequence", "Diagramme de séquence UML", "Logiciel et données", stencils.UML, "straight", True,
     "Participants et messages d’interaction UML.", "séquence message interaction"),
    ("uml_usecase", "Diagramme de cas d’utilisation", "Logiciel et données", stencils.UML, "straight", False,
     "Acteurs et cas d’utilisation UML.", "use case acteur uml"),
    ("uml_activity", "Diagramme d’activité UML", "Logiciel et données", stencils.UML, "orthogonal", True,
     "Activités, décisions et transitions UML.", "activité uml workflow"),
    ("uml_component", "Diagramme de composants UML", "Logiciel et données", stencils.UML, "orthogonal", True,
     "Composants et interfaces UML.", "composant interface"),
    ("uml_deployment", "Diagramme de déploiement UML", "Logiciel et données", stencils.UML, "orthogonal", True,
     "Nœuds et artefacts de déploiement.", "deployment serveur nœud"),
    ("uml_state", "Diagramme d’états UML", "Logiciel et données", stencils.UML, "orthogonal", False,
     "États, transitions et événements UML.", "état machine transition"),
    ("erd_crow", "Entité-association (Crow’s Foot)", "Logiciel et données", stencils.UML, "straight", False,
     "Entités et cardinalités Crow’s Foot.", "erd crow pied corbeau base données"),
    ("erd_chen", "Entité-association (Chen)", "Logiciel et données", stencils.UML, "straight", False,
     "Entités, attributs et relations Chen.", "erd chen entité relation"),
    ("database_model", "Modèle de base de données", "Logiciel et données", stencils.UML, "straight", True,
     "Formes de tables, champs et relations de données.", "base données schéma"),
    ("website", "Site web", "Logiciel et données", stencils.BASIC, "orthogonal", True,
     "Formes pour architecture et pages web.", "site internet page web"),
    ("website_map", "Plan de site web", "Logiciel et données", stencils.BASIC, "orthogonal", True,
     "Pages et hiérarchie d’un site web.", "sitemap arborescence page"),
    ("wireframe", "Maquette filaire", "Logiciel et données", stencils.BASIC, "orthogonal", False,
     "Formes de base pour des maquettes d’interface.", "wireframe interface écran"),
    ("app_architecture", "Architecture d’application", "Logiciel et données", stencils.UML, "orthogonal", True,
     "Composants et dépendances d’application.", "logiciel architecture application"),

    ("timeline", "Chronologie", "Calendrier", stencils.BASIC, "straight", True,
     "Repères et éléments de chronologie.", "timeline dates jalons"),
    ("calendar", "Calendrier", "Calendrier", stencils.BASIC, "straight", False,
     "Page vierge pour organiser un calendrier.", "mois semaine dates"),
    ("gantt", "Diagramme de Gantt", "Calendrier", stencils.BASIC, "straight", True,
     "Formes pour planifier tâches et durées.", "gantt projet tâches planning"),
    ("pert", "Diagramme PERT", "Calendrier", stencils.BASIC, "orthogonal", True,
     "Activités et dépendances de projet.", "pert projet dépendances"),
    ("project_schedule", "Planning de projet", "Calendrier", stencils.BASIC, "straight", True,
     "Éléments de planification et de calendrier.", "planning échéance projet"),

    ("circuit", "Schéma électrique", "Ingénierie", stencils.CIRCUIT, "straight", False,
     "Composants électriques et connexions.", "électricité circuit électronique"),
    ("electrical", "Schéma électrique détaillé", "Ingénierie", stencils.CIRCUIT, "orthogonal", True,
     "Gabarits électriques pour schémas détaillés.", "électricité câblage"),
    ("piping", "Tuyauterie et instrumentation", "Ingénierie", stencils.CIRCUIT, "orthogonal", True,
     "Gabarits de tuyauterie, vannes et équipements.", "p id pid tuyau vanne"),
    ("fluid_power", "Puissance hydraulique et pneumatique", "Ingénierie", stencils.CIRCUIT, "orthogonal", True,
     "Composants de circuits hydrauliques et pneumatiques.", "fluidique hydraulique pneumatique"),
    ("instrumentation", "Instrumentation", "Ingénierie", stencils.CIRCUIT, "orthogonal", True,
     "Éléments génériques d’instrumentation et de procédé.", "instrumentation procédé"),
    ("industrial_controls", "Commandes industrielles", "Ingénierie", stencils.CIRCUIT, "orthogonal", True,
     "Formes électriques et de contrôle industriel.", "automate plc relais"),
    ("assembly", "Assemblage", "Ingénierie", stencils.BASIC, "straight", True,
     "Formes pour vues et séquences d’assemblage.", "assemblage pièces"),
    ("parts_assembly", "Pièces et assemblage", "Ingénierie", stencils.BASIC, "straight", True,
     "Formes pour composants et assemblages.", "pièces mécanique"),
    ("systems", "Diagramme de systèmes", "Ingénierie", stencils.BASIC, "orthogonal", True,
     "Éléments pour systèmes et dépendances.", "système ingénierie"),
    ("logic", "Logique", "Ingénierie", stencils.CIRCUIT, "straight", False,
     "Gabarits pour portes et circuits logiques.", "logique booléenne portes"),
    ("mechanical", "Ingénierie mécanique", "Ingénierie", stencils.BASIC, "straight", True,
     "Formes de base pour assemblages mécaniques.", "mécanique ingénierie"),
    ("basic_flow", "Diagramme de flux de base", "Processus", stencils.FLOW, "orthogonal", False,
     "Page vierge avec les formes de flux les plus utilisées.", "organigramme flowchart basic"),
    ("cross_functional", "Diagramme interfonctionnel horizontal", "Processus", stencils.CFF, "orthogonal", True,
     "Gabarits horizontaux de couloirs et de phases.", "swimlane transversal horizontal"),
    ("cross_functional_vertical", "Diagramme interfonctionnel vertical", "Processus", stencils.CFF, "orthogonal", False,
     "Gabarits verticaux de couloirs et de phases.", "swimlane transversal vertical"),
    ("sharepoint_workflow", "Flux de travail SharePoint", "Processus", stencils.FLOW, "orthogonal", True,
     "Formes génériques pour cartographier un flux SharePoint.", "sharepoint workflow"),
    ("business_process", "Processus métier", "Entreprise", stencils.FLOW, "orthogonal", True,
     "Activités et décisions de processus métier.", "bpm entreprise activité"),
    ("block_diagram", "Diagramme de blocs", "Général", stencils.BASIC, "orthogonal", False,
     "Formes de blocs pour représenter des composants et relations.", "bloc composant système"),
    ("relationship_diagram", "Diagramme de relations", "Entreprise", stencils.BASIC, "straight", False,
     "Formes pour présenter les relations entre éléments.", "relation entité"),
    ("map", "Carte directionnelle", "Plans et bâtiments", stencils.BASIC, "straight", True,
     "Formes et flèches pour créer des cartes directionnelles.", "carte direction plan"),
    ("roadmap", "Feuille de route", "Calendrier", stencils.BASIC, "straight", True,
     "Repères temporels pour une feuille de route.", "roadmap jalons calendrier"),
    ("uml_communication", "Diagramme de communication UML", "Logiciel et données", stencils.UML, "straight", True,
     "Objets et échanges de messages UML.", "communication collaboration uml"),
    ("uml_timing", "Diagramme de temps UML", "Logiciel et données", stencils.UML, "straight", True,
     "Lignes de vie et contraintes temporelles UML.", "timing temps uml"),
    ("uml_package", "Diagramme de packages UML", "Logiciel et données", stencils.UML, "orthogonal", True,
     "Packages et dépendances UML.", "package dépendance logiciel"),
    ("database_relationship", "Relations de base de données", "Logiciel et données", stencils.UML, "straight", True,
     "Tables et relations pour la conception de données.", "database relation table"),
    ("building_plan", "Plan de bâtiment", "Plans et bâtiments", stencils.FLOORPLAN, "orthogonal", True,
     "Gabarits de murs, ouvertures et espaces de bâtiment.", "bâtiment étage architecture"),
)

TEMPLATES = [(item[0], item[1]) for item in _CATALOG]
TEMPLATE_INFO = {item[0]: (item[2], item[6], item[7]) for item in _CATALOG}
TEMPLATE_SETUP = {item[0]: (item[3], item[4], item[5]) for item in _CATALOG}


def template_info(key: str) -> tuple[str, str, str]:
    return TEMPLATE_INFO.get(key, ("Général", "Page vierge avec les formes générales.", "vide nouveau"))


def build(template: str) -> dict:
    """Crée une page vierge avec les préférences adaptées au type choisi."""
    palette, route, landscape = TEMPLATE_SETUP.get(template, TEMPLATE_SETUP["blank"])
    page = fileformat.default_page("Page-1")
    if landscape:
        width, height = PAGE_SIZES["A4"]
        page["width"], page["height"] = mm_to_px(height), mm_to_px(width)
    title = next((name for key, name in TEMPLATES if key == template), "Dessin vierge")
    raw = {
        "format": fileformat.FORMAT,
        "version": fileformat.VERSION,
        "settings": {"route": route, "theme": "office"},
        "properties": {"title": title},
        "pages": [page],
    }
    clean, _warnings = fileformat.validate_document(raw)
    return clean


def category_for(template: str) -> str:
    return TEMPLATE_SETUP.get(template, TEMPLATE_SETUP["blank"])[0]


def preview(template: str) -> dict:
    """L'aperçu est une page vide, jamais un diagramme d'exemple."""
    return build(template)


@lru_cache(maxsize=128)
def thumbnail(template: str, w: int = 176, h: int = 132):
    """Vignette d'une feuille vierge en orientation portrait ou paysage."""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap

    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(QColor("#f2f4f7"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    landscape = TEMPLATE_SETUP.get(template, TEMPLATE_SETUP["blank"])[2]
    ratio = (PAGE_SIZES["A4"][1] / PAGE_SIZES["A4"][0] if landscape
             else PAGE_SIZES["A4"][0] / PAGE_SIZES["A4"][1])
    max_w, max_h = w * 0.72, h * 0.78
    paper_w, paper_h = (max_w, max_w / ratio) if max_w / ratio <= max_h else (max_h * ratio, max_h)
    x, y = (w - paper_w) / 2, (h - paper_h) / 2
    paper = QRectF(x, y, paper_w, paper_h)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 24))
    p.drawRect(paper.translated(2, 2))
    p.setPen(QPen(QColor("#cbd3dc"), 1))
    p.setBrush(QColor("#ffffff"))
    p.drawRect(paper)
    p.setPen(QPen(QColor("#e0e5eb"), 1))
    fold = min(9.0, paper_w * 0.12, paper_h * 0.12)
    p.drawLine(int(paper.right() - fold), int(paper.top()),
               int(paper.right() - fold), int(paper.top() + fold))
    p.drawLine(int(paper.right() - fold), int(paper.top() + fold),
               int(paper.right()), int(paper.top() + fold))
    p.setPen(QPen(QColor("#d2d8e0"), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
    p.end()
    return pm
