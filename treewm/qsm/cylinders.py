"""Geometric metrics from a QSM cylinder table (rTwig-style columns, metres).

The main stem is branch_order == 0. All volumes are m^3.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

N_SECTORS = 8


def cylinder_volume(cyl: pd.DataFrame) -> np.ndarray:
    return np.pi * cyl["radius"].to_numpy() ** 2 * cyl["length"].to_numpy()


def midpoints(cyl: pd.DataFrame) -> np.ndarray:
    s = cyl[["start_x", "start_y", "start_z"]].to_numpy()
    e = cyl[["end_x", "end_y", "end_z"]].to_numpy()
    return 0.5 * (s + e)


def base_point(cyl: pd.DataFrame) -> np.ndarray:
    """Start of the root cylinder (parent == 0, lowest if several)."""
    roots = cyl[cyl["parent"] == 0]
    if roots.empty:
        roots = cyl
    r = roots.loc[roots["start_z"].idxmin()]
    return np.array([r.start_x, r.start_y, r.start_z])


def stem_cylinders(cyl: pd.DataFrame) -> pd.DataFrame:
    s = cyl[cyl["branch_order"] == 0]
    return s.sort_values("start_z")


def diameter_at_height(cyl: pd.DataFrame, h: float) -> float:
    """Stem diameter (m) at height h above the base, from the stem cylinder spanning it."""
    z0 = base_point(cyl)[2]
    s = stem_cylinders(cyl)
    zs, ze = s["start_z"].to_numpy() - z0, s["end_z"].to_numpy() - z0
    lo, hi = np.minimum(zs, ze), np.maximum(zs, ze)
    hit = np.where((lo <= h) & (hi >= h))[0]
    if hit.size == 0:
        if s.empty:
            return float("nan")
        hit = np.array([np.argmin(np.abs(0.5 * (lo + hi) - h))])
    return float(2 * s["radius"].to_numpy()[hit[0]])


def stem_profile(cyl: pd.DataFrame, rel_heights=np.linspace(0.05, 0.95, 10)) -> np.ndarray:
    """Stem diameters (m) at relative heights of the stem length."""
    z0 = base_point(cyl)[2]
    s = stem_cylinders(cyl)
    top = s["end_z"].max() - z0
    return np.array([diameter_at_height(cyl, float(r * top)) for r in rel_heights])


def stem_lean(cyl: pd.DataFrame, upto: float | None = None) -> dict:
    """Lean of the stem axis: angle from vertical of base→point at `upto` m (default: stem top)."""
    s = stem_cylinders(cyl)
    if s.empty:
        return {"lean_deg": np.nan, "lean_azimuth_deg": np.nan}
    b = base_point(cyl)
    ends = s[["end_x", "end_y", "end_z"]].to_numpy()
    if upto is not None:
        idx = np.argmin(np.abs(ends[:, 2] - b[2] - upto))
        p = ends[idx]
    else:
        p = ends[np.argmax(ends[:, 2])]
    d = p - b
    horiz = np.hypot(d[0], d[1])
    return {
        "lean_deg": float(np.degrees(np.arctan2(horiz, d[2]))),
        "lean_azimuth_deg": float(np.degrees(np.arctan2(d[1], d[0])) % 360),
        "top_offset_m": float(horiz),
    }


def center_of_mass(cyl: pd.DataFrame, density=None) -> tuple[np.ndarray, float]:
    """Mass-weighted centre and total mass. density: scalar or per-cylinder array (kg/m^3).

    With density=None the result is the volume centroid and the total volume.
    """
    v = cylinder_volume(cyl)
    w = v if density is None else v * np.broadcast_to(np.asarray(density, dtype=float), v.shape)
    m = w.sum()
    return (midpoints(cyl) * w[:, None]).sum(axis=0) / m, float(m)


def base_moments(cyl: pd.DataFrame, density) -> dict:
    """Gravitational overturning moment and inertia about the stem base (simple rigid model).

    Cylinders are treated as point masses at their midpoints, plus their own axial/transverse
    inertia. Returns the horizontal COM offset, the gravity moment M g d (N m) and the moment
    of inertia about a horizontal axis through the base, perpendicular to the lean direction.
    """
    g = 9.81
    com, mass = center_of_mass(cyl, density)
    b = base_point(cyl)
    off = com - b
    d_h = float(np.hypot(off[0], off[1]))
    m_i = cylinder_volume(cyl) * np.broadcast_to(np.asarray(density, dtype=float), (len(cyl),))
    rel = midpoints(cyl) - b
    # rotation axis: horizontal, perpendicular to COM offset direction (fall direction)
    if d_h > 1e-9:
        u = np.array([-off[1], off[0], 0.0]) / d_h
    else:
        u = np.array([1.0, 0.0, 0.0])
    dist2 = np.sum(rel**2, axis=1) - (rel @ u) ** 2
    r, L = cyl["radius"].to_numpy(), cyl["length"].to_numpy()
    own = m_i * (3 * r**2 + L**2) / 12.0  # transverse inertia of a solid cylinder (approx.)
    inertia = float(np.sum(m_i * dist2 + own))
    return {
        "mass_kg": mass,
        "com_height_m": float(off[2]),
        "com_horizontal_offset_m": d_h,
        "com_azimuth_deg": float(np.degrees(np.arctan2(off[1], off[0])) % 360),
        "gravity_moment_Nm": mass * g * d_h,
        "inertia_base_kgm2": inertia,
    }


def sector_volumes(cyl: pd.DataFrame, mask=None, n: int = N_SECTORS) -> np.ndarray:
    """Volume per azimuth sector around the stem base (sector 0 starts at +x, counter-clockwise)."""
    c = cyl if mask is None else cyl[mask]
    if c.empty:
        return np.zeros(n)
    b = base_point(cyl)
    mp = midpoints(c) - b
    az = np.arctan2(mp[:, 1], mp[:, 0]) % (2 * np.pi)
    idx = np.minimum((az / (2 * np.pi) * n).astype(int), n - 1)
    return np.bincount(idx, weights=cylinder_volume(c), minlength=n)


def directional_asymmetry(weights: np.ndarray) -> float:
    """Resultant length (0..1) of sector weights: 0 = balanced, 1 = all on one side."""
    n = len(weights)
    tot = weights.sum()
    if tot <= 0:
        return 0.0
    ang = (np.arange(n) + 0.5) * 2 * np.pi / n
    return float(np.hypot((weights * np.cos(ang)).sum(), (weights * np.sin(ang)).sum()) / tot)


def qsm_features(cyl: pd.DataFrame, breast_height: float = 1.3) -> dict:
    """Per-tree QSM feature row (feature set E in the ablation)."""
    v = cylinder_volume(cyl)
    order = cyl["branch_order"].to_numpy()
    stem_v = float(v[order == 0].sum())
    total_v = float(v.sum())
    b = base_point(cyl)
    height = float(cyl[["start_z", "end_z"]].to_numpy().max() - b[2])
    branch_mask = cyl["branch_order"] > 0
    sec = sector_volumes(cyl, branch_mask.to_numpy())
    com, _ = center_of_mass(cyl)
    off = com - b
    lean = stem_lean(cyl)
    # crown base: lowest start of a first-order branch thicker than 2 cm
    fo = cyl[(cyl["branch_order"] == 1) & (cyl["branch_position"] <= 1) & (cyl["radius"] >= 0.01)]
    crown_base = float(fo["start_z"].min() - b[2]) if not fo.empty else np.nan
    prof = stem_profile(cyl)
    feats = {
        "qsm_volume_total_m3": total_v,
        "qsm_volume_stem_m3": stem_v,
        "qsm_volume_branch_m3": total_v - stem_v,
        "qsm_branch_ratio": (total_v - stem_v) / total_v if total_v > 0 else np.nan,
        "qsm_volume_order1_m3": float(v[order == 1].sum()),
        "qsm_volume_order2plus_m3": float(v[order >= 2].sum()),
        "qsm_dbh_cm": 100 * diameter_at_height(cyl, breast_height),
        "qsm_height_m": height,
        "qsm_crown_base_m": crown_base,
        "qsm_crown_ratio": (height - crown_base) / height if np.isfinite(crown_base) and height > 0 else np.nan,
        "qsm_n_cylinders": int(len(cyl)),
        "qsm_n_branches": int(cyl.loc[branch_mask, "branch"].nunique()),
        "qsm_max_order": int(order.max()),
        "qsm_branch_asymmetry": directional_asymmetry(sec),
        "qsm_com_height_ratio": float(off[2] / height) if height > 0 else np.nan,
        "qsm_com_offset_m": float(np.hypot(off[0], off[1])),
        "qsm_stem_lean_deg": lean["lean_deg"],
        "qsm_stem_top_offset_m": lean.get("top_offset_m", np.nan),
        "qsm_taper_ratio": float(prof[-2] / prof[0]) if prof[0] > 0 else np.nan,
        "qsm_added_fraction": float(v[cyl["added"].to_numpy()].sum() / total_v) if total_v > 0 else 0.0,
    }
    return feats
