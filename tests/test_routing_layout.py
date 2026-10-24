import unittest

from linxdiagram.layout import layered_layout
from linxdiagram.routing import route_orthogonal, simplify


def _orthogonal(points):
    return all(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6 for a, b in zip(points, points[1:]))


class RoutingTest(unittest.TestCase):
    CASES = [
        ((100, 50), (0, 1), (100, 200), (0, -1)),      # alignés verticalement
        ((100, 50), (1, 0), (300, 200), (-1, 0)),      # en escalier
        ((100, 50), (0, 1), (300, 200), (-1, 0)),      # un coude
        ((300, 50), (1, 0), (100, 200), (1, 0)),       # retour en arrière
        ((100, 100), (0, -1), (100, 300), (0, 1)),     # sorties opposées
        ((100, 100), None, (250, 180), None),          # extrémités libres
    ]

    def test_routes_are_orthogonal_and_connect(self):
        for p1, d1, p2, d2 in self.CASES:
            pts = route_orthogonal(p1, d1, p2, d2)
            self.assertEqual(pts[0], p1)
            self.assertEqual(pts[-1], p2)
            self.assertTrue(_orthogonal(pts), (p1, d1, p2, d2, pts))

    def test_ports_left_and_entered_perpendicularly(self):
        for p1, d1, p2, d2 in self.CASES[:5]:
            pts = route_orthogonal(p1, d1, p2, d2)
            first = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            last = (pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
            self.assertGreater(first[0] * d1[0] + first[1] * d1[1], 0, pts)
            self.assertLess(last[0] * d2[0] + last[1] * d2[1], 0, pts)

    def test_avoids_shapes(self):
        r1 = (0, 0, 100, 60)
        r2 = (300, 0, 400, 60)
        pts = route_orthogonal((50, 60), (0, 1), (350, 60), (0, 1), r1, r2)
        for a, b in zip(pts, pts[1:]):
            if abs(a[1] - b[1]) < 1e-6:
                self.assertGreater(a[1], 60, "ne doit pas traverser les formes")

    def test_simplify(self):
        self.assertEqual(simplify([(0, 0), (0, 0), (5, 0), (10, 0), (10, 5)]), [(0, 0), (10, 0), (10, 5)])


class LayoutTest(unittest.TestCase):
    def test_tree_top_to_bottom(self):
        nodes = [(k, 0.0, 0.0, 80.0, 40.0) for k in "abcd"]
        pos = layered_layout(nodes, [("a", "b"), ("a", "c"), ("c", "d")], "TB")
        self.assertLess(pos["a"][1], pos["b"][1])
        self.assertLess(pos["c"][1], pos["d"][1])
        self.assertAlmostEqual(pos["b"][1], pos["c"][1])
        self.assertNotAlmostEqual(pos["b"][0], pos["c"][0])

    def test_cycles_and_isolated(self):
        nodes = [(k, float(i * 10), 0.0, 50.0, 30.0) for i, k in enumerate("abcx")]
        pos = layered_layout(nodes, [("a", "b"), ("b", "c"), ("c", "a")], "LR")
        self.assertEqual(set(pos), set("abcx"))
        self.assertLess(pos["a"][0], pos["b"][0])


if __name__ == "__main__":
    unittest.main()
