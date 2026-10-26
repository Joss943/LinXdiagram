"""Vérification orthographique (Révision > Orthographe, F7), hors ligne.

Utilise la bibliothèque Hunspell et les dictionnaires installés sur le système
(paquets hunspell-fr, hunspell-en…), comme LibreOffice. Aucun texte ne quitte
l'ordinateur. Les mots ajoutés par l'utilisateur sont gardés dans un dictionnaire
personnel local.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import sys

from . import compat, security

_LINUX_DICT_DIRS = ("/usr/share/hunspell", "/usr/share/myspell", "/usr/share/myspell/dicts",
                    "/app/share/hunspell")


def dict_dirs() -> list[str]:
    """Dossiers de dictionnaires .aff/.dic selon le système. Sous Windows et macOS, on peut
    aussi déposer les dictionnaires dans le dossier « dictionnaires » de l'application."""
    out = [os.path.join(compat.data_dir(), "dictionnaires")]
    if getattr(sys, "frozen", False):  # paquet autonome : dictionnaires livrés à côté
        out.append(os.path.join(os.path.dirname(sys.executable), "dictionnaires"))
    if compat.IS_MACOS:
        out += [os.path.expanduser("~/Library/Spelling"), "/Library/Spelling",
                "/opt/homebrew/share/hunspell", "/usr/local/share/hunspell"]
    elif not compat.IS_WINDOWS:
        out += list(_LINUX_DICT_DIRS)
    return out


def install_hint() -> str:
    if compat.IS_WINDOWS or compat.IS_MACOS:
        return ("Copiez les fichiers fr_FR.aff et fr_FR.dic (dictionnaires LibreOffice) dans :\n"
                + os.path.join(compat.data_dir(), "dictionnaires"))
    return "Installez par exemple le paquet « hunspell-fr » de votre distribution."


def _lib_names() -> list[str]:
    names = [ctypes.util.find_library("hunspell-1.7"), ctypes.util.find_library("hunspell")]
    if compat.IS_WINDOWS:
        names += ["libhunspell-1.7-0.dll", "libhunspell.dll", "hunspell.dll"]
    elif compat.IS_MACOS:
        names += ["/opt/homebrew/lib/libhunspell-1.7.dylib", "/usr/local/lib/libhunspell-1.7.dylib"]
    else:
        names += ["libhunspell-1.7.so.0", "libhunspell-1.6.so.0"]
    return names
LANGS = ("fr_FR", "fr_BE", "fr_CA", "fr_CH", "en_US", "en_GB")
LANG_NAMES = {"fr": "Français", "en": "Anglais"}
MAX_WORD = 100
MAX_PERSONAL = 5000
WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
_ELISIONS = ("l", "d", "j", "m", "n", "s", "t", "c", "qu", "jusqu", "lorsqu", "puisqu", "quoiqu")


def _load_lib():
    for name in _lib_names():
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        lib.Hunspell_create.restype = ctypes.c_void_p
        lib.Hunspell_create.argtypes = (ctypes.c_char_p, ctypes.c_char_p)
        lib.Hunspell_destroy.argtypes = (ctypes.c_void_p,)
        lib.Hunspell_spell.argtypes = (ctypes.c_void_p, ctypes.c_char_p)
        lib.Hunspell_spell.restype = ctypes.c_int
        lib.Hunspell_suggest.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_char_p)),
                                         ctypes.c_char_p)
        lib.Hunspell_suggest.restype = ctypes.c_int
        lib.Hunspell_free_list.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.c_char_p)),
                                           ctypes.c_int)
        lib.Hunspell_add.argtypes = (ctypes.c_void_p, ctypes.c_char_p)
        lib.Hunspell_add.restype = ctypes.c_int
        return lib
    return None


def find_dictionary(preferred: str = "fr_FR") -> tuple[str, str, str] | None:
    """(langue, chemin .aff, chemin .dic) du premier dictionnaire disponible."""
    for lang in (preferred,) + LANGS:
        for d in dict_dirs():
            aff, dic = os.path.join(d, lang + ".aff"), os.path.join(d, lang + ".dic")
            if os.path.isfile(aff) and os.path.isfile(dic):
                return lang, aff, dic
    return None


