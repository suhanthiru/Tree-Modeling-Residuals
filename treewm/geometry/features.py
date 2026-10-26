"""Assemble the per-tree geometry feature row from a point cloud (and optionally a QSM)."""
from __future__ import annotations

import numpy as np

from treewm.geometry.crown import crown_features
from treewm.geometry.stem import StemConfig, stem_features


def cloud_features(pts: np.ndarray, cfg: StemConfig = StemConfig(), track: bool = True) -> dict:
    pts = pts[np.isfinite(pts).all(axis=1)]
    if track:
        st = stem_features(pts, cfg)
        trk = st.pop("_track", None)
    else:
        trk = None
        z0 = float(np.percentile(pts[:, 2], 0.1))
        st = {"pc_height_m": float(pts[:, 2].max() - z0)}
    if trk is not None and len(trk["h"]) >= 2:
        h, cx, cy = trk["h"], trk["cx"], trk["cy"]
        base_xy = np.array([np.interp(0.0, h, cx), np.interp(0.0, h, cy)])
        k = np.polyfit(h, np.c_[cx, cy], 1)

        def axis_xy(z):
            return (k[0] * min(z, h.max()) + k[1]) if z > h.max() else np.array([np.interp(z, h, cx), np.interp(z, h, cy)])
        stem_r = float(np.median(trk["r"][np.abs(h - cfg.breast_height) <= 0.3])) if np.any(np.abs(h - cfg.breast_height) <= 0.3) else float(trk["r"][0])
        z0 = trk["z0"]
    else:
        z0 = float(np.percentile(pts[:, 2], 0.1))
        low = pts[pts[:, 2] < z0 + 0.1 * (pts[:, 2].max() - z0)]
        base_xy = np.median(low[:, :2], axis=0) if len(low) else np.median(pts[:, :2], axis=0)
        axis_xy, stem_r = None, np.nan
    height = st["pc_height_m"]
    cr = crown_features(pts, z0, height, base_xy, axis_xy, stem_r)
    return {"pc_n_points": int(len(pts)), **st, **cr}
