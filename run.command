#!/bin/sh
# Lance LinXdiagram depuis les sources sous macOS (double-clic dans le Finder).
# Prérequis : python3 -m pip install PyQt6 cryptography
cd "$(dirname "$0")" && exec python3 -P -m linxdiagram "$@"
