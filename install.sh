#!/bin/sh
# Installation de LinXdiagram pour l'utilisateur courant (sans droits administrateur).
#   ./install.sh              installe dans ~/.local
#   ./install.sh --uninstall  désinstalle
#   PREFIX=/chemin ./install.sh   installe ailleurs
set -eu

APP_ID=io.github.joss943.LinXdiagram
PREFIX="${PREFIX:-$HOME/.local}"
LIBDIR="$PREFIX/share/linxdiagram"
BINDIR="$PREFIX/bin"
APPDIR="$PREFIX/share/applications"
ICONDIR="$PREFIX/share/icons/hicolor/scalable/apps"
MIMEDIR="$PREFIX/share/mime"
METADIR="$PREFIX/share/metainfo"
SRC="$(cd "$(dirname "$0")" && pwd)"

refresh() {
    command -v update-mime-database >/dev/null 2>&1 && update-mime-database "$MIMEDIR" >/dev/null 2>&1 || true
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPDIR" >/dev/null 2>&1 || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true
}

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$LIBDIR"
    rm -f "$BINDIR/linxdiagram" "$APPDIR/$APP_ID.desktop" "$ICONDIR/$APP_ID.svg" \
          "$MIMEDIR/packages/$APP_ID-mime.xml" "$METADIR/$APP_ID.metainfo.xml"
    refresh
    echo "LinXdiagram a été désinstallé (vos documents et réglages sont conservés)."
    exit 0
fi

python3 -c "import sys; sys.exit(sys.version_info < (3, 11))" || {
    echo "Python 3.11 ou plus récent est requis." >&2
    exit 1
}
python3 -c "import PyQt6.QtWidgets, PyQt6.QtSvg, PyQt6.QtPrintSupport" 2>/dev/null || {
    echo "PyQt6 est requis. Sur Fedora : sudo dnf install python3-pyqt6" >&2
    echo "Sur Debian/Ubuntu : sudo apt install python3-pyqt6 python3-pyqt6.qtsvg" >&2
    exit 1
}

umask 022
mkdir -p "$LIBDIR" "$BINDIR" "$APPDIR" "$ICONDIR" "$MIMEDIR/packages" "$METADIR"
rm -rf "$LIBDIR/linxdiagram"
cp -R "$SRC/linxdiagram" "$LIBDIR/"
find "$LIBDIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
python3 -m compileall -q "$LIBDIR/linxdiagram" >/dev/null
# Mode isolé (-I) si PyQt6 est installé au niveau du système, sinon -P (PyQt6 via pip --user).
if python3 -I -c "import PyQt6.QtWidgets" 2>/dev/null; then PYFLAGS=-I; else PYFLAGS=-P; fi
sed "s|@LIBDIR@|$LIBDIR|; s|@PYFLAGS@|$PYFLAGS|" "$SRC/bin/linxdiagram" > "$BINDIR/linxdiagram"
chmod 755 "$BINDIR/linxdiagram"
sed "s|^Exec=linxdiagram|Exec=$BINDIR/linxdiagram|; s|^TryExec=linxdiagram|TryExec=$BINDIR/linxdiagram|" \
    "$SRC/packaging/$APP_ID.desktop" > "$APPDIR/$APP_ID.desktop"
cp "$SRC/packaging/$APP_ID.svg" "$ICONDIR/"
cp "$SRC/packaging/$APP_ID-mime.xml" "$MIMEDIR/packages/"
cp "$SRC/packaging/$APP_ID.metainfo.xml" "$METADIR/"
refresh
echo "LinXdiagram est installé. Lancez-le depuis le menu des applications ou avec : linxdiagram"
case ":$PATH:" in *":$BINDIR:"*) ;; *) echo "Note : ajoutez $BINDIR à votre PATH." ;; esac
