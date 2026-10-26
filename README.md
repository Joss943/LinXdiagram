# LinXdiagram

Éditeur de diagrammes **libre pour Linux, Windows et macOS**, à l'ergonomie familière pour les
habitués de Microsoft Visio : ruban, gabarits de formes, connecteurs dynamiques, connexion
automatique, repères d'alignement… et **compatible avec les fichiers `.vsdx`**.

Application Qt 6 (PyQt6), intégrée au bureau : GNOME et KDE (Wayland et X11), Windows 10/11
et macOS 11 ou plus récent (barre de titre native, ouverture des fichiers depuis le Finder).
Site du projet : <https://joss943.github.io/LinXdiagram/>

> Projet indépendant, **non affilié à Microsoft**, ni approuvé ou soutenu par Microsoft.
> Microsoft, Visio et Office sont des marques du groupe Microsoft, citées uniquement pour
> indiquer la compatibilité (voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).

![Éditeur](docs/captures/editeur.png)

## Démarrage rapide

```bash
./run.sh                 # lancer depuis les sources
./install.sh             # installer pour l'utilisateur (~/.local), avec entrée de menu
./install.sh --uninstall # désinstaller
```

Dépendances : Python ≥ 3.11 et PyQt6 (`sudo dnf install python3-pyqt6` sur Fedora,
`sudo apt install python3-pyqt6 python3-pyqt6.qtsvg` sur Debian/Ubuntu). La police
Carlito (métriquement identique à Calibri) est utilisée si elle est installée.

### Windows et macOS

Des paquets prêts à l'emploi sont publiés à chaque version (onglet *Releases* de GitHub) :
installateur Windows (`.exe`, sans droits administrateur, associations `.lxd` et `.vsdx`),
version portable `.zip`, et image disque macOS (`.dmg`, Apple Silicon et Intel).

Depuis les sources :

```bash
python -m pip install PyQt6 cryptography
python -m linxdiagram          # ou run.bat (Windows), run.command (macOS)
```

`pip install .` installe aussi la commande `linxdiagram`. Les dossiers de l'application suivent
chaque système : `~/.local/share` et `~/.config` (Linux), `%LOCALAPPDATA%\LinXdiagram` (Windows),
`~/Library/Application Support/LinXdiagram` (macOS). La variable `LINXDIAGRAM_HOME` les
regroupe dans un seul dossier (version portable sur clé USB). Pour l'orthographe sous Windows
et macOS, copiez les dictionnaires Hunspell (`fr_FR.aff` et `fr_FR.dic`, ceux de LibreOffice)
dans le sous-dossier `dictionnaires` de ce dossier ; sous macOS, ceux de Homebrew
(`brew install hunspell`) et de `~/Library/Spelling` sont aussi reconnus.

## Une interface familière

* **Barre de titre** bleue façon Office : barre d'outils Accès rapide (Enregistrer, Annuler avec
  historique, Rétablir), titre du document et zone **« Rechercher (Alt+Q) »** qui trouve et lance
  n'importe quelle commande ou insère une forme par son nom.
* Thème de bureau inspiré d’Office 2024 : bleu plus vif, onglets et ruban lumineux, canevas gris
  doux avec feuille blanche ombrée ; volets Formes et propriétés de part et d’autre du canevas.
* **Ruban** à neuf onglets : Accueil, Insertion, Création, Données, Processus, Révision, Affichage,
  Développeur, Aide ; grands et petits boutons, boutons partagés, galeries, lanceurs de boîte de
  dialogue ↘, réduction du ruban (Ctrl+F1 ou double-clic sur un onglet).
* **Volet Formes** : onglets FORMES / RECHERCHER, « Plus de formes », Formes rapides, gabarits ouverts,
  liste à deux colonnes, glisser-déposer.
* **Nouveau diagramme** : catalogue local de 84 types dans les familles processus, entreprise, réseau,
  plans, logiciel et données, calendrier et ingénierie. Chaque choix ouvre une page vierge avec le
  gabarit de formes et l’orientation adaptés ; les diagrammes interfonctionnels ne contiennent que
  des couloirs vides. Les formes BPMN 2.0 comprennent notamment événements, tâches et passerelles spécialisés.
* **Gabarits ajoutés** : diagramme de blocs, base de données (entité-relation : entités, relations,
  attributs, tables, vues) et chronologie (ligne de temps, jalons, intervalles), en plus du BPMN 2.0.
* **Volets de tâches** : Format de la forme (Remplissage et trait, Effets, Texte, Taille et
  propriétés), Taille et position, Données de forme, Commentaires, Problèmes, Panoramique et zoom,
  et **Explorateur de dessin** avec recherche par texte ou données, filtre par calque, sélection des
  formes, groupes et connecteurs, et navigation sur toutes les pages du document.
