import json
import os
import stat
import sys
import tempfile
import unittest

POSIX_ONLY = unittest.skipIf(sys.platform.startswith("win"),
                             "droits Unix, FIFO et /dev absents sous Windows")

from linxdiagram import security


class CryptoTest(unittest.TestCase):
    def test_aes_gcm_nist_vector(self):
        # Cas de test 16 de la spécification GCM (McGrew & Viega).
        key = bytes.fromhex("feffe9928665731c6d6a8f9467308308feffe9928665731c6d6a8f9467308308")
        iv = bytes.fromhex("cafebabefacedbaddecaf888")
        pt = bytes.fromhex("d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
                           "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39")
        aad = bytes.fromhex("feedfacedeadbeeffeedfacedeadbeefabaddad2")
        out = security._cipher().encrypt(key, iv, pt, aad)
        self.assertEqual(out[:-16].hex(), "522dc1f099567d07f47f37a32a84427d643a8cdcbfe5c0c97598a2bd2555d1aa"
                                          "8cb08e48590dbb3da7b08b1056828838c5f61e6393ba7a0abcc9f662")
        self.assertEqual(out[-16:].hex(), "76fc6ece0f4e1768cddf8853bb2d551b")
        self.assertEqual(security._cipher().decrypt(key, iv, out, aad), pt)

    def test_roundtrip_and_wrong_password(self):
        env = json.loads(security.encrypt_payload(b"secret diagram", "correct horse"))
        self.assertNotIn("secret", json.dumps(env))
        self.assertEqual(security.decrypt_payload(env, "correct horse"), b"secret diagram")
        with self.assertRaises(security.WrongPasswordError):
            security.decrypt_payload(env, "wrong")

    def test_tampering_detected(self):
        env = json.loads(security.encrypt_payload(b"payload", "pw12345678"))
        data = bytearray(security.base64.b64decode(env["data"]))
        data[0] ^= 1
        env["data"] = security.base64.b64encode(bytes(data)).decode()
        with self.assertRaises(security.WrongPasswordError):
            security.decrypt_payload(env, "pw12345678")

    def test_header_is_authenticated(self):
        env = json.loads(security.encrypt_payload(b"payload", "pw12345678"))
        env["r"] = 7  # paramètre modifié : la clé et l'AAD changent
        with self.assertRaises(security.SecurityError):
            security.decrypt_payload(env, "pw12345678")

    def test_kdf_bounds_refused(self):
        env = json.loads(security.encrypt_payload(b"x", "pw12345678"))
        env["n"] = 2 ** 30  # tentative d'épuisement mémoire
        with self.assertRaises(security.SecurityError):
            security.decrypt_payload(env, "pw12345678")


class SanitizeTest(unittest.TestCase):
    def test_safe_url(self):
        self.assertEqual(security.safe_url("https://exemple.fr/a?b=1"), "https://exemple.fr/a?b=1")
        self.assertEqual(security.safe_url("mailto:a@b.fr"), "mailto:a@b.fr")
        for bad in ("javascript:alert(1)", "file:///etc/passwd", "smb://x/y", "http://",
                    "https://exa mple.fr", "https://e.fr/‮gnp.exe", "data:text/html,x", ""):
            self.assertIsNone(security.safe_url(bad), bad)

    def test_clean_line_removes_bidi_and_controls(self):
        self.assertEqual(security.clean_line("a‮b\x00c\nd", 50), "abc d")

    def test_clean_text_keeps_newlines(self):
        self.assertEqual(security.clean_text("a\r\nb\x07c", 50), "a\nbc")

    def test_password_strength(self):
        self.assertLess(security.password_strength("abc")[0], 2)
        self.assertGreaterEqual(security.password_strength("Tr0ub4dor&3-horse!")[0], 3)


class FileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    @POSIX_ONLY
    def test_atomic_write_private_by_default(self):
        p = os.path.join(self.dir, "a.lxd")
        security.atomic_write(p, b"hello")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        os.chmod(p, 0o640)
        security.atomic_write(p, b"world")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"world")
        self.assertEqual(os.listdir(self.dir), ["a.lxd"])

    @POSIX_ONLY
    def test_read_limited_rejects_big_and_special_files(self):
        p = os.path.join(self.dir, "big")
        with open(p, "wb") as f:
            f.write(b"x" * 2000)
        with self.assertRaises(security.SecurityError):
            security.read_file_limited(p, 1000)
        fifo = os.path.join(self.dir, "fifo")
        os.mkfifo(fifo)
        with self.assertRaises(security.SecurityError):
            security.read_file_limited(fifo, 1000)
        with self.assertRaises(security.SecurityError):
            security.read_file_limited("/dev/zero", 1000)

    @POSIX_ONLY
    def test_private_dir(self):
        d = security.private_dir(os.path.join(self.dir, "priv"))
        self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)
        link = os.path.join(self.dir, "lnk")
        os.symlink(d, link)
        with self.assertRaises(security.SecurityError):
            security.private_dir(link)


if __name__ == "__main__":
    unittest.main()
