import json
import os
import tempfile
import unittest

from PyQt6.QtCore import QPointF

from tests.helpers import qapp

from linxdiagram import fileformat, templates
from linxdiagram.document import Document


def _raw(pages):
    return {"format": "linxdiagram", "version": 1, "pages": pages}


def _shape(sid="a", **extra):
    s = {"id": sid, "type": "flow.process", "x": 100, "y": 100, "w": 120, "h": 60, "text": "t"}
    s.update(extra)
    return s


class FileFormatTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp()

    def test_roundtrip_plain_and_encrypted(self):
        doc = Document(templates.build("sample"))
        d = tempfile.mkdtemp()
        for pw in (None, "motdepasse-solide"):
            doc.password = pw
            path = os.path.join(d, f"x{bool(pw)}.lxd")
            doc.save(path)
            data, warnings, got_pw = fileformat.load_file(path, (lambda: pw) if pw else None)
            self.assertEqual(warnings, [])
            self.assertEqual(got_pw, pw)
            page = data["pages"][0]
            self.assertEqual(len(page["shapes"]), 10)
            self.assertEqual(len(page["connectors"]), 8)
            with open(path, "rb") as f:
                raw = f.read()
            self.assertEqual(b"Commande" in raw, pw is None)

    def test_encrypted_requires_password(self):
        doc = Document()
        doc.password = "motdepasse-solide"
        data = fileformat.dump_bytes(doc.to_dict(), doc.password)
        with self.assertRaises(fileformat.PasswordRequired):
            fileformat.load_bytes(data)
        with self.assertRaises(fileformat.PasswordRequired):
            fileformat.load_bytes(data, lambda: None)

    def test_rejects_non_json_constants_and_duplicates(self):
        for bad in (b'{"format": "linxdiagram", "version": 1, "x": NaN}',
                    b'{"format": "linxdiagram", "format": "linxdiagram", "version": 1}',
                    b"\xff\xfe", b"[" * 100000, b"not json"):
            with self.assertRaises(fileformat.DocumentError):
                fileformat.load_bytes(bad)

    def test_rejects_foreign_or_future_documents(self):
        with self.assertRaises(fileformat.DocumentError):
            fileformat.validate_document({"format": "other", "version": 1, "pages": []})
        with self.assertRaises(fileformat.DocumentError):
            fileformat.validate_document({"format": "linxdiagram", "version": 99, "pages": [{}]})

    def test_sanitizes_values(self):
        doc, warnings = fileformat.validate_document(_raw([{
            "name": "P‮1", "shapes": [
                _shape("a", x=1e12, w=-5, link="javascript:alert(1)",
                       style={"fill": "red; background:url(x)", "line_width": 1e9},
                       text_style={"font": "Evil\nFont", "size": "12"}, evil="ignored"),
                _shape("b", type="does.not.exist"),
            ],
            "connectors": [{"id": "c", "src": {"shape": "ghost"}, "dst": {"shape": "a", "port": 2}}],
        }]))
        page = doc["pages"][0]
        a, b = page["shapes"]
        self.assertEqual(page["name"], "P1")
        self.assertLessEqual(a["x"], 1e6)
        self.assertGreaterEqual(a["w"], 1)
        self.assertEqual(a["link"], "")
        self.assertEqual(a["style"]["fill"], "#5b9bd5")
        self.assertLessEqual(a["style"]["line_width"], 50)
        self.assertEqual(a["text_style"]["font"], "Evil Font")
        self.assertNotIn("evil", a)
        self.assertEqual(b["type"], "basic.rectangle")
        self.assertTrue(any("inconnu" in w for w in warnings))
        c = page["connectors"][0]
        self.assertEqual(c["src"]["shape"], "")
        self.assertEqual(c["dst"]["shape"], "a")

    def test_image_whitelist(self):
        svg = fileformat.base64.b64encode(b"<svg onload=alert(1)>").decode()
        with self.assertRaises(fileformat.DocumentError):
            fileformat.validate_document(_raw([{"shapes": [
                _shape("i", type="special.image", image=svg)], "connectors": []}]))

    def test_limits(self):
        many = [_shape(f"s{i}") for i in range(fileformat.MAX_ITEMS_PER_PAGE + 1)]
        with self.assertRaises(fileformat.DocumentError):
            fileformat.validate_document(_raw([{"shapes": many, "connectors": []}]))

    def test_integrity_warning(self):
        doc = Document()
        doc.pages[0].add_shape("flow.process", QPointF(100, 100))
        obj = json.loads(fileformat.dump_bytes(doc.to_dict()))
        obj["pages"][0]["shapes"][0]["text"] = "modifié à la main"
        _doc, warnings = fileformat.validate_document(obj)
        self.assertTrue(any("intégrité" in w for w in warnings))

    def test_clipboard_roundtrip(self):
        doc = Document(templates.build("sample"))
        sc = doc.pages[0]
        sc.select_all()
        data = sc.copy_selection()
        shapes, conns = fileformat.load_clip(data, "office", "orthogonal")
        self.assertEqual(len(shapes), 10)
        self.assertEqual(len(conns), 8)
        with self.assertRaises(fileformat.DocumentError):
            fileformat.load_clip(b'{"format": "autre"}', "office", "orthogonal")


if __name__ == "__main__":
    unittest.main()