* **Onglets de pages** avec navigation ◀ ▶, menu « Tout » et ⊕ ; **barre d'état** avec page, taille et
  angle de la sélection, langue, mode Présentation et curseur de zoom.
* **Menu Fichier** façon Microsoft 365 : Accueil (« Bonjour », vignettes de diagrammes vierges, récents),
  Nouveau, Ouvrir, Informations (protection, propriétés), Imprimer avec **aperçu intégré**, Exporter.
* **Menu contextuel avec mini-barre** (police, taille, gras, style rapide, remplissage, trait).
* Thème **« En couleur »** par défaut, thème **Noir** disponible (Fichier > Options).
* La largeur des volets Formes et Format, ainsi que l'état du ruban réduit, sont mémorisés entre
  les sessions. Le canevas ne redessine que les zones modifiées lorsque c'est possible, ce qui
  améliore la réactivité des grands diagrammes.
* La compatibilité et les écarts restants par rapport à Visio sont suivis dans
  [la feuille de route de parité](docs/parite-visio.md).

## Fonctions Visio

| Onglet | Fonctions |
|---|---|
| Accueil | Coller, couper, copier, reproduire la mise en forme ; police, taille, A⁺/A⁻, effacer la mise en forme, gras, italique, souligné, barré, casse ; alignements ; Pointeur, Connecteur, Texte, outils de dessin (rectangle, ellipse, ligne, forme libre, arc) dont **Stylo à main levée** (Ctrl+7) ; **Styles rapides** (35 styles), Remplissage, Trait (couleur, épaisseur, tirets, flèches), Effets (ombre, lumière, dégradé) ; Aligner, Position (**Aligner automatiquement et espacer**, espacement automatique, distribuer), Premier plan, Arrière-plan, Grouper ; **Modifier la forme**, Calques, Sélectionner par type, Rechercher / Remplacer |
| Insertion | Page vierge, **page d'arrière-plan** (cartouche, logo, filigrane affichés derrière les pages qui l'utilisent), dupliquer, renommer, supprimer ; Images ; **Conteneur** (entoure la sélection ; onglet contextuel **Format du conteneur** : styles, ajuster au contenu, sélectionner le contenu, désassembler ; déplacer un conteneur déplace ses formes), Légende, Connecteur ; Lien (web ou page du document) ; Zone de texte, Info-bulle d'écran, Symbole ; **Champ** (date, heure, numéro et nombre de pages, nom de page, nom de fichier, titre, auteur), mis à jour automatiquement |
| Création | Orientation, Taille, **Taille automatique**, Mise en page ; **Thèmes** et **Variantes** ; Arrière-plans, **Bordures et titres** ; **Redisposer la page**, Connecteurs, **sauts de ligne** |
| Données | **Créer à partir de données** (organigramme ou diagramme de flux depuis un CSV), lier chaque forme à plusieurs fichiers CSV locaux par clé et actualiser toutes les sources à la demande, noms de colonnes préfixés automatiquement en cas de conflit, **graphiques de données** (étiquette et valeur, valeur seule ou pastille de statut avec couleurs configurables), fenêtre Données de forme, **Rapports de forme** (CSV). À l’export VSDX, les graphiques deviennent des annotations vectorielles statiques et séparables dans Visio ; les métadonnées LinXdiagram rétablissent leur association et leurs règles de couleur au réimport. |
| Processus | **Sous-processus** à partir de la sélection, **Vérifier le diagramme**, fenêtre Problèmes |
| Diagramme de flux interfonctionnel (contextuel) | Couloir (avant / après), Séparateur, nouveau diagramme horizontal ou vertical, Disposer les couloirs, Orientation du diagramme, Faire pivoter les étiquettes, Styles, Barre de titre, Séparateurs |
| Volet Formes | **Mes formes > Favoris** : clic droit > « Ajouter aux Favoris » sur une forme ou une sélection, puis glisser-déposer ; renommer ou supprimer par clic droit dans le volet |
| Révision | **Orthographe** (F7, dictionnaires Hunspell du système, hors ligne, dictionnaire personnel) ; **Commentaires** (nouveau, précédent, suivant, supprimer, volet), **verrouiller les formes**, protéger le document |
| Affichage | **Plein écran** (présentation page par page), règle (**repères** tirés des règles, avec aimantation des formes ; les ramener sur la règle ou Suppr les efface), grille, grille dynamique, AutoConnect, points de connexion, magnétisme, Zoom, Ajuster à la fenêtre, Largeur de page, Nouvelle fenêtre, Volets des tâches |
| Développeur | ShapeSheet ; **Opérations** sur les formes (Union, Combiner, Fragmenter, Intersecter, Soustraire), Forme libre, Arc, Crayon ; import / export .vsdx, propriétés du document |

