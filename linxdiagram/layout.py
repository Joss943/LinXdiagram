"""Disposition automatique (« Redisposer la page » de Visio).

Algorithme en couches simplifié (Sugiyama) : suppression des cycles, couches
par plus long chemin, ordonnancement par barycentres, puis placement.
"""

from __future__ import annotations

from collections import defaultdict

Node = tuple[str, float, float, float, float]  # id, x centre, y centre, largeur, hauteur


def layered_layout(nodes: list[Node], edges: list[tuple[str, str]], direction: str = "TB",
                   gap_major: float = 60.0, gap_minor: float = 40.0) -> dict[str, tuple[float, float]]:
    """Retourne la nouvelle position (centre) de chaque nœud.

    ``direction`` : "TB" (haut → bas) ou "LR" (gauche → droite).
    """
    if not nodes:
        return {}
    info = {n[0]: n for n in nodes}
    succ: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        if a in info and b in info and a != b and b not in succ[a]:
            succ[a].append(b)

    # 1. Suppression des cycles par parcours en profondeur (arêtes arrière ignorées).
    state: dict[str, int] = {}
    dag: dict[str, list[str]] = defaultdict(list)
    order_key = sorted(info, key=lambda k: (info[k][2], info[k][1]) if direction == "TB"
                       else (info[k][1], info[k][2]))
    for root in order_key:
        if root in state:
            continue
        stack = [(root, iter(succ[root]))]
        state[root] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
                continue
            if state.get(nxt) == 1:
                continue  # arête arrière : cycle
            dag[node].append(nxt)
            if nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(succ[nxt])))

    preds: dict[str, list[str]] = defaultdict(list)
    for a, outs in dag.items():
        for b in outs:
            preds[b].append(a)

    connected = {a for a in dag if dag[a]} | set(preds)
    isolated = [k for k in order_key if k not in connected]

    # 2. Couches par plus long chemin (ordre topologique).
    indeg = {k: len(preds[k]) for k in connected}
    queue = [k for k in order_key if k in connected and indeg[k] == 0]
    layer: dict[str, int] = {k: 0 for k in queue}
    topo = []
    while queue:
        k = queue.pop(0)
        topo.append(k)
        for b in dag[k]:
            layer[b] = max(layer.get(b, 0), layer[k] + 1)
            indeg[b] -= 1
            if indeg[b] == 0:
                queue.append(b)
    layers: dict[int, list[str]] = defaultdict(list)
    for k in topo:
        layers[layer[k]].append(k)
    if isolated:
        layers[(max(layers) + 1) if layers else 0].extend(isolated)

    # 3. Ordonnancement par barycentres (quelques balayages).
    def pos_key(k):
        return info[k][1] if direction == "TB" else info[k][2]

    ranks = sorted(layers)
    for r in ranks:
        layers[r].sort(key=pos_key)
    for _ in range(4):
        for seq, neigh in ((ranks[1:], preds), (list(reversed(ranks[:-1])), dag)):
            for r in seq:
                index = {}
                for rr in ranks:
                    for i, k in enumerate(layers[rr]):
                        index[k] = i
                def bary(k):
                    ns = [index[n] for n in neigh.get(k, []) if n in index]
                    return sum(ns) / len(ns) if ns else index[k]
                layers[r].sort(key=bary)

    # 4. Placement.
    def along(k):  # dimension dans l'axe principal
        return info[k][4] if direction == "TB" else info[k][3]

    def across(k):
        return info[k][3] if direction == "TB" else info[k][4]

    xs = [n[1] - n[3] / 2 for n in nodes]
    ys = [n[2] - n[4] / 2 for n in nodes]
    origin_major = min(ys) if direction == "TB" else min(xs)
    origin_minor_center = (min(xs) + max(n[1] + n[3] / 2 for n in nodes)) / 2 if direction == "TB" \
        else (min(ys) + max(n[2] + n[4] / 2 for n in nodes)) / 2

    result: dict[str, tuple[float, float]] = {}
    major = origin_major
    for r in ranks:
        keys = layers[r]
        if not keys:
            continue
        thickness = max(along(k) for k in keys)
        total = sum(across(k) for k in keys) + gap_minor * (len(keys) - 1)
        minor = origin_minor_center - total / 2
        for k in keys:
            c_minor = minor + across(k) / 2
            c_major = major + thickness / 2
            result[k] = (c_minor, c_major) if direction == "TB" else (c_major, c_minor)
            minor += across(k) + gap_minor
        major += thickness + gap_major
    return result
