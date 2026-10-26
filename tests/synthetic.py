"""Synthetic trees with analytically known geometry, shared by the tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from treewm.io.treeqsm_mat import CYLINDER_COLUMNS


def make_cylinders(rows) -> pd.DataFrame:
    """rows: (parent, start(3), axis(3), length, radius, branch, order, position)."""
    recs = []
    for i, (parent, start, axis, length, radius, branch, order, pos) in enumerate(rows, start=1):
        start, axis = np.asarray(start, float), np.asarray(axis, float)
        axis = axis / np.linalg.norm(axis)
        end = start + axis * length
        recs.append({
            "id": i, "parent": parent,
            "start_x": start[0], "start_y": start[1], "start_z": start[2],
            "axis_x": axis[0], "axis_y": axis[1], "axis_z": axis[2],
            "end_x": end[0], "end_y": end[1], "end_z": end[2],
            "radius": radius, "raw_radius": radius, "length": length,
            "branch": branch, "branch_order": order, "branch_position": pos, "added": False,
        })
    return pd.DataFrame(recs)[CYLINDER_COLUMNS]


def leaning_stem(n=10, seg=1.0, radius=0.2, lean_deg=10.0, azimuth_deg=0.0) -> pd.DataFrame:
    t = np.radians(lean_deg)
    a = np.radians(azimuth_deg)
    axis = np.array([np.sin(t) * np.cos(a), np.sin(t) * np.sin(a), np.cos(t)])
    rows, p = [], np.zeros(3)
    for i in range(n):
        rows.append((i, p.copy(), axis, seg, radius, 1, 0, i + 1))
        p = p + axis * seg
    return make_cylinders(rows)


def stem_with_branch() -> pd.DataFrame:
    """Vertical 10 m stem (r=0.2) with one horizontal branch along +x at 6 m (r=0.05, 3 m)."""
    rows = [(i, (0, 0, i), (0, 0, 1), 1.0, 0.2, 1, 0, i + 1) for i in range(10)]
    rows.append((6, (0, 0, 6), (1, 0, 0), 3.0, 0.05, 2, 1, 1))
    return make_cylinders(rows)


def point_cloud_tree(seed=0, height=20.0, dbh=0.4, lean_deg=0.0, crown_offset=(0.0, 0.0),
                     crown_base=10.0, crown_radius=3.0, n_stem=40000, n_crown=20000):
    """Point cloud: conical stem surface (with lean) + ellipsoidal crown shell."""
    rng = np.random.default_rng(seed)
    z = rng.uniform(0, height * 0.95, n_stem)
    r = (dbh / 2) * (1 - 0.8 * z / height)
    th = rng.uniform(0, 2 * np.pi, n_stem)
    shift = np.tan(np.radians(lean_deg)) * z
    stem = np.c_[shift + r * np.cos(th), r * np.sin(th), z]
    u = rng.normal(size=(n_crown, 3))
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    half = (height - crown_base) / 2
    cz = crown_base + half
    crown = np.c_[crown_offset[0] + np.tan(np.radians(lean_deg)) * cz + crown_radius * u[:, 0],
                  crown_offset[1] + crown_radius * u[:, 1], cz + half * u[:, 2]]
    return np.vstack([stem, crown])