### Diagrammes de flux interfonctionnels (couloirs)

![Couloirs](docs/captures/couloirs.png)

* Modèle **« Diagramme de flux interfonctionnel »** et gabarit dédié : couloirs horizontaux ou
  verticaux, séparateurs de phases, cadre avec barre de titre.
* Onglet contextuel **« Diagramme de flux interfonctionnel »**, affiché dès qu'on utilise des
  couloirs, comme dans Visio : Couloir (avant/après), Séparateur, nouveau diagramme horizontal ou
  vertical, Disposer les couloirs, **Orientation du diagramme** (passe d'horizontal à vertical en
  gardant chaque forme dans son couloir et sa phase, et met la page en portrait ou en paysage),
  **Faire pivoter les étiquettes des couloirs**, galerie de **styles**, cases **Barre de titre** et
  **Séparateurs**.

  ![Couloirs verticaux](docs/captures/couloirs-vertical.png)
* Comportement de Visio : les couloirs restent accolés ; **glisser un couloir le réordonne et
  emmène ses formes** ; redimensionner un couloir décale les suivants ; insérer un couloir au
  milieu pousse ceux du dessous ; **supprimer un couloir supprime son contenu** et referme
  l'espace ; supprimer le cadre supprime toute la structure ; un nouveau séparateur coupe la phase
  où on le dépose sans rallonger le diagramme ; les nouveaux couloirs reprennent le style de leurs
  voisins. Tout est annulable.
* Étiquettes de couloir verticales, intérieur des couloirs « transparent » aux clics (sélection
  par zone, formes posées dessus).
* **Créer à partir de données** : une colonne « Fonction » dans le CSV produit directement un
  diagramme interfonctionnel, une ligne par fonction, étapes dans l'ordre du processus.
* « Vérifier le diagramme » signale les étapes posées hors de tout couloir.
* Export `.vsdx` : étiquettes verticales comprises, et cadre, couloirs et phases enregistrés comme
  **conteneurs Visio** (`User.msvStructureType`, cellule `Relationships`), avec l'appartenance de
  chaque forme à son couloir et à sa phase. Import des couloirs, séparateurs et cadres des
  fichiers Visio.

Et aussi : **AutoConnect** avec mini-barre des **formes rapides** au survol des flèches bleues,
collage dynamique ou statique des connecteurs, saisie directe du texte, poignées de rotation,
grille dynamique, annulation illimitée, raccourcis clavier de Visio (Ctrl+1/2/3, Ctrl+Maj+F/B,
Ctrl+Maj+G/U, Ctrl+R/L, Ctrl+H/J, F5…).

Exports : PDF (multipage, vectoriel), PNG, JPEG, SVG, **page web HTML** (toutes les pages dans
un seul fichier, sans script ni ressource externe), `.vsdx` ; impression avec aperçu.

## Compatibilité Visio (.vsdx)

Le format VSDX est un paquet ZIP de parties XML publié par Microsoft (spécification
ouverte [MS-VSDX]). LinXdiagram lit et écrit ce format directement, à partir de cette
spécification et du comportement de libvisio (la bibliothèque de LibreOffice issue de
la rétro-ingénierie du format) pour les points que la documentation ne précise pas.
Aucun code de Microsoft n'est utilisé ni décompilé.

* **Import** : formes maîtres et héritage, feuilles de style, géométrie (lignes, arcs,
  arcs elliptiques, ellipses, Béziers, polylignes), groupes, textes et mise en forme,
  données de forme, liens, connecteurs et collages, images PNG/JPEG, pages multiples.
* **Export** : fichiers lisibles par Visio et LibreOffice (vérifié par conversion
  LibreOffice dans les tests), aller-retour sans perte du type des formes, des calques, des
  verrous et des info-bulles.
* **Limites** : les formules ShapeSheet ne sont pas exécutées (seules leurs valeurs
  calculées sont lues), les images EMF/WMF et objets OLE sont remplacés par un cadre,
  le format binaire `.vsd` (Visio 2010 et antérieur) n'est pas lu — convertissez-le
  d'abord en `.vsdx`.

## Sécurité

* **Pas de macros, scripts ni formules** : un document ne peut exécuter aucun code
  (contrairement aux macros VBA de Visio).
* **Format `.lxd` en JSON strictement validé** : liste blanche des champs, nombres finis
  et bornés, tailles et quantités limitées, empreinte SHA-256 contre l'altération.
