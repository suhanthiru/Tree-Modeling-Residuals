"""Convert a BioDiv-3DTrees GraphML tree graph into a cylinder table.

Graph nodes carry pos_x/pos_y/pos_z and radius; edges are undirected. We root the graph at its
lowest node, orient edges away from the root, and make one cylinder per edge (radius of the
child node). Branches are decomposed like TreeQSM: at each fork the child with the largest
downstream volume continues the parent branch, the others start new branches one order higher.
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

from treewm.io.treeqsm_mat import CYLINDER_COLUMNS


def graph_to_cylinders(path: str | Path) -> pd.DataFrame:
    g = nx.read_graphml(str(path))
    if g.number_of_nodes() < 2:
        raise ValueError(f"{path}: graph has fewer than two nodes")
    nodes = list(g.nodes)
    idx = {n: i for i, n in enumerate(nodes)}
    pos = np.array([[float(g.nodes[n]["pos_x"]), float(g.nodes[n]["pos_y"]), float(g.nodes[n]["pos_z"])] for n in nodes])
    rad = np.array([float(g.nodes[n].get("radius", 0.0)) for n in nodes])
    # keep the component containing the lowest node
    root = nodes[int(np.argmin(pos[:, 2]))]
    comp = nx.node_connected_component(g, root)
    tree = nx.bfs_tree(g.subgraph(comp), root)  # directed, parent -> child

    order_nodes = list(nx.topological_sort(tree))
    parent_of = {c: p for p, c in tree.edges}
    # downstream pipe volume per node (edge into node + everything below)
    down = {}
    for n in reversed(order_nodes):
        own = 0.0
        if n in parent_of:
            p = parent_of[n]
            L = np.linalg.norm(pos[idx[n]] - pos[idx[p]])
            own = np.pi * rad[idx[n]] ** 2 * L
        down[n] = own + sum(down[c] for c in tree.successors(n))

    cyl_id, branch_of, border_of, bpos_of = {}, {}, {}, {}
    next_branch = 2
    rows = []
    for n in order_nodes:
        children = sorted(tree.successors(n), key=lambda c: -down[c])
        for k, c in enumerate(children):
            if n == root:
                br, order, bpos = 1, 0, 1
            elif k == 0:
                br, order, bpos = branch_of[n], border_of[n], bpos_of[n] + 1
            else:
                br, order, bpos = next_branch, border_of[n] + 1, 1
                next_branch += 1
            branch_of[c], border_of[c], bpos_of[c] = br, order, bpos
            s, e = pos[idx[n]], pos[idx[c]]
            L = float(np.linalg.norm(e - s))
            if L <= 0:
                continue
            ax = (e - s) / L
            cid = len(rows) + 1
            cyl_id[c] = cid
            rows.append({
                "id": cid, "parent": cyl_id.get(n, 0),
                "start_x": s[0], "start_y": s[1], "start_z": s[2],
                "axis_x": ax[0], "axis_y": ax[1], "axis_z": ax[2],
                "end_x": e[0], "end_y": e[1], "end_z": e[2],
                "radius": rad[idx[c]], "raw_radius": np.nan, "length": L,
                "branch": br, "branch_order": order, "branch_position": bpos, "added": False,
            })
    return pd.DataFrame(rows)[CYLINDER_COLUMNS]
