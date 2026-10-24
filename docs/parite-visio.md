# Vers la parité fonctionnelle avec Visio

Ce document distingue les fonctions déjà présentes des écarts qui demandent encore du travail.
La référence provisoire est Visio desktop Professional / Plan 2 ; les fonctions diffèrent selon
l’édition et la version de Visio. L’objectif porte sur les usages, avec une interface LinXdiagram
et sans reprendre les éléments de marque ou le code propriétaire de Microsoft.

| Domaine | LinXdiagram aujourd’hui | Écart à traiter |
|---|---|---|
| Création et mise en page | Ruban et volets inspirés de Visio PC, palette de bureau Office 2024, gabarits, pages, groupes, thèmes, connecteurs, règles, grille, guides, calques et validation ; gabarits initiaux BPMN, plan de bureau et circuit | Étendre les bibliothèques BPMN, architecture et ingénierie |
| Navigation dans le dessin | Explorateur filtrable sur la page active ou toutes les pages, avec recherche dans le texte et les données de forme, filtre par calque et sélection des formes, groupes et connecteurs | Développer les conteneurs et objets imbriqués, et afficher les propriétés du document |
| Données | Création d’organigrammes et de flux depuis CSV ; liaison persistante dans `.lxd` des formes à un CSV local par clé avec actualisation à la demande ; données libres, rapports CSV et graphiques liés à une propriété (étiquette/valeur, valeur seule ou pastille de statut colorée) | Les liens CSV et les liaisons éditables des graphiques restent propres au `.lxd` ; règles de couleur configurables, plusieurs sources liées et liaison automatique à une base de données |
| Fichiers Visio | Import/export VSDX, formes, pages, styles, connecteurs et plusieurs métadonnées ; les graphiques LinXdiagram sont exportés comme annotations vectorielles figées | Les annotations exportées ne sont pas rattachées à leur forme par Visio ; les formules ShapeSheet ne sont pas exécutées ; VSD binaire, EMF/WMF et objets OLE ne sont pas pris en charge |
| Collaboration | Commentaires locaux et documents hors ligne | Coédition, présence, stockage cloud et intégration Teams hors périmètre actuel |
| Automatisation | Recherche de commandes, raccourcis et dispositions automatiques | Macros et compléments absents par conception ; ils nécessiteraient un modèle d’exécution isolé |
| Dessin au stylet | Outils de formes et de lignes | Outils de tracé libre et annotations tactiles à ajouter |

## Ordre de travail proposé

1. Ajouter les règles de couleur configurables et plusieurs sources locales pour les graphiques de données.
2. Étendre BPMN, architecture et les bibliothèques d’ingénierie.
3. Améliorer la fidélité des aller-retours VSDX, dont l’association éditable des graphiques de données, et documenter chaque élément non pris en charge.
4. Garder la coédition et les services cloud hors périmètre pour l’application de bureau hors ligne.

Cette feuille de route ne prétend pas à une parité complète. La comparaison officielle des éditions
Visio est publiée par [Microsoft Support](https://support.microsoft.com/en-us/visio/compare-visio-versions-and-features).
Les descriptions de [liaison et d’actualisation des données](https://support.microsoft.com/en-us/visio/importing-data-into-visio-an-overview)
et de [coédition](https://support.microsoft.com/en-us/visio/work-together-on-visio-drawings)
servent de références pour les écarts ci-dessus.
