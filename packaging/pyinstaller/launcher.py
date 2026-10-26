"""Point d'entrée des paquets autonomes (PyInstaller)."""

import sys

from linxdiagram.app import main

if __name__ == "__main__":
    sys.exit(main())
