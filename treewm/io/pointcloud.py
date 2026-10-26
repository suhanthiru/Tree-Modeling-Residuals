"""Load single-tree point clouds into (N, 3) float64 arrays (metres)."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def read_points(path: str | Path) -> np.ndarray:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".las", ".laz"):
        import laspy
        las = laspy.read(p)
        return np.c_[las.x, las.y, las.z].astype(float)
    if ext == ".pcd":
        return _read_pcd(p)
    if ext in (".txt", ".xyz", ".pts", ".csv"):
        return _read_text(p)
    raise ValueError(f"Unsupported point cloud format: {p}")


def _read_text(p: Path) -> np.ndarray:
    import pandas as pd
    with open(p, "r") as f:
        first = f.readline()
    sep = "," if "," in first else r"\s+"
    skip = 0
    try:
        [float(v) for v in first.replace(",", " ").split()[:3]]
    except ValueError:
        skip = 1
    df = pd.read_csv(p, sep=sep, header=None, skiprows=skip, usecols=[0, 1, 2], engine="c" if sep == "," else "python")
    return df.to_numpy(dtype=float)


def _read_pcd(p: Path) -> np.ndarray:
    with open(p, "rb") as f:
        header = {}
        while True:
            line = f.readline().decode("ascii", "ignore").strip()
            if not line or line.startswith("#"):
                continue
            k, *v = line.split()
            header[k.upper()] = v
            if k.upper() == "DATA":
                break
        fields = header["FIELDS"]
        sizes = [int(s) for s in header["SIZE"]]
        types = header["TYPE"]
        counts = [int(c) for c in header.get("COUNT", ["1"] * len(fields))]
        n = int(header["POINTS"][0])
        kind = header["DATA"][0].lower()
        if kind == "ascii":
            arr = np.loadtxt(f, max_rows=n)
            cols = np.cumsum([0] + counts)[:-1]
            return arr[:, [cols[fields.index(c)] for c in ("x", "y", "z")]].astype(float)
        if kind != "binary":
            raise ValueError(f"{p}: compressed PCD not supported")
        dt = np.dtype([(fld, {"F": "f", "I": "i", "U": "u"}[t] + str(s), (c,) if c > 1 else ())
                       for fld, s, t, c in zip(fields, sizes, types, counts)])
        data = np.frombuffer(f.read(n * dt.itemsize), dtype=dt, count=n)
        return np.c_[data["x"], data["y"], data["z"]].astype(float)


def voxel_downsample(pts: np.ndarray, size: float) -> np.ndarray:
    """One point (the voxel centroid) per occupied voxel."""
    if len(pts) == 0:
        return pts
    keys = np.floor(pts / size).astype(np.int64)
    _, inv, cnt = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    out = np.zeros((cnt.size, 3))
    np.add.at(out, inv.ravel(), pts)
    return out / cnt[:, None]