class SpellChecker:
    def __init__(self, personal_path: str | None = None, preferred: str = "fr_FR"):
        self._lib = _load_lib()
        found = find_dictionary(preferred)
        self.lang = found[0] if found else ""
        self._h = None
        self._encoding = "utf-8"
        self.personal_path = personal_path
        self.personal: set[str] = set()
        self.ignored: set[str] = set()
        if self._lib is None or found is None:
            return
        _lang, aff, dic = found
        self._encoding = _aff_encoding(aff)
        self._h = self._lib.Hunspell_create(aff.encode(), dic.encode())
        for w in self._read_personal():
            self._add(w)

    @property
    def available(self) -> bool:
        return self._h is not None

    def __del__(self):
        if getattr(self, "_h", None) and self._lib is not None:
            self._lib.Hunspell_destroy(self._h)
            self._h = None

    def _enc(self, word: str) -> bytes | None:
        try:
            return word.encode(self._encoding)
        except UnicodeEncodeError:
            return None

    def _add(self, word: str) -> None:
        b = self._enc(word)
        if b is not None:
            self._lib.Hunspell_add(self._h, b)
        self.personal.add(word)

    def check(self, word: str) -> bool:
        if not self.available or len(word) > MAX_WORD or word in self.ignored or word in self.personal:
            return True
        if len(word) < 2 or word.isupper():
            return True  # sigles et lettres isolées, comme les options par défaut de Visio
        b = self._enc(word)
        if b is None or self._lib.Hunspell_spell(self._h, b):
            return True
        # Élisions françaises : « l'entreprise », « qu'il »…
        for sep in ("'", "’"):
            if sep in word:
                head, _, tail = word.partition(sep)
                if head.lower() in _ELISIONS and tail and self.check(tail):
                    return True
        if "-" in word:
            return all(self.check(part) for part in word.split("-") if part)
        return False

    def suggest(self, word: str, limit: int = 8) -> list[str]:
        if not self.available or len(word) > MAX_WORD:
            return []
        b = self._enc(word)
        if b is None:
            return []
        lst = ctypes.POINTER(ctypes.c_char_p)()
        n = self._lib.Hunspell_suggest(self._h, ctypes.byref(lst), b)
        out = []
        try:
            for i in range(min(n, limit)):
                raw = lst[i]
                if raw:
                    out.append(raw.decode(self._encoding, "replace"))
        finally:
            if n > 0:
                self._lib.Hunspell_free_list(self._h, ctypes.byref(lst), n)
        return out

    def ignore_all(self, word: str) -> None:
        self.ignored.add(word)

    def add_to_dictionary(self, word: str) -> None:
        word = security.clean_line(word, MAX_WORD)
        if not word or not self.available:
            return
        self._add(word)
        if self.personal_path and len(self.personal) <= MAX_PERSONAL:
            data = "\n".join(sorted(self.personal)) + "\n"
            security.atomic_write(self.personal_path, data.encode("utf-8"), private=True)

    def _read_personal(self) -> list[str]:
        if not self.personal_path or not os.path.isfile(self.personal_path):
            return []
        try:
            raw = security.read_file_limited(self.personal_path, 1_000_000)
        except (OSError, ValueError):
            return []
        words = [security.clean_line(w, MAX_WORD) for w in raw.decode("utf-8", "replace").splitlines()]
        return [w for w in words if w][:MAX_PERSONAL]

    def errors(self, text: str) -> list[tuple[int, int, str]]:
        """Fautes du texte : (début, fin, mot). Les codes de champ {{…}} sont ignorés."""
        out = []
        for m in WORD_RE.finditer(text):
            if text[max(0, m.start() - 2):m.start()] == "{{":
                continue
            if not self.check(m.group(0)):
                out.append((m.start(), m.end(), m.group(0)))
        return out


def _aff_encoding(aff: str) -> str:
    try:
        with open(aff, "rb") as f:
            for _ in range(200):
                line = f.readline()
                if not line:
                    break
                if line.startswith(b"SET "):
                    enc = line[4:].strip().decode("ascii", "replace").lower()
                    return {"iso8859-1": "latin-1", "iso8859-15": "iso8859_15"}.get(enc, enc)
    except OSError:
        pass
    return "utf-8"
