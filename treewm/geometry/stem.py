"""Stem tracking from a single-tree point cloud: slice circle fits, centerline, lean, taper.

The stem is followed upward in thin horizontal slices. In each slice, points near the predicted
centre are fitted with a circle by RANSAC + least squares. Tracking stops after several
consecutive failed slices (crown, occlusion) or at the tree top.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class StemConfig:
    slice_thickness: float = 0.10
    slice_step: float = 0.25
    start_height: float = 0.3
    max_height: float | None = None
    search_factor: float = 2.5
    min_search: float = 0.25
    ransac_iter: int = 150
    min_points: int = 15
    max_failures: int = 4
    breast_height: float = 1.3
    seed: int = 0


def fit_circle_lsq(xy: np.ndarray) -> tuple[float, float, float]:
    """Algebraic (Kasa) circle fit. Returns (cx, cy, r)."""
    x, y = xy[:, 0], xy[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    b = x**2 + y**2
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy, c = sol
    r2 = c + cx**2 + cy**2
    return float(cx), float(cy), float(np.sqrt(r2)) if r2 > 0 else np.nan


def fit_circle_ransac(xy: np.ndarray, rng: np.random.Generator, n_iter: int = 150,
                      tol: float | None = None, r_max: float = 1.5) -> tuple[float, float, float, float]:
    """RANSAC circle fit. Returns (cx, cy, r, inlier_fraction)."""
    n = len(xy)
    if n < 3:
        return np.nan, np.nan, np.nan, 0.0
    best_inl, best = None, None
    for _ in range(n_iter):
        s = xy[rng.choice(n, 3, replace=False)]
        cx, cy, r = fit_circle_lsq(s)
        if not np.isfinite(r) or r <= 0.005 or r > r_max:
            continue
        t = tol if tol is not None else max(0.01, 0.08 * r)
        d = np.abs(np.hypot(xy[:, 0] - cx, xy[:, 1] - cy) - r)
        inl = d < t
        if best_inl is None or inl.sum() > best_inl.sum():
            best_inl, best = inl, (cx, cy, r)
    if best is None or best_inl.sum() < 3:
        return np.nan, np.nan, np.nan, 0.0
    cx, cy, r = fit_circle_lsq(xy[best_inl])
    t = tol if tol is not None else max(0.01, 0.08 * r)
    inl = np.abs(np.hypot(xy[:, 0] - cx, xy[:, 1] - cy) - r) < t
    if inl.sum() >= 3:
        cx, cy, r = fit_circle_lsq(xy[inl])
    return cx, cy, r, float(inl.mean())


def angular_coverage(xy: np.ndarray, cx: float, cy: float, bins: int = 12) -> float:
    ang = np.arctan2(xy[:, 1] - cy, xy[:, 0] - cx)
    h = np.histogram(ang, bins=bins, range=(-np.pi, np.pi))[0]
    return float((h > 0).mean())


def base_height(pts: np.ndarray) -> float:
    return float(np.percentile(pts[:, 2], 0.1))


def _seed_center(pts: np.ndarray, z0: float) -> np.ndarray:
    """Horizontal stem location: densest 0.1 m cell among points 0.3-2.0 m above the base."""
    sl = pts[(pts[:, 2] > z0 + 0.3) & (pts[:, 2] < z0 + 2.0)]
    if len(sl) < 10:
        sl = pts[pts[:, 2] < z0 + 0.25 * (pts[:, 2].max() - z0)]
    if len(sl) == 0:
        return np.median(pts[:, :2], axis=0)
    cell = np.floor(sl[:, :2] / 0.1).astype(np.int64)
    u, cnt = np.unique(cell, axis=0, return_counts=True)
    c = (u[np.argmax(cnt)] + 0.5) * 0.1
    near = sl[np.hypot(sl[:, 0] - c[0], sl[:, 1] - c[1]) < 0.6]
    return np.median(near[:, :2], axis=0) if len(near) else c


def track_stem(pts: np.ndarray, cfg: StemConfig = StemConfig()) -> dict:
    """Return slice table (heights, centres, radii, quality) and the base height."""
    rng = np.random.default_rng(cfg.seed)
    z0 = base_height(pts)
    top = pts[:, 2].max() - z0
    hmax = min(top, cfg.max_height) if cfg.max_height else top
    order = np.argsort(pts[:, 2])
    zs = pts[order, 2] - z0
    P = pts[order]
    center = _seed_center(pts, z0)
    r_prev, direction = None, np.zeros(2)
    rows, failures, h = [], 0, cfg.start_height
    last_ok_h = None
    while h <= hmax:
        lo, hi = np.searchsorted(zs, [h - cfg.slice_thickness / 2, h + cfg.slice_thickness / 2])
        sl = P[lo:hi, :2]
        pred = center + (direction * (h - last_ok_h) if last_ok_h is not None else 0)
        search = max(cfg.min_search, cfg.search_factor * r_prev) if r_prev else 0.8
        sl = sl[np.hypot(sl[:, 0] - pred[0], sl[:, 1] - pred[1]) < search]
        ok = False
        if len(sl) >= cfg.min_points:
            cx, cy, r, inl = fit_circle_ransac(sl, rng, cfg.ransac_iter, r_max=1.5)
            if np.isfinite(r):
                cov = angular_coverage(sl, cx, cy)
                jump = np.hypot(cx - pred[0], cy - pred[1])
                plausible = inl > 0.35 and cov >= 0.25 and (r_prev is None or (r < 1.25 * r_prev + 0.01 and jump < max(0.15, 1.5 * r_prev)))
                if plausible:
                    ok = True
                    if last_ok_h is not None and h > last_ok_h:
                        new_dir = (np.array([cx, cy]) - center) / (h - last_ok_h)
                        direction = 0.5 * direction + 0.5 * new_dir
                    center, r_prev, last_ok_h = np.array([cx, cy]), r, h
                    rows.append((h, cx, cy, r, inl, cov, len(sl)))
        failures = 0 if ok else failures + 1
        if failures >= cfg.max_failures and rows:
            break
        h += cfg.slice_step
    arr = np.array(rows) if rows else np.zeros((0, 7))
    return {"z0": z0, "height": top, "h": arr[:, 0], "cx": arr[:, 1], "cy": arr[:, 2], "r": arr[:, 3],
            "inlier": arr[:, 4], "coverage": arr[:, 5], "n": arr[:, 6]}


def dbh_from_slices(trk: dict, breast_height: float = 1.3) -> float:
    """DBH (cm): median radius of slices within +/-0.3 m of breast height."""
    h, r = trk["h"], trk["r"]
    m = np.abs(h - breast_height) <= 0.3
    if m.sum() == 0:
        return np.nan
    return float(200 * np.median(r[m]))


def _line_fit(h: np.ndarray, c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    A = np.c_[np.ones_like(h), h]
    coef, *_ = np.linalg.lstsq(A, c, rcond=None)
    return coef[0], coef[1]  # intercept (x,y), slope (dx/dz, dy/dz)


def stem_features(pts: np.ndarray, cfg: StemConfig = StemConfig()) -> dict:
    trk = track_stem(pts, cfg)
    h, r = trk["h"], trk["r"]
    c = np.c_[trk["cx"], trk["cy"]]
    out = {"pc_height_m": trk["height"], "pc_stem_slices": int(len(h)),
           "pc_stem_tracked_m": float(h.max() - h.min()) if len(h) else 0.0}
    out["pc_dbh_cm"] = dbh_from_slices(trk, cfg.breast_height)
    low = (h > 0) & (h <= 3.0)
    out["pc_stem_visibility"] = float(low.sum() / max(1, int(round((3.0 - cfg.start_height) / cfg.slice_step)) + 1))
    nan_keys = ["pc_lean_deg", "pc_lean_azimuth_deg", "pc_lean_base_deg", "pc_lean_cut_deg", "pc_curvature",
                "pc_sweep_m", "pc_lean_change_deg", "pc_taper_cm_per_m", "pc_stem_volume_m3", "pc_d_rel50_cm"]
    if len(h) < 5:
        out.update({k: np.nan for k in nan_keys})
        return out
    _, slope = _line_fit(h, c)
    out["pc_lean_deg"] = float(np.degrees(np.arctan(np.hypot(*slope))))
    out["pc_lean_azimuth_deg"] = float(np.degrees(np.arctan2(slope[1], slope[0])) % 360)
    b = h <= 3.0
    if b.sum() >= 4:
        _, sb = _line_fit(h[b], c[b])
        out["pc_lean_base_deg"] = float(np.degrees(np.arctan(np.hypot(*sb))))
    else:
        out["pc_lean_base_deg"] = np.nan
    # lean at felling-cut height (0.3 m): local slope over the lowest metre of tracked stem
    cut = h <= max(1.3, h.min() + 1.0)
    if cut.sum() >= 3:
        _, sc = _line_fit(h[cut], c[cut])
        out["pc_lean_cut_deg"] = float(np.degrees(np.arctan(np.hypot(*sc))))
    else:
        out["pc_lean_cut_deg"] = np.nan
    upper = h > np.median(h)
    lower = ~upper
    if upper.sum() >= 3 and lower.sum() >= 3:
        _, su = _line_fit(h[upper], c[upper])
        _, sl_ = _line_fit(h[lower], c[lower])
        out["pc_lean_change_deg"] = float(np.degrees(np.arctan(np.hypot(*(su - sl_)))))
    else:
        out["pc_lean_change_deg"] = np.nan
    # sweep: max deviation of centres from the straight chord between first and last slice
    a, e = np.r_[c[0], h[0]], np.r_[c[-1], h[-1]]
    pts3 = np.c_[c, h]
    chord = (e - a) / np.linalg.norm(e - a)
    dev = np.linalg.norm(np.cross(pts3 - a, chord), axis=1)
    out["pc_sweep_m"] = float(dev.max())
    out["pc_curvature"] = float(dev.max() / np.linalg.norm(e - a))
    # taper: robust slope of diameter vs height above breast height
    m = h >= 1.0
    if m.sum() >= 4:
        k = np.polyfit(h[m], 200 * r[m], 1)
        out["pc_taper_cm_per_m"] = float(-k[0])
    else:
        out["pc_taper_cm_per_m"] = np.nan
    # stem volume: integrate pi r^2 over tracked heights (from 0 with base radius), cone to the top.
    # Above 1.5 m the radius profile is forced to be non-increasing, so forks and branch
    # junctions captured by a slice cannot inflate the volume.
    from sklearn.isotonic import IsotonicRegression
    r_v = r.copy()
    up = h >= 1.5
    if up.sum() >= 3:
        r_v[up] = IsotonicRegression(increasing=False).fit_transform(h[up], r[up])
    r = r_v
    rr = np.r_[r[0], r]
    hh = np.r_[0.0, h]
    vol = float(np.trapezoid(np.pi * rr**2, hh))
    vol += np.pi * r[-1] ** 2 * max(0.0, trk["height"] - h[-1]) / 3.0
    out["pc_stem_volume_m3"] = vol
    hm = 0.5 * trk["height"]
    out["pc_d_rel50_cm"] = float(200 * np.interp(hm, h, r)) if h.max() >= hm else np.nan
    out["_track"] = trk
    return out
