"""Différences entre Linux, Windows et macOS : dossiers de l'application, processus.

Chaque système range les données de l'utilisateur à un endroit différent :

* Linux et autres Unix : spécification XDG (``~/.local/share``, ``~/.local/state``…) ;
* Windows : ``%LOCALAPPDATA%\\LinXdiagram`` ;
* macOS : ``~/Library/Application Support``, ``~/Library/Logs`` et ``~/Library/Caches``.
"""

from __future__ import annotations

import os
import sys

from . import APP_NAME

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def _xdg(var: str, fallback: str) -> str:
    base = os.environ.get(var)
    if not base or not os.path.isabs(base):
        base = os.path.expanduser(fallback)
    return os.path.join(base, APP_NAME)


def _windows_base() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base or not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, APP_NAME)


def _mac(sub: str) -> str:
    return os.path.join(os.path.expanduser("~"), "Library", sub, APP_NAME)


def _override(sub: str) -> str | None:
    """``LINXDIAGRAM_HOME`` regroupe tous les dossiers (tests, version portable sur clé USB)."""
    base = os.environ.get("LINXDIAGRAM_HOME")
    if base and os.path.isabs(base):
        return os.path.join(base, sub)
    return None


def data_dir() -> str:
    """Données persistantes (copies de récupération)."""
    if (o := _override("data")):
        return o
    if IS_WINDOWS:
        return _windows_base()
    if IS_MACOS:
        return _mac("Application Support")
    return _xdg("XDG_DATA_HOME", "~/.local/share")


def state_dir() -> str:
    """Journaux d'erreurs."""
    if (o := _override("state")):
        return o
    if IS_WINDOWS:
        return os.path.join(_windows_base(), "Logs")
    if IS_MACOS:
        return _mac("Logs")
    return _xdg("XDG_STATE_HOME", "~/.local/state")


def runtime_dir() -> str:
    """Fichiers temporaires de l'interface (images des feuilles de style)."""
    if (o := _override("cache")):
        return o
    if IS_WINDOWS:
        return os.path.join(_windows_base(), "Cache")
    if IS_MACOS:
        return _mac("Caches")
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base or not os.path.isdir(base):
        base = os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "linxdiagram-ui")


def config_dir() -> str:
    """Fichiers de configuration écrits par l'application (dictionnaire personnel)."""
    if (o := _override("config")):
        return o
    if IS_WINDOWS:
        return _windows_base()
    if IS_MACOS:
        return _mac("Application Support")
    return _xdg("XDG_CONFIG_HOME", "~/.config")


def documents_dir() -> str:
    for name in ("Documents", "Mes documents"):
        path = os.path.join(os.path.expanduser("~"), name)
        if os.path.isdir(path):
            return path
    return os.path.expanduser("~")


def pid_alive(pid: int) -> bool:
    """Le processus ``pid`` existe-t-il encore ?

    Sous Windows, ``os.kill(pid, 0)`` terminerait le processus : on interroge
    donc le noyau avec OpenProcess / GetExitCodeProcess.
    """
    if pid <= 0:
        return False
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # accès refusé : le processus existe
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def ui_chrome_fonts() -> tuple[str, ...]:
    """Polices du ruban et des volets, par ordre de préférence."""
    if IS_WINDOWS:
        return ("Segoe UI", "Inter", "Arial")
    if IS_MACOS:
        return (".AppleSystemUIFont", "Helvetica Neue", "Inter", "Helvetica")
    return ("Inter", "Noto Sans", "Cantarell", "DejaVu Sans", "Liberation Sans")


def ui_font_candidates() -> tuple[str, ...]:
    """Polices d'interface proches de Calibri / Segoe UI selon le système."""
    common = ("Calibri", "Carlito")
    if IS_WINDOWS:
        return common + ("Segoe UI", "Arial")
    if IS_MACOS:
        return common + ("Helvetica Neue", ".AppleSystemUIFont", "Helvetica")
    return common + ("Noto Sans", "Cantarell", "DejaVu Sans", "Liberation Sans")
