# Politique de sécurité

## Versions prises en charge

Seule la dernière version publiée reçoit des correctifs de sécurité.

## Signaler une vulnérabilité

Merci de **ne pas** ouvrir de ticket public pour une faille de sécurité. Utilisez le
signalement privé de GitHub : onglet **Security** du dépôt, puis
**Report a vulnerability** (<https://github.com/Joss943/LinXdiagram/security/advisories/new>).

Indiquez si possible la version, les étapes pour reproduire et un fichier d'exemple.
Vous recevrez un accusé de réception sous 7 jours. Une fois le correctif publié, la faille
sera décrite dans un avis de sécurité, avec votre accord pour vous citer.

Ce processus suit les principes de divulgation coordonnée des vulnérabilités recommandés
par l'ENISA et le règlement européen sur la cyberrésilience (CRA).

## Mesures de sécurité de l'application

Voir la section « Sécurité » du [README](README.md) : pas de macros ni de formules exécutées,
aucune connexion réseau, validation stricte des fichiers, import VSDX protégé contre les
bombes de décompression et les attaques XML, chiffrement AES-256-GCM.