* **Chiffrement par mot de passe** : AES-256-GCM (OpenSSL) et dérivation scrypt aux
  paramètres bornés pour empêcher un fichier piégé d'épuiser la mémoire ;
  vérifié avec le vecteur de test officiel du NIST. Les copies de récupération d'un
  document chiffré restent chiffrées.
* **Import VSDX blindé** : protection contre les bombes de décompression, XML avec
  DTD refusé (XXE, « billion laughs »), XML non UTF-8 et parties ZIP ambiguës refusés,
  chemins normalisés, aucune ressource externe.
* **Images** : PNG/JPEG uniquement, décodées avec plafond mémoire, ré-encodées à
  l'insertion pour retirer les métadonnées (EXIF, GPS).
* **Liens** : http, https et mailto seulement, sans identifiants intégrés, confirmation avant ouverture.
* **Contenu utilisateur** : texte de document affiché comme texte brut dans les infobulles ; formules
  CSV neutralisées cellule par cellule dans les rapports.
* **Fichiers** : écriture atomique, nouveaux documents en droits 0600, lecture
  bornée (pas de FIFO ni de périphérique), pas de core dump.
* **Aucune connexion réseau en arrière-plan**, aucune télémétrie ; les liens web ne s'ouvrent
  dans le navigateur qu'après une action et une confirmation ; collage en texte brut uniquement.
* **Flatpak** (`packaging/flatpak`) : bac à sable sans accès réseau.

## Confidentialité (RGPD)

Aucune donnée n'est collectée ni transmise par LinXdiagram : pas de service cloud, de télémétrie
ni de compte. Les liens web sont ouverts uniquement sur demande dans le navigateur du système.
Tout reste sur votre ordinateur ; le nom de connexion du système n'est jamais inscrit
dans les documents. Détails et emplacements des fichiers locaux : [PRIVACY.md](PRIVACY.md).

## Accessibilité

Toutes les commandes sont accessibles au clavier (raccourcis, recherche de commandes Alt+Q,
navigation par Tab) et l'interface suit le thème clair ou sombre. Le site du projet vise le
niveau AA des WCAG 2.1 (norme européenne EN 301 549).

## Licence

Code sous licence **MIT** © 2026 Joss943 et les contributeurs — voir [LICENSE](LICENSE).
Composants tiers, polices, spécification [MS-VSDX] et marques :
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Signaler une faille :
[SECURITY.md](SECURITY.md). Contribuer : [CONTRIBUTING.md](CONTRIBUTING.md).

## Tests

```bash
python3 -m unittest discover -s tests -t .
LINX_TEST_LIBREOFFICE=1 python3 -m unittest tests.test_vsdx   # + vérification par LibreOffice
```

Les tests couvrent la cryptographie, les fichiers malveillants, le format, le routage
des connecteurs, la disposition automatique, l'import/export Visio et l'interface
(souris et clavier simulés).

## Paquets

* `install.sh` : installation utilisateur (menu, icône, type de fichier `.lxd`,
  association `.vsdx`).
* `packaging/rpm/linxdiagram.spec` : paquet RPM pour Fedora.
* `packaging/flatpak/` : manifeste Flatpak (runtime KDE + PyQt BaseApp).
* `pyproject.toml` : installation par `pip` sur les trois systèmes.
* `packaging/pyinstaller/` : application autonome Windows (`LinXdiagram.exe`) et macOS
  (`LinXdiagram.app`, types de documents déclarés) ; `packaging/windows/linxdiagram.iss` :
  installateur Inno Setup. Le workflow `release.yml` les construit à chaque étiquette `v*`.

## Organisation du code

| Module | Rôle |
|---|---|
| `style.py`, `icons.py`, `ribbon.py`, `titlebar.py` | Charte Visio, icônes, ruban, barre de titre |
| `stencils.py` | Gabarits de formes (géométrie, points de connexion, zone de texte) |
| `items.py` | Formes et connecteurs (poignées, rotation, texte, collage) |
| `scene.py` | Interactions, magnétisme, repères, connexion automatique, opérations |
| `routing.py`, `layout.py` | Routage des connecteurs, disposition automatique |
| `commands.py`, `document.py` | Annulation/rétablissement, pages, document |
| `fileformat.py`, `security.py` | Format `.lxd` validé, chiffrement, fichiers |
| `compat.py` | Différences Linux / Windows / macOS (dossiers, processus, polices) |
| `vsdx.py` | Import/export Microsoft Visio |
| `export.py` | PDF, PNG, JPEG, SVG, page web, impression |
| `mainwindow.py`, `panes.py`, `canvas.py`, `backstage.py`, `widgets.py`, `dialogs.py`, `presentation.py` | Interface |
| `quickstyles.py`, `datavis.py`, `swimlanes.py` | Styles rapides et variantes, création à partir de données, couloirs |
