# Composants tiers, marques et spécifications

## Licence de LinXdiagram

Le code source de LinXdiagram est publié sous licence MIT (voir [LICENSE](LICENSE)),
© 2026 Joss943 et les contributeurs. Les icônes, gabarits, modèles et captures d'écran du
dépôt ont été créés pour le projet et sont couverts par la même licence.

## Bibliothèques utilisées (non incluses dans le dépôt)

| Composant | Licence | Rôle |
|---|---|---|
| [Python](https://www.python.org) | PSF License | Langage |
| [Qt 6](https://www.qt.io) | LGPL v3 | Interface graphique |
| [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) | GPL v3 | Liaison Python de Qt |
| [OpenSSL](https://www.openssl.org) (libcrypto, chargée dynamiquement) | Apache 2.0 | Chiffrement AES-256-GCM et scrypt |

La licence MIT est compatible avec la GPL v3. Une distribution **binaire** qui embarque
PyQt6 (par exemple le paquet Flatpak) forme un ensemble soumis à la GPL v3 ; le code source
correspondant est celui de ce dépôt et celui de PyQt6.

## Polices

Aucune police n'est fournie. L'application utilise, si elles sont installées sur le système,
[Inter](https://rsms.me/inter/) (SIL Open Font License 1.1) et
[Carlito](https://github.com/googlefonts/carlito) (SIL Open Font License 1.1).

## Format Visio (.vsdx)

La lecture et l'écriture du format `.vsdx` reposent sur la spécification publique
[MS-VSDX] publiée par Microsoft dans le cadre de son programme Open Specifications et
couverte par la [Microsoft Open Specifications Promise](https://learn.microsoft.com/fr-fr/openspecs/dev_center/ms-devcentlp/1c24c7c8-28b0-4ce1-a47d-95fe1ff504bc).
Aucun code, aucune image ni aucun fichier de Microsoft n'est utilisé, copié ou décompilé.
Le comportement de la bibliothèque libre libvisio (MPL 2.0) a servi de référence pour les
points non précisés par la spécification ; aucun code n'en a été repris.

## Marques

Microsoft, Visio et Office sont des marques du groupe Microsoft. LinXdiagram est un projet
indépendant, **non affilié** à Microsoft, ni approuvé, parrainé ou soutenu par Microsoft. Ces
noms sont cités uniquement pour indiquer la compatibilité de format et l'inspiration
ergonomique, conformément à l'usage loyal des marques (article 14 du règlement (UE) 2017/1001).
Linux® est une marque déposée de Linus Torvalds.
