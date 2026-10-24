# Confidentialité et données personnelles

LinXdiagram est conçu pour respecter le Règlement général sur la protection des données
(RGPD, règlement (UE) 2016/679) dès la conception et par défaut (article 25).

## Ce que l'application ne fait pas

* **Aucune collecte** : l'auteur du logiciel ne reçoit aucune donnée, personnelle ou non.
* **Aucune connexion réseau en arrière-plan** : pas de télémétrie, de statistiques d'usage, de rapport de plantage
  envoyé, de vérification de mise à jour ni de chargement de ressources en ligne. Les liens web
  ne sont ouverts dans le navigateur qu'après une action et une confirmation.
* **Aucun compte** et aucun identifiant publicitaire.
* Le nom de connexion du système n'est **jamais** inscrit dans les documents.

## Ce qui reste sur votre ordinateur

Toutes les données sont stockées localement, sous votre seul contrôle :

| Donnée | Emplacement | Comment l'effacer |
|---|---|---|
| Réglages (thème, volets, nom d'auteur facultatif) | `~/.config/LinXdiagram/` | Supprimer le dossier |
| Liste des fichiers récents | dans les réglages | Fichier > Options > « Mémoriser les fichiers récents », ou bouton « Effacer » |
| Copies de récupération automatique | `~/.local/share/LinXdiagram/autosave/` | Supprimées à la fermeture normale du document ; sinon supprimer le dossier |
| Journal des erreurs (texte technique, sans contenu de document) | `~/.local/state/LinXdiagram/erreurs.log` | Supprimer le fichier |

Les fichiers sont créés avec des droits réservés à votre compte (0600). Les copies de
récupération d'un document protégé par mot de passe restent chiffrées.

## Données inscrites dans vos documents

Un document peut contenir des métadonnées que **vous** saisissez : propriétés (titre, auteur,
société…), auteur des commentaires (le nom choisi dans Fichier > Options, « Utilisateur » par
défaut) et données de forme. Pensez-y avant de partager un fichier : Fichier > Informations
affiche ces propriétés.

## Site web du projet

Le site <https://joss943.github.io/LinXdiagram/> n'utilise ni cookie, ni traceur, ni outil
de mesure d'audience, ni ressource tierce (polices, scripts ou images externes). Il est hébergé
par GitHub Pages ; GitHub peut enregistrer l'adresse IP des visiteurs pour des raisons de
sécurité, selon sa propre
[déclaration de confidentialité](https://docs.github.com/fr/site-policy/privacy-policies/github-general-privacy-statement).

## Contact

Pour toute question, ouvrez un ticket sur
<https://github.com/Joss943/LinXdiagram/issues>. Vous pouvez aussi saisir la CNIL
(<https://www.cnil.fr>) ou l'autorité de protection des données de votre pays.
