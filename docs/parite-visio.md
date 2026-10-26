# Vers la parité fonctionnelle avec Visio

Ce document distingue les fonctions déjà présentes des écarts qui demandent encore du travail.
La référence provisoire est Visio desktop Professional / Plan 2 ; les fonctions diffèrent selon
l’édition et la version de Visio. L’objectif porte sur les usages, avec une interface LinXdiagram
et sans reprendre les éléments de marque ou le code propriétaire de Microsoft.

| Domaine | LinXdiagram aujourd’hui | Écart à traiter |
|---|---|---|
| Création et mise en page | Ruban et volets de bureau inspirés de Visio PC, gabarits, pages, groupes, thèmes, connecteurs, règles, grille, guides, calques et validation ; catalogue local de 84 types dans les familles processus, entreprise, réseau, plans, logiciel/données, calendrier et ingénierie. Chaque choix ouvre une page vierge avec le gabarit associé ; le diagramme interfonctionnel ne contient que des couloirs vides. | Compléter les bibliothèques de formes spécialisées et rapprocher davantage les options de mise en page de Visio |
| Navigation dans le dessin | Explorateur filtrable sur la page active ou toutes les pages, avec recherche dans le texte et les données de forme, filtre par calque et sélection des formes, groupes et connecteurs | Développer les conteneurs et objets imbriqués, et afficher les propriétés du document |
| Données | Création d’organigrammes et de flux depuis CSV ; liaison persistante dans `.lxd` des formes à plusieurs CSV locaux par clé avec actualisation à la demande ; données libres, rapports CSV et graphiques liés à une propriété, avec règles de couleur de statut configurables | Les liens CSV restent propres au `.lxd` ; liaison automatique à une base de données |
| Fichiers Visio | Import/export VSDX, formes, pages, styles, connecteurs et plusieurs métadonnées ; les graphiques sont des annotations vectorielles dans Visio, avec métadonnées permettant à LinXdiagram de reconstruire l’association lors du réimport | Dans Visio, l’annotation peut être déplacée séparément de sa forme ; les formules ShapeSheet ne sont pas exécutées ; VSD binaire, EMF/WMF et objets OLE ne sont pas pris en charge |
| Conception de formes | Opérations Union, Combiner, Fragmenter, Intersection et Soustraire ; le résultat est une forme personnalisée annulable | Opérations Rogner, Joindre et Décaler |
| Pages et champs | Pages d’arrière-plan (affectation, renommage, boucles refusées, aller-retour VSDX) ; champs numéro de page, date, propriétés du document et données de forme ; espacement automatique ; export page web | Champs personnalisés à formule et format de nombre |
| Plateformes | Linux, Windows 10/11 et macOS 11+ : dossiers propres à chaque système, chiffrement via OpenSSL ou `cryptography`, ouverture depuis le Finder, paquets autonomes et installateur | Signature des paquets Windows et notarisation Apple |
| Collaboration | Commentaires locaux et documents hors ligne | Coédition, présence, stockage cloud et intégration Teams hors périmètre actuel |
| Automatisation | Recherche de commandes, raccourcis et dispositions automatiques | Macros et compléments absents par conception ; ils nécessiteraient un modèle d’exécution isolé |
| Dessin au stylet | Outil Stylo à main levée (Ctrl+7) ; le tracé est enregistré comme une forme personnalisée, modifiable avec les outils de mise en forme et l’historique Annuler/Rétablir | Annotations tactiles sensibles à la pression et édition des points du tracé |

## Ordre de travail proposé

1. Compléter les bibliothèques spécialisées et les options propres à chaque famille du catalogue.
2. Améliorer la fidélité des aller-retours VSDX afin que les graphiques restent liés à leurs formes dans Visio, et documenter chaque élément non pris en charge.
3. Garder la coédition et les services cloud hors périmètre pour l’application de bureau hors ligne.

Cette feuille de route ne prétend pas à une parité complète. La comparaison officielle des éditions
Visio est publiée par [Microsoft Support](https://support.microsoft.com/en-us/visio/compare-visio-versions-and-features).
Les descriptions de [liaison et d’actualisation des données](https://support.microsoft.com/en-us/visio/importing-data-into-visio-an-overview)
et de [coédition](https://support.microsoft.com/en-us/visio/work-together-on-visio-drawings)
servent de références pour les écarts ci-dessus.
