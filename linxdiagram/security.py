"""Primitives de sécurité.

* lecture de fichiers bornée (refus des FIFO, périphériques, fichiers géants) ;
* écriture atomique (fichier temporaire + fsync + rename), droits 0600 par défaut ;
* assainissement des chaînes (caractères de contrôle, surcharges bidi) et des URL ;
* chiffrement authentifié AES-256-GCM (OpenSSL) avec dérivation de clé scrypt.

Aucune de ces fonctions n'exécute de code provenant d'un document : le format
LinXdiagram ne contient ni macros, ni scripts, ni formules.
"""

from __future__ import annotations

import base64
import contextlib
import ctypes
import ctypes.util
import hashlib
import html
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import unicodedata
from urllib.parse import urlsplit


# Drapeaux absents de certains systèmes (Windows n'a ni O_CLOEXEC ni O_NONBLOCK, mais
# exige O_BINARY pour lire les octets tels quels).
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_BINARY = getattr(os, "O_BINARY", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


class SecurityError(Exception):
    """Refus d'une opération jugée dangereuse ; le message est affichable."""


class WrongPasswordError(SecurityError):
    pass


# --------------------------------------------------------------------------- texte

_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_BIDI_RE = re.compile("[‪-‮⁦-⁩⁪-⁯‎‏؜]")
_LINE_RE = re.compile("[\r\n\t]")


def clean_text(value: str, maxlen: int) -> str:
    """Texte multiligne : retire les contrôles et marques bidi, garde \n et \t."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _CONTROL_RE.sub("", value)
    value = _BIDI_RE.sub("", value)
    return value[:maxlen]


def clean_line(value: str, maxlen: int) -> str:
    """Texte sur une ligne (noms, polices, clés) : sans contrôle ni surcharge bidi."""
    value = _LINE_RE.sub(" ", value)
    value = _CONTROL_RE.sub("", value)
    value = _BIDI_RE.sub("", value)
    return value.strip()[:maxlen]


def tooltip_html(value: str, maxlen: int = 5000) -> str:
    """Texte non fiable affichable en infobulle Qt riche sans interpréter son contenu."""
    value = clean_text(value if isinstance(value, str) else str(value), maxlen)
    return "<span>" + html.escape(value, quote=True).replace("\n", "<br/>") + "</span>"


SAFE_URL_SCHEMES = ("http", "https", "mailto")


def safe_url(value: str) -> str | None:
    """Retourne l'URL si elle est sûre à proposer à l'ouverture, sinon None.

    Seuls http, https et mailto sont acceptés : pas de file://, javascript:,
    smb:// ni de schémas de gestionnaires d'applications.
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 2048:
        return None
    if _CONTROL_RE.search(value) or _BIDI_RE.search(value) or any(c.isspace() for c in value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in SAFE_URL_SCHEMES:
        return None
    if scheme in ("http", "https"):
        if not parts.hostname or parts.username is not None or parts.password is not None:
            return None
        try:
            _ = parts.port  # urlsplit diffère la validation du numéro de port à cette propriété.
        except ValueError:
            return None
    return value


# ------------------------------------------------------------------- fichiers

def read_file_limited(path: str, max_bytes: int) -> bytes:
    """Lit un fichier ordinaire d'au plus ``max_bytes`` octets.

    Le contrôle est fait sur le descripteur ouvert (fstat) pour éviter les
    courses entre vérification et ouverture ; O_NONBLOCK empêche un FIFO de
    bloquer l'ouverture.
    """
    flags = os.O_RDONLY | O_CLOEXEC | O_BINARY | _O_NONBLOCK | getattr(os, "O_NOCTTY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise SecurityError(f"Impossible d'ouvrir le fichier : {exc.strerror}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SecurityError("Ce chemin ne désigne pas un fichier ordinaire.")
        if st.st_size > max_bytes:
            raise SecurityError(
                f"Fichier trop volumineux ({st.st_size // (1024 * 1024)} Mo, "
                f"maximum {max_bytes // (1024 * 1024)} Mo).")
        if _O_NONBLOCK:
            os.set_blocking(fd, True)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise SecurityError("Le fichier a grossi pendant la lecture.")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def current_umask() -> int:
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("Umask:"):
                    return int(line.split()[1], 8)
    except (OSError, ValueError):
        pass
    old = os.umask(0o022)
    os.umask(old)
    return old


def _target_mode(path: str, private: bool) -> int:
    try:
        return stat.S_IMODE(os.stat(path).st_mode)  # on conserve les droits existants
    except FileNotFoundError:
        return 0o600 if private else (0o666 & ~current_umask())


def _fsync_dir(directory: str) -> None:
    if not hasattr(os, "O_DIRECTORY"):  # Windows : NTFS journalise le renommage
        return
    try:
        dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


def atomic_write(path: str, data: bytes, private: bool = True) -> None:
    """Écrit ``data`` de façon atomique : jamais de fichier à moitié écrit."""
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    mode = _target_mode(path, private)
    fd, tmp = tempfile.mkstemp(prefix=".~" + os.path.basename(path)[:40] + ".",
                               suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    _fsync_dir(directory)


@contextlib.contextmanager
def atomic_target(path: str, private: bool = False):
    """Fournit un chemin temporaire à remplir (export PDF/SVG/PNG), puis le
    renomme atomiquement vers ``path`` si le bloc se termine sans erreur."""
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    mode = _target_mode(path, private)
    suffix = os.path.splitext(path)[1]
    fd, tmp = tempfile.mkstemp(prefix=".~export.", suffix=suffix, dir=directory)
    os.close(fd)
    try:
        yield tmp
        if os.path.getsize(tmp) == 0:
            raise SecurityError("L'export n'a produit aucune donnée.")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    _fsync_dir(directory)


def private_dir(path: str) -> str:
    """Crée (si besoin) un répertoire accessible au seul utilisateur."""
    os.makedirs(path, mode=0o700, exist_ok=True)
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise SecurityError(f"{path} n'est pas un répertoire sûr.")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise SecurityError(f"{path} appartient à un autre utilisateur.")
    if stat.S_IMODE(st.st_mode) & 0o077:
        os.chmod(path, 0o700)
    return path


def harden_process() -> None:
    """Désactive les core dumps : un document déchiffré ne doit pas finir sur disque."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError):
        pass


# ----------------------------------------------------------------- chiffrement

ENCRYPTED_FORMAT = "linxdiagram-encrypted"
_SCRYPT_N = 2 ** 17
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 320 * 1024 * 1024


def _libcrypto_candidates() -> list[str]:
    """Emplacements possibles de la libcrypto d'OpenSSL 3 selon le système.

    Sous Windows, CPython et les roues PyQt6 livrent ``libcrypto-3*.dll`` ; sous macOS,
    on n'utilise jamais ``/usr/lib/libcrypto.dylib`` (son chargement interrompt le processus).
    """
    out: list[str] = []
    if sys.platform.startswith("win"):
        names = ("libcrypto-3-x64.dll", "libcrypto-3-arm64.dll", "libcrypto-3.dll")
        dirs = [os.path.join(sys.base_prefix, "DLLs"), os.path.dirname(sys.executable)]
        try:
            import PyQt6
            dirs.append(os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "bin"))
        except ImportError:
            pass
        out += [os.path.join(d, n) for d in dirs for n in names]
        out += list(names)
    elif sys.platform == "darwin":
        name = "libcrypto.3.dylib"
        dirs = [os.path.join(sys.base_prefix, "lib"), "/opt/homebrew/opt/openssl@3/lib",
                "/usr/local/opt/openssl@3/lib", "/opt/local/lib"]
        out += [os.path.join(d, name) for d in dirs]
    else:
        found = ctypes.util.find_library("crypto")
        if found:
            out.append(found)
        out += ["libcrypto.so.3", "libcrypto.so"]
    return out


class _CryptographyGCM:
    """AES-256-GCM via le paquet « cryptography » lorsqu'il est installé."""

    def __init__(self) -> None:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self._aesgcm, self._invalid = AESGCM, InvalidTag

    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
        return self._aesgcm(key).encrypt(nonce, plaintext, aad or None)

    def decrypt(self, key: bytes, nonce: bytes, data: bytes, aad: bytes) -> bytes:
        if len(data) < 16:
            raise SecurityError("Données chiffrées tronquées.")
        try:
            return self._aesgcm(key).decrypt(nonce, data, aad or None)
        except self._invalid as exc:
            raise WrongPasswordError("Mot de passe incorrect, ou fichier modifié/corrompu.") from exc


class _OpenSSLGCM:
    """AES-256-GCM via la libcrypto d'OpenSSL (Linux, Windows et macOS)."""

    _SET_IVLEN = 0x9
    _GET_TAG = 0x10
    _SET_TAG = 0x11

    def __init__(self) -> None:
        lib = None
        for name in _libcrypto_candidates():
            if os.path.isabs(name) and not os.path.isfile(name):
                continue
            try:
                lib = ctypes.CDLL(name)
                lib.EVP_aes_256_gcm  # noqa: B018 - vérifie qu'il s'agit bien d'OpenSSL
                break
            except (OSError, AttributeError):
                lib = None
        if lib is None:
            raise OSError("libcrypto introuvable")
        vp, ip, cp = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
        lib.EVP_CIPHER_CTX_new.restype = vp
        lib.EVP_CIPHER_CTX_new.argtypes = []
        lib.EVP_CIPHER_CTX_free.argtypes = [vp]
        lib.EVP_CIPHER_CTX_free.restype = None
        lib.EVP_aes_256_gcm.restype = vp
        lib.EVP_aes_256_gcm.argtypes = []
        for fn in (lib.EVP_EncryptInit_ex, lib.EVP_DecryptInit_ex):
            fn.argtypes = [vp, vp, vp, cp, cp]
            fn.restype = ip
        for fn in (lib.EVP_EncryptUpdate, lib.EVP_DecryptUpdate):
            fn.argtypes = [vp, vp, ctypes.POINTER(ip), cp, ip]
            fn.restype = ip
        for fn in (lib.EVP_EncryptFinal_ex, lib.EVP_DecryptFinal_ex):
            fn.argtypes = [vp, vp, ctypes.POINTER(ip)]
            fn.restype = ip
        lib.EVP_CIPHER_CTX_ctrl.argtypes = [vp, ip, ip, vp]
        lib.EVP_CIPHER_CTX_ctrl.restype = ip
        self.lib = lib

    def _check(self, ok: int, what: str) -> None:
        if ok != 1:
            raise SecurityError(f"Erreur OpenSSL ({what}).")

    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
        lib = self.lib
        ctx = lib.EVP_CIPHER_CTX_new()
        if not ctx:
            raise SecurityError("OpenSSL indisponible.")
        try:
            outl = ctypes.c_int(0)
            self._check(lib.EVP_EncryptInit_ex(ctx, lib.EVP_aes_256_gcm(), None, None, None), "init")
            self._check(lib.EVP_CIPHER_CTX_ctrl(ctx, self._SET_IVLEN, len(nonce), None), "iv")
            self._check(lib.EVP_EncryptInit_ex(ctx, None, None, key, nonce), "clé")
            if aad:
                self._check(lib.EVP_EncryptUpdate(ctx, None, ctypes.byref(outl), aad, len(aad)), "aad")
            buf = ctypes.create_string_buffer(len(plaintext) + 32)
            self._check(lib.EVP_EncryptUpdate(ctx, buf, ctypes.byref(outl), plaintext,
                                              len(plaintext)), "chiffrement")
            n = outl.value
            self._check(lib.EVP_EncryptFinal_ex(ctx, ctypes.addressof(buf) + n,
                                                ctypes.byref(outl)), "final")
            n += outl.value
            tag = ctypes.create_string_buffer(16)
            self._check(lib.EVP_CIPHER_CTX_ctrl(ctx, self._GET_TAG, 16, tag), "tag")
            return buf.raw[:n] + tag.raw
        finally:
            lib.EVP_CIPHER_CTX_free(ctx)

    def decrypt(self, key: bytes, nonce: bytes, data: bytes, aad: bytes) -> bytes:
        if len(data) < 16:
            raise SecurityError("Données chiffrées tronquées.")
        lib = self.lib
        ciphertext, tag = data[:-16], data[-16:]
        ctx = lib.EVP_CIPHER_CTX_new()
        if not ctx:
            raise SecurityError("OpenSSL indisponible.")
        try:
            outl = ctypes.c_int(0)
            self._check(lib.EVP_DecryptInit_ex(ctx, lib.EVP_aes_256_gcm(), None, None, None), "init")
            self._check(lib.EVP_CIPHER_CTX_ctrl(ctx, self._SET_IVLEN, len(nonce), None), "iv")
            self._check(lib.EVP_DecryptInit_ex(ctx, None, None, key, nonce), "clé")
            if aad:
                self._check(lib.EVP_DecryptUpdate(ctx, None, ctypes.byref(outl), aad, len(aad)), "aad")
            buf = ctypes.create_string_buffer(len(ciphertext) + 32)
            self._check(lib.EVP_DecryptUpdate(ctx, buf, ctypes.byref(outl), ciphertext,
                                              len(ciphertext)), "déchiffrement")
            n = outl.value
            tag_buf = ctypes.create_string_buffer(tag, 16)
            self._check(lib.EVP_CIPHER_CTX_ctrl(ctx, self._SET_TAG, 16, tag_buf), "tag")
            if lib.EVP_DecryptFinal_ex(ctx, ctypes.addressof(buf) + n, ctypes.byref(outl)) <= 0:
                raise WrongPasswordError(
                    "Mot de passe incorrect, ou fichier modifié/corrompu.")
            n += outl.value
            return buf.raw[:n]
        finally:
            lib.EVP_CIPHER_CTX_free(ctx)


_gcm: _OpenSSLGCM | _CryptographyGCM | None = None


def _cipher() -> _OpenSSLGCM | _CryptographyGCM:
    global _gcm
    if _gcm is None:
        try:
            _gcm = _OpenSSLGCM()
        except (OSError, AttributeError):
            try:
                _gcm = _CryptographyGCM()
            except ImportError as exc:
                raise SecurityError("Le chiffrement nécessite OpenSSL (libcrypto) ou le paquet "
                                    "Python « cryptography ».") from exc
    return _gcm


def encryption_available() -> bool:
    try:
        _cipher()
        return True
    except SecurityError:
        return False


def _derive_key(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    pw = unicodedata.normalize("NFC", password).encode("utf-8")
    if len(pw) > 4096:
        raise SecurityError("Le mot de passe dépasse la limite de 4 096 octets.")
    return hashlib.scrypt(pw, salt=salt, n=n, r=r, p=p, maxmem=_SCRYPT_MAXMEM, dklen=32)


def _aad(header: dict) -> bytes:
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")


def encrypt_payload(plaintext: bytes, password: str) -> bytes:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    header = {
        "format": ENCRYPTED_FORMAT, "version": 1, "cipher": "AES-256-GCM", "kdf": "scrypt",
        "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }
    key = _derive_key(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    data = _cipher().encrypt(key, nonce, plaintext, _aad(header))
    envelope = dict(header)
    envelope["data"] = base64.b64encode(data).decode("ascii")
    return json.dumps(envelope, indent=1).encode("utf-8")


def is_encrypted_envelope(obj: object) -> bool:
    return isinstance(obj, dict) and obj.get("format") == ENCRYPTED_FORMAT


def decrypt_payload(envelope: dict, password: str) -> bytes:
    try:
        header = {k: envelope[k] for k in
                  ("format", "version", "cipher", "kdf", "n", "r", "p", "salt", "nonce")}
        version = header["version"]
        if (not isinstance(version, int) or isinstance(version, bool) or version != 1
                or header["cipher"] != "AES-256-GCM" or header["kdf"] != "scrypt"):
            raise SecurityError("Méthode de chiffrement non prise en charge.")
        n, r, p = header["n"], header["r"], header["p"]
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (n, r, p)):
            raise SecurityError("Paramètres de chiffrement invalides.")
        # Bornes : un fichier piégé ne doit pas pouvoir épuiser la mémoire.
        if not (2 ** 14 <= n <= 2 ** 18 and n & (n - 1) == 0 and 1 <= r <= 8 and 1 <= p <= 2
                and 128 * n * r <= 256 * 1024 * 1024):
            raise SecurityError("Paramètres de dérivation de clé hors limites.")
        if (not isinstance(header["salt"], str) or len(header["salt"]) != 24
                or not isinstance(header["nonce"], str) or len(header["nonce"]) != 16
                or not isinstance(envelope["data"], str)):
            raise SecurityError("Enveloppe chiffrée invalide.")
        salt = base64.b64decode(header["salt"], validate=True)
        nonce = base64.b64decode(header["nonce"], validate=True)
        data = base64.b64decode(envelope["data"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise SecurityError("Enveloppe chiffrée invalide.") from exc
    if len(salt) != 16 or len(nonce) != 12:
        raise SecurityError("Enveloppe chiffrée invalide.")
    key = _derive_key(password, salt, n, r, p)
    return _cipher().decrypt(key, nonce, data, _aad(header))


def password_strength(password: str) -> tuple[int, str]:
    """Estimation simple (0-4) affichée lors du choix d'un mot de passe."""
    if not password:
        return 0, "Vide"
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w]"))
    length = len(password)
    score = 0
    if length >= 8:
        score += 1
    if length >= 12:
        score += 1
    if length >= 16:
        score += 1
    if classes >= 3:
        score += 1
    score = min(score, 4)
    return score, ("Très faible", "Faible", "Moyen", "Bon", "Excellent")[score]
