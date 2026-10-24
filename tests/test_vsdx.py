import io
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile


from tests.helpers import qapp

from linxdiagram import templates, vsdx
from linxdiagram.document import Document

NS = 'xmlns="http://schemas.microsoft.com/office/visio/2012/main" ' \
     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
RELS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
VREL = "http://schemas.microsoft.com/visio/2010/relationships/"


def _rels(*entries):
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{g}"{m}/>' for i, t, g, m in entries)
    return f'<?xml version="1.0"?><Relationships {RELS}>{body}</Relationships>'


def cell(n, v, f=None):
    return f'<Cell N="{n}" V="{v}"' + (f' F="{f}"' if f else "") + "/>"


def build_vsdx(page_xml: str, document_xml: str | None = None, page_target="page1.xml",
               extra: dict | None = None) -> bytes:
    """Fabrique un paquet .vsdx minimal, à la manière de Visio (formes maîtres, styles)."""
    document_xml = document_xml or (
        f'<?xml version="1.0"?><VisioDocument {NS}><FaceNames><FaceName ID="1" NameU="Arial"/>'
        '</FaceNames><StyleSheets><StyleSheet ID="0" NameU="No Style">'
        + cell("LineWeight", "0.01") + cell("LineColor", "0") + cell("LinePattern", "1")
        + cell("FillForegnd", "1") + cell("FillPattern", "1")
        + '</StyleSheet></StyleSheets></VisioDocument>')
    master = (
        f'<?xml version="1.0"?><MasterContents {NS}><Shapes><Shape ID="5" Type="Shape">'
        + cell("Width", "1") + cell("Height", "0.75") + cell("FillForegnd", "#ff0000")
        + '<Section N="Geometry" IX="0">'
        + '<Row T="MoveTo" IX="1">' + cell("X", "0") + cell("Y", "0") + '</Row>'
        + '<Row T="LineTo" IX="2">' + cell("X", "1", "Width") + cell("Y", "0") + '</Row>'
        + '<Row T="LineTo" IX="3">' + cell("X", "1", "Width") + cell("Y", "0.75", "Height") + '</Row>'
        + '<Row T="LineTo" IX="4">' + cell("X", "0") + cell("Y", "0.75", "Height") + '</Row>'
        + '<Row T="LineTo" IX="5">' + cell("X", "0") + cell("Y", "0") + '</Row>'
        + '</Section><Text>Défaut</Text></Shape></Shapes></MasterContents>')
    files = {
        "[Content_Types].xml": "<Types/>",
        "_rels/.rels": _rels(("rId1", VREL + "document", "visio/document.xml", "")),
        "visio/document.xml": document_xml,
        "visio/_rels/document.xml.rels": _rels(("rId1", VREL + "pages", "pages/pages.xml", ""),
                                               ("rId2", VREL + "masters", "masters/masters.xml", "")),
        "visio/masters/masters.xml": f'<?xml version="1.0"?><Masters {NS}><Master ID="2" '
                                     'NameU="Process"><Rel r:id="rId1"/></Master></Masters>',
        "visio/masters/_rels/masters.xml.rels": _rels(("rId1", VREL + "master", "master1.xml", "")),
        "visio/masters/master1.xml": master,
        "visio/pages/pages.xml": f'<?xml version="1.0"?><Pages {NS}><Page ID="0" Name="Ma page">'
                                 '<PageSheet>' + cell("PageWidth", "11") + cell("PageHeight", "8.5")
                                 + '</PageSheet><Rel r:id="rId1"/></Page></Pages>',
        "visio/pages/_rels/pages.xml.rels": _rels(("rId1", VREL + "page", page_target, "")),
        "visio/pages/page1.xml": page_xml,
    }
    files.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content if isinstance(content, bytes) else content.encode("utf-8"))
    return buf.getvalue()


