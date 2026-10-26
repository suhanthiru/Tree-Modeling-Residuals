"""Read TreeQSM (v2.3 / v2.4) .mat output into a cylinder table with rTwig-style column names.

TreeQSM stores one struct `qsm` (or an array of them) with a `cylinder` sub-struct:
radius, length, start (N,3), axis (N,3), parent, extension, added, UnmodRadius, branch,
BranchOrder, PositionInBranch. Indices are 1-based and the root's parent is 0.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio

CYLINDER_COLUMNS = [
    "id", "parent", "start_x", "start_y", "start_z", "axis_x", "axis_y", "axis_z",
    "end_x", "end_y", "end_z", "radius", "raw_radius", "length", "branch", "branch_order",
    "branch_position", "added",
]


def _as_struct(obj):
    if isinstance(obj, np.ndarray) and obj.dtype == object:
        obj = obj.flat[0]
    return obj


def cylinders_from_struct(cyl) -> pd.DataFrame:
    radius = np.atleast_1d(np.asarray(cyl.radius, dtype=float))
    n = radius.size
    start = np.asarray(cyl.start, dtype=float).reshape(n, 3)
    axis = np.asarray(cyl.axis, dtype=float).reshape(n, 3)
    length = np.atleast_1d(np.asarray(cyl.length, dtype=float))
    end = start + axis * length[:, None]

    def col(name, default):
        v = getattr(cyl, name, None)
        return np.atleast_1d(np.asarray(v)) if v is not None and np.size(v) == n else np.full(n, default)

    df = pd.DataFrame({
        "id": np.arange(1, n + 1, dtype=np.int32),
        "parent": col("parent", 0).astype(np.int32),
        "start_x": start[:, 0], "start_y": start[:, 1], "start_z": start[:, 2],
        "axis_x": axis[:, 0], "axis_y": axis[:, 1], "axis_z": axis[:, 2],
        "end_x": end[:, 0], "end_y": end[:, 1], "end_z": end[:, 2],
        "radius": radius,
        "raw_radius": col("UnmodRadius", np.nan).astype(float),
        "length": length,
        "branch": col("branch", 1).astype(np.int32),
        "branch_order": col("BranchOrder", 0).astype(np.int32),
        "branch_position": col("PositionInBranch", 0).astype(np.int32),
        "added": col("added", 0).astype(bool),
    })
    return df[CYLINDER_COLUMNS]


def read_treeqsm(path: str | Path) -> tuple[pd.DataFrame, dict]:
    """Return (cylinders, treedata) from a TreeQSM .mat file."""
    m = sio.loadmat(str(path), squeeze_me=True, struct_as_record=False)
    if "qsm" in m:
        qsm = _as_struct(m["qsm"])
    elif "QSM" in m:
        qsm = _as_struct(m["QSM"])
    else:
        raise KeyError(f"{path}: no qsm struct (keys: {[k for k in m if not k.startswith('__')]})")
    cyl = cylinders_from_struct(qsm.cylinder)
    td = {}
    tdat = getattr(qsm, "treedata", None)
    if tdat is not None:
        for f in tdat._fieldnames:
            v = getattr(tdat, f)
            if np.isscalar(v) or (isinstance(v, np.ndarray) and v.size == 1):
                td[f] = float(np.asarray(v).item())
    td["n_models_optimal"] = int(np.size(m["optmodels"])) if "optmodels" in m else 1
    return cyl, td
