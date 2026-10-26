# -*- mode: python -*-
# Paquet autonome Windows (dossier + LinXdiagram.exe) et macOS (LinXdiagram.app).
#   python packaging/make_icons.py build/icons
#   (macOS) iconutil -c icns build/icons/LinXdiagram.iconset
#   pyinstaller --noconfirm packaging/pyinstaller/linxdiagram.spec
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
sys.path.insert(0, ROOT)
from linxdiagram import APP_ID, __version__  # noqa: E402

ICONS = os.path.join(ROOT, "build", "icons")
icon = None
if sys.platform == "win32":
    icon = os.path.join(ICONS, "LinXdiagram.ico")
elif sys.platform == "darwin":
    icon = os.path.join(ICONS, "LinXdiagram.icns")
if icon and not os.path.exists(icon):
    icon = None

a = Analysis(
    [os.path.join(ROOT, "packaging", "pyinstaller", "launcher.py")],
    pathex=[ROOT],
    hiddenimports=["PyQt6.QtSvg", "PyQt6.QtPrintSupport", "cryptography.hazmat.primitives.ciphers.aead"],
    excludes=["tkinter", "PyQt6.QtWebEngineCore", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.Qt3DCore",
              "PyQt6.QtMultimedia", "PyQt6.QtBluetooth"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LinXdiagram", console=False,
          icon=icon, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="LinXdiagram")

if sys.platform == "darwin":
    doc_types = [
        {"CFBundleTypeName": "Dessin LinXdiagram", "CFBundleTypeRole": "Editor",
         "LSHandlerRank": "Owner", "CFBundleTypeExtensions": ["lxd"],
         "LSItemContentTypes": [f"{APP_ID}.lxd"]},
        {"CFBundleTypeName": "Dessin Visio", "CFBundleTypeRole": "Editor",
         "LSHandlerRank": "Alternate", "CFBundleTypeExtensions": ["vsdx"]},
    ]
    app = BUNDLE(
        coll, name="LinXdiagram.app", icon=icon, bundle_identifier=APP_ID, version=__version__,
        info_plist={
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "CFBundleDisplayName": "LinXdiagram",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleDocumentTypes": doc_types,
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": f"{APP_ID}.lxd", "UTTypeDescription": "Dessin LinXdiagram",
                "UTTypeConformsTo": ["public.data", "public.json"],
                "UTTypeTagSpecification": {"public.filename-extension": ["lxd"],
                                           "public.mime-type": ["application/x-linxdiagram"]},
            }],
        },
    )