PAGE = (
    f'<?xml version="1.0"?><PageContents {NS}><Shapes>'
    # instance de la forme maître, agrandie : la géométrie héritée doit suivre
    '<Shape ID="1" Master="2">' + cell("PinX", "2") + cell("PinY", "6") + cell("Width", "2")
    + cell("Height", "1") + '<Text>Étape 1</Text></Shape>'
    # forme propre : arc, texte formaté, données, lien
    '<Shape ID="2" Type="Shape">' + cell("PinX", "6") + cell("PinY", "6") + cell("Width", "2")
    + cell("Height", "1") + cell("FillForegnd", "#00ff00")
    + '<Section N="Character"><Row IX="0">' + cell("Size", "0.1666667") + cell("Color", "#0000ff")
    + cell("Style", "1") + cell("Font", "1") + '</Row></Section>'
    + '<Section N="Property"><Row N="Cout">' + cell("Label", "Coût") + cell("Value", "12")
    + '</Row></Section><Section N="Hyperlink"><Row N="Row_1">' + cell("Address", "https://exemple.fr")
    + '</Row></Section><Section N="Geometry" IX="0">'
    + '<Row T="MoveTo" IX="1">' + cell("X", "0") + cell("Y", "0.5") + '</Row>'
    + '<Row T="ArcTo" IX="2">' + cell("X", "2") + cell("Y", "0.5") + cell("A", "0.5") + '</Row>'
    + '<Row T="EllipticalArcTo" IX="3">' + cell("X", "0") + cell("Y", "0.5") + cell("A", "1")
    + cell("B", "1") + cell("C", "0") + cell("D", "1") + '</Row>'
    + '</Section><Text>Arc</Text></Shape>'
    # groupe contenant deux formes, coordonnées locales au groupe
    '<Shape ID="3" Type="Group">' + cell("PinX", "4") + cell("PinY", "3") + cell("Width", "2")
    + cell("Height", "2") + cell("LocPinX", "1") + cell("LocPinY", "1") + '<Shapes>'
    + '<Shape ID="4" Type="Shape">' + cell("PinX", "0.5") + cell("PinY", "0.5") + cell("Width", "0.5")
    + cell("Height", "0.5") + '<Section N="Geometry" IX="0"><Row T="Ellipse" IX="1">'
    + cell("X", "0.25") + cell("Y", "0.25") + cell("A", "0.5") + cell("B", "0.25") + cell("C", "0.25")
    + cell("D", "0.5") + '</Row></Section></Shape>'
    + '<Shape ID="7" Type="Shape">' + cell("PinX", "1.5") + cell("PinY", "1.5") + cell("Width", "0.5")
    + cell("Height", "0.5") + '<Text>B</Text></Shape>'
    + '</Shapes></Shape>'
    # connecteur 1-D collé aux formes 1 et 2
    '<Shape ID="6" Type="Shape" NameU="Dynamic connector">' + cell("BeginX", "3") + cell("BeginY", "6")
    + cell("EndX", "5") + cell("EndY", "6") + cell("EndArrow", "4") + '<Text>oui</Text></Shape>'
    '</Shapes><Connects>'
    '<Connect FromSheet="6" FromCell="BeginX" ToSheet="1" ToCell="PinX"/>'
    '<Connect FromSheet="6" FromCell="EndX" ToSheet="2" ToCell="PinX"/>'
    '</Connects></PageContents>')


class VsdxImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp()

    def test_visio_like_document(self):
        doc, warnings = vsdx.import_vsdx_bytes(build_vsdx(PAGE))
        page = doc["pages"][0]
        self.assertEqual(page["name"], "Ma page")
        self.assertAlmostEqual(page["width"], 11 * 96)
        shapes = {s["text"]: s for s in page["shapes"]}
        inst = shapes["Étape 1"]
        self.assertEqual(inst["style"]["fill"], "#ff0000")  # hérité du maître
        self.assertAlmostEqual(inst["w"], 2 * 96)
        xs = [c[1] for c in inst["path"] if c[0] in "ML"]
        self.assertAlmostEqual(max(xs), 1.0)  # géométrie du maître remise à l'échelle
        arc = shapes["Arc"]
        self.assertEqual(arc["text_style"]["color"], "#0000ff")
        self.assertTrue(arc["text_style"]["bold"])
        self.assertAlmostEqual(arc["text_style"]["size"], 12, places=1)
        self.assertEqual(arc["text_style"]["font"], "Arial")
        self.assertEqual(arc["data"], {"Coût": "12"})
        self.assertEqual(arc["link"], "https://exemple.fr")
        ys = [v for c in arc["path"] if c[0] == "C" for v in c[2::2]]
        # bombement positif à droite du sens de parcours (sous la corde) : y normalisé > 0,5
        self.assertGreater(max(ys), 0.9)
        # l'arc elliptique passe par (1, 1) en repère Visio, soit le haut de la boîte
        self.assertLess(min(ys), 0.1)
        groups = {s["group"] for s in page["shapes"] if s["group"]}
        self.assertEqual(len(groups), 1)
        ellipse = next(s for s in page["shapes"] if s["group"] and s["text"] == "")
        self.assertAlmostEqual(ellipse["x"], 3.5 * 96)
        self.assertAlmostEqual(ellipse["y"], (8.5 - 2.5) * 96)
        conn = page["connectors"][0]
        self.assertEqual(conn["text"], "oui")
        self.assertEqual(conn["style"]["arrow_end"], "triangle")
        self.assertEqual(conn["src"]["shape"], inst["id"])
        self.assertEqual(conn["dst"]["shape"], arc["id"])
        self.assertTrue(any("formules" in w for w in warnings))
        Document(doc)  # le document importé s'ouvre dans l'éditeur

    def test_rejects_xxe(self):
        evil = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
                f'<PageContents {NS}><Shapes/></PageContents>')
        with self.assertRaises(vsdx.VsdxError):
            vsdx.import_vsdx_bytes(build_vsdx(evil))

    def test_rejects_zip_bomb(self):
        bomb = b"<a>" + b" " * (3 * 1024 * 1024) + b"</a>"
        with self.assertRaises(vsdx.VsdxError):
            vsdx.import_vsdx_bytes(build_vsdx(PAGE, extra={"visio/pages/page1.xml": bomb}))

    def test_ignores_traversal_and_external_targets(self):
        data = build_vsdx(PAGE, page_target="../../../../etc/passwd")
        doc, _ = vsdx.import_vsdx_bytes(data)
        self.assertEqual(doc["pages"][0]["shapes"], [])

    def test_not_a_zip(self):
        with self.assertRaises(vsdx.VsdxError):
            vsdx.import_vsdx_bytes(b"MZ\x90\x00 pas un zip")


class VsdxRoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp()

    def test_export_then_import(self):
        doc = Document(templates.build("sample"))
        doc.pages[0].item_by_id("s2").link = "https://exemple.fr/doc"
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "flux.vsdx")
        vsdx.export_vsdx(doc, path)
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        for part in ("[Content_Types].xml", "_rels/.rels", "visio/document.xml",
                     "visio/pages/pages.xml", "visio/pages/page1.xml"):
            self.assertIn(part, names)
        data, _warnings = vsdx.import_vsdx(path)
        page = data["pages"][0]
        by_text = {s["text"]: s for s in page["shapes"]}
        self.assertEqual(by_text["Article en stock ?"]["type"], "flow.decision")
        self.assertEqual(by_text["Vérifier le stock"]["link"], "https://exemple.fr/doc")
        self.assertEqual(by_text["Facture"]["data"], {"Montant": "149,90 €", "TVA": "20 %"})
        glued = [c for c in page["connectors"] if c["src"]["shape"] and c["dst"]["shape"]]
        self.assertEqual(len(glued), 8)
        self.assertEqual(sorted(c["text"] for c in page["connectors"] if c["text"]), ["Non", "Oui"])

    @unittest.skipUnless(shutil.which("soffice") and os.environ.get("LINX_TEST_LIBREOFFICE"),
                         "LibreOffice non demandé (LINX_TEST_LIBREOFFICE=1)")
    def test_libreoffice_opens_export(self):
        doc = Document(templates.build("sample"))
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "lo.vsdx")
        vsdx.export_vsdx(doc, path)
        subprocess.run(["soffice", f"-env:UserInstallation=file://{tmp}/profile", "--headless",
                        "--convert-to", "pdf", "--outdir", tmp, path], check=True, timeout=180,
                       capture_output=True)
        self.assertTrue(os.path.getsize(os.path.join(tmp, "lo.pdf")) > 1000)


if __name__ == "__main__":
    unittest.main()
