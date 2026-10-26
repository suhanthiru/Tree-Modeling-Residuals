"""Crown geometry from a single-tree point cloud.

Point density depends on scanner distance, so crown statistics are computed on a voxel grid
(one point per occupied voxel) rather than on raw points.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import ConvexHull, QhullError

from treewm.io.pointcloud import voxel_downsample
from treewm.qsm.cylinders import directional_asymmetry

N_SECTORS = 8


def crown_base_height(vox: np.ndarray, z0: float, axis_xy, stem_r: float, height: float,
                      step: float = 0.5) -> float:
    """Lowest height (above 1.5 m) where the 95th-percentile radial spread exceeds a threshold."""
    thresh = max(1.0, 5 * stem_r if np.isfinite(stem_r) else 1.0)
    rel = vox[:, 2] - z0
    for h in np.arange(1.5, height, step):
        m = (rel >= h) & (rel < h + step)
        if m.sum() < 5:
            continue
        cx, cy = axis_xy(h + step / 2)
        d = np.hypot(vox[m, 0] - cx, vox[m, 1] - cy)
        if np.percentile(d, 95) > thresh:
            return float(h)
    return float(0.5 * height)


def crown_features(pts: np.ndarray, z0: float, height: float, base_xy: np.ndarray,
                   axis_xy=None, stem_r: float = np.nan, voxel: float = 0.1) -> dict:
    """axis_xy(h) -> (x, y) of the stem centre at height h above the base (defaults to base_xy)."""
    if axis_xy is None:
        axis_xy = lambda _h: base_xy  # noqa: E731
    vox = voxel_downsample(pts, voxel)
    cb = crown_base_height(vox, z0, axis_xy, stem_r, height)
    rel = vox[:, 2] - z0
    cr = vox[rel >= cb]
    out = {"pc_crown_base_m": cb, "pc_crown_length_m": height - cb,
           "pc_crown_ratio": (height - cb) / height if height > 0 else np.nan,
           "pc_crown_voxels": int(len(cr)), "pc_crown_occupied_m3": float(len(cr) * voxel**3)}
    if len(cr) < 20:
        return out
    d = cr[:, :2] - base_xy
    ang = np.arctan2(d[:, 1], d[:, 0]) % (2 * np.pi)
    sec = np.minimum((ang / (2 * np.pi) * N_SECTORS).astype(int), N_SECTORS - 1)
    dist = np.hypot(d[:, 0], d[:, 1])
    radii = np.array([np.percentile(dist[sec == s], 98) if (sec == s).sum() >= 3 else 0.0 for s in range(N_SECTORS)])
    out.update({
        "pc_crown_radius_mean_m": float(radii.mean()),
        "pc_crown_radius_max_m": float(radii.max()),
        "pc_crown_radius_min_m": float(radii.min()),
        "pc_crown_diameter_m": float(2 * radii.mean()),
    })
    try:
        out["pc_crown_projection_area_m2"] = float(ConvexHull(cr[:, :2]).volume)
        out["pc_crown_hull_volume_m3"] = float(ConvexHull(cr).volume)
    except QhullError:
        out["pc_crown_projection_area_m2"] = np.nan
        out["pc_crown_hull_volume_m3"] = np.nan
    cen = cr.mean(axis=0)
    off = cen[:2] - base_xy
    out["pc_crown_offset_m"] = float(np.hypot(*off))
    out["pc_crown_offset_azimuth_deg"] = float(np.degrees(np.arctan2(off[1], off[0])) % 360)
    out["pc_crown_centroid_height_ratio"] = float((cen[2] - z0) / height) if height > 0 else np.nan
    counts = np.bincount(sec, minlength=N_SECTORS).astype(float)
    out["pc_crown_asymmetry"] = directional_asymmetry(counts)
    hw = np.bincount(sec, weights=(cr[:, 2] - z0), minlength=N_SECTORS)
    out["pc_crown_asymmetry_hw"] = directional_asymmetry(hw)
    # moment arm of crown occupancy about the base, per unit occupied volume
    out["pc_crown_moment_arm_m"] = float(np.mean(dist * np.cos(ang - np.arctan2(off[1], off[0]))))
    # completeness: fraction of (sector x height band) cells with any voxel
    band = np.minimum(((cr[:, 2] - z0 - cb) / max(1e-6, height - cb) * 4).astype(int), 3)
    cells = np.zeros((N_SECTORS, 4), bool)
    cells[sec, band] = True
    out["pc_crown_completeness"] = float(cells.mean())
    return out
