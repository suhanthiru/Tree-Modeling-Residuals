"""Explanatory figures for the v1 report (`treewm figures`).

They complement the result tables written by `treewm evaluate`:
  example_tree.png          what the scan measurements are, on one beech
  geometry_validation.png   scan-derived DBH, height and volumes against field and harvest values
  feature_ladder.png        held-out-site error as information is added (the ablation)
  formula_errors.png        which scan features line up with the DBH formula's errors
  species_errors.png        per-species error before and after the correction
  ceda_studies.png          per-study error on the global compilation
geometry_validation.csv holds the numbers behind the second figure.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

from treewm.eval import style as st
from treewm.paths import LABELS, OUTPUTS, PROCESSED, ROOT

plt = st.plt

TARGET_NAMES = {"fresh_mass_total_kg": "Fresh mass", "agb_dry_kg": "Dry biomass (AGB)",
                "volume_total_m3": "Total woody volume", "volume_stem_m3": "Stem volume"}
BASELINE = "allometry A (DBH)"
CORRECTED = "residual E over A / ensemble"
SPECIES = ["Pinus sylvestris", "Fagus sylvatica", "Fraxinus excelsior", "Larix decidua"]


def _belgian() -> pd.DataFrame:
    """Measurements, features and site/species for the Belgian trees, one row per tree."""
    from treewm.data.schema import wide
    T = pd.read_parquet(PROCESSED / "trees.parquet").set_index("tree_id")
    W = wide(pd.read_parquet(LABELS / "measurements.parquet"))
    F = pd.read_parquet(PROCESSED / "features_belgian.parquet").set_index("tree_id")
    # QSM volumes in the harvest CSV are a mean over 10 TreeQSM runs; use the single optimal QSM
    # (the feature columns), as the models do.
    W = W.drop(columns=[c for c in W.columns if c in F.columns])
    return W.join(F, how="inner").join(T[["site_id", "species_latin", "cloud_path"]])


def _loso_scan(preds: pd.DataFrame) -> pd.DataFrame:
    return preds[(preds.experiment == "belgian") & (preds.scheme == "leave_one_site_out") & (preds.scenario == "scan")]


def _rel_mae(d: pd.DataFrame) -> float:
    return float(100 * np.mean(np.abs(d.yhat - d.y) / d.y))


# ----------------------------------------------------------------------------- geometry checks
GEOMETRY_PAIRS = [
    ("DBH, scan slices vs tape", "pc_dbh_cm", "dbh_cm", "cm"),
    ("DBH, QSM vs tape", "qsm_dbh_cm", "dbh_cm", "cm"),
    ("Height, scan vs felled tree", "pc_height_m", "height_m", "m"),
    ("Height, QSM vs felled tree", "qsm_height_m", "height_m", "m"),
    ("Stem volume, scan slices vs harvest", "pc_stem_volume_m3", "volume_stem_m3", "%"),
    ("Stem volume, QSM vs harvest", "qsm_volume_stem_m3", "volume_stem_m3", "%"),
    ("Total volume, QSM vs harvest", "qsm_volume_total_m3", "volume_total_m3", "%"),
]


def geometry_validation(b: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, est, ref, unit in GEOMETRY_PAIRS:
        d = b[[est, ref]].dropna()
        e = d[est] - d[ref]
        if unit == "%":
            e = 100 * e / d[ref]
        rows.append({"comparison": name, "n": len(d), "unit": unit, "bias": round(e.mean(), 2),
                     "mean_abs_error": round(e.abs().mean(), 2),
                     "correlation": round(float(np.corrcoef(d[est], d[ref])[0, 1]), 3)})
    return pd.DataFrame(rows)


def fig_geometry(b: pd.DataFrame, path: Path) -> None:
    panels = [("Trunk diameter at 1.3 m", "pc_dbh_cm", "dbh_cm", "tape measure (cm)", "scan (cm)", "cm"),
              ("Tree height", "pc_height_m", "height_m", "felled tree, measured (m)", "scan (m)", "m"),
              ("Stem volume", "pc_stem_volume_m3", "volume_stem_m3", "harvest (m³)", "scan slices (m³)", "%"),
              ("Total woody volume", "qsm_volume_total_m3", "volume_total_m3", "harvest (m³)", "QSM (m³)", "%")]
    fig, axes = plt.subplots(1, 4, figsize=(14, 3.9))
    for ax, (title, est, ref, xl, yl, unit) in zip(axes, panels):
        d = b[[est, ref, "species_latin"]].dropna()
        lo, hi = float(min(d[est].min(), d[ref].min())), float(max(d[est].max(), d[ref].max()))
        pad = 0.06 * (hi - lo)
        lim = [lo - pad, hi + pad]
        ax.plot(lim, lim, color=st.MUTED, lw=0.8, zorder=1)
        ax.text(lim[1], lim[1], "1:1 ", ha="right", va="bottom", fontsize=7, color=st.MUTED)
        if est == "qsm_volume_total_m3":
            larch = d.species_latin.eq("Larix decidua")
            st.dots(ax, d.loc[~larch, ref], d.loc[~larch, est], st.BLUE, label="pine, beech, ash")
            st.dots(ax, d.loc[larch, ref], d.loc[larch, est], st.ORANGE, label="larch")
            ax.legend(loc="upper left", handletextpad=0.2)
        else:
            st.dots(ax, d[ref], d[est])
        e = d[est] - d[ref]
        if unit == "%":
            r = 100 * e / d[ref]
            sub = f"bias {r.mean():+.0f} %, mean abs. error {r.abs().mean():.0f} %, n = {len(d)}"
        else:
            sub = f"bias {e.mean():+.1f} {unit}, mean abs. error {e.abs().mean():.1f} {unit}, n = {len(d)}"
        st.titled(ax, title, sub)
        ax.set_xlim(lim)
        ax.set_ylim(lim)
        ax.set_aspect("equal")
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
    fig.tight_layout(w_pad=2.5)
    fig.savefig(path)
    plt.close(fig)


# ----------------------------------------------------------------------------- example tree
def fig_example_tree(b: pd.DataFrame, path: Path, tree_id: str = "belgian:FSYL-06") -> dict:
    from treewm.geometry.crown import N_SECTORS
    from treewm.geometry.features import cloud_features
    from treewm.geometry.stem import stem_features
    from treewm.io.pointcloud import read_points, voxel_downsample
    from treewm.qsm.cylinders import base_point, center_of_mass

    pts = read_points(b.loc[tree_id, "cloud_path"])
    pts = pts[np.isfinite(pts).all(axis=1)]
    feats = cloud_features(pts)
    trk = stem_features(pts)["_track"]
    h, cx, cy, r, z0 = trk["h"], trk["cx"], trk["cy"], trk["r"], trk["z0"]
    bx, by = np.interp(0.0, h, cx), np.interp(0.0, h, cy)
    vox = voxel_downsample(pts, 0.05)
    rel = vox[:, 2] - z0
    cb = feats["pc_crown_base_m"]
    crown = voxel_downsample(pts, 0.1)
    crown = crown[crown[:, 2] - z0 >= cb]
    cen = crown.mean(axis=0)

    fig = plt.figure(figsize=(14, 6.6))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1.25, 1], wspace=0.35)

    # (a) side view: stem slices, crown base, centroid
    ax = fig.add_subplot(gs[0])
    ax.scatter(vox[:, 0] - bx, rel, s=0.08, color=st.CONTEXT, rasterized=True, zorder=1)
    for hi_, cxi, ri in zip(h, cx, r):
        ax.plot([cxi - bx - ri, cxi - bx + ri], [hi_, hi_], color=st.BLUE, lw=1.3, zorder=3)
    ax.plot(cx - bx, h, color=st.BLUE_DARK, lw=0.8, zorder=3)
    ax.axhline(cb, color=st.ORANGE, lw=1.0, zorder=2)
    ax.text((vox[:, 0] - bx).max(), cb + 0.25, f"crown base {cb:.1f} m", ha="right", va="bottom",
            fontsize=7.5, color=st.INK2)
    st.dots(ax, [cen[0] - bx], [cen[2] - z0], st.ORANGE, size=40)
    ax.annotate("crown centroid", (cen[0] - bx, cen[2] - z0), xytext=(8, 6), textcoords="offset points",
                fontsize=7.5, color=st.INK2)
    ax.annotate(f"DBH {feats['pc_dbh_cm']:.1f} cm\nat 1.3 m",
                (np.interp(1.3, h, cx) - bx + np.interp(1.3, h, r), 1.3),
                xytext=(18, 10), textcoords="offset points", fontsize=7.5, color=st.INK2,
                arrowprops={"arrowstyle": "-", "color": st.MUTED, "lw": 0.7})
    ax.set_aspect("equal")
    ax.set_xlabel("horizontal position (m)")
    ax.set_ylabel("height above stem base (m)")
    st.titled(ax, "a. Stem tracking, side view",
              f"{len(h)} circle fits, lean {feats['pc_lean_deg']:.1f}°, height {feats['pc_height_m']:.1f} m")

    # (b) top view: crown sectors and centroid offset
    ax = fig.add_subplot(gs[1])
    d = crown[:, :2] - np.array([bx, by])
    ax.scatter(d[:, 0], d[:, 1], s=0.15, color=st.CONTEXT, rasterized=True, zorder=1)
    ang = np.arctan2(d[:, 1], d[:, 0]) % (2 * np.pi)
    sec = np.minimum((ang / (2 * np.pi) * N_SECTORS).astype(int), N_SECTORS - 1)
    dist = np.hypot(d[:, 0], d[:, 1])
    radii = np.array([np.percentile(dist[sec == s], 98) if (sec == s).sum() >= 3 else 0.0 for s in range(N_SECTORS)])
    rmax = radii.max() * 1.08
    for s in range(N_SECTORS):
        a = 2 * np.pi * s / N_SECTORS
        ax.plot([0, rmax * np.cos(a)], [0, rmax * np.sin(a)], color=st.AXIS, lw=0.7, zorder=2)
    mid = 2 * np.pi * (np.arange(N_SECTORS) + 0.5) / N_SECTORS
    poly = np.c_[radii * np.cos(mid), radii * np.sin(mid)]
    poly = np.vstack([poly, poly[:1]])
    ax.plot(poly[:, 0], poly[:, 1], color=st.BLUE, lw=1.5, zorder=3, label="crown radius per 45° sector")
    off = cen[:2] - np.array([bx, by])
    ax.annotate("", xy=(off[0], off[1]), xytext=(0, 0),
                arrowprops={"arrowstyle": "-|>", "color": st.ORANGE, "lw": 1.5}, zorder=4)
    st.dots(ax, [0], [0], st.INK, size=30)
    st.dots(ax, [off[0]], [off[1]], st.ORANGE, size=40)
    ax.annotate(f"centroid offset {np.hypot(*off):.2f} m", (off[0], off[1]), xytext=(8, -14),
                textcoords="offset points", fontsize=7.5, color=st.INK2, bbox=st.LABEL_BOX)
    ax.annotate("stem base", (0, 0), xytext=(-8, -14), textcoords="offset points", fontsize=7.5, color=st.INK2,
                ha="right", bbox=st.LABEL_BOX)
    ax.set_anchor("N")
    ax.set_aspect("equal")
    ax.set_xlabel("east-west (m)")
    ax.set_ylabel("north-south (m)")
    ax.legend(loc="lower left", fontsize=7.5)
    st.titled(ax, "b. Crown, top view (10 cm voxels)",
              f"projection area {feats['pc_crown_projection_area_m2']:.0f} m², sector asymmetry "
              f"{feats['pc_crown_asymmetry']:.2f}, completeness {feats['pc_crown_completeness']:.2f}")

    # (c) QSM cylinders by branch order, centre of mass
    ax = fig.add_subplot(gs[2])
    cyl = pd.read_parquet(PROCESSED / "qsm_cylinders_belgian.parquet", filters=[("tree_id", "==", tree_id)])
    p0 = base_point(cyl)
    seg = np.stack([cyl[["start_x", "start_z"]].to_numpy() - p0[[0, 2]],
                    cyl[["end_x", "end_z"]].to_numpy() - p0[[0, 2]]], axis=1)
    order = np.minimum(cyl["branch_order"].to_numpy(), 3)
    for o in [3, 2, 1, 0]:
        m = order == o
        lw = np.clip(cyl["radius"].to_numpy()[m] * 40, 0.25, 6)
        ax.add_collection(LineCollection(seg[m], colors=st.ORDINAL[o], linewidths=lw, capstyle="round",
                                         zorder=2 + (3 - o)))
    com, vol = center_of_mass(cyl)
    st.dots(ax, [com[0] - p0[0]], [com[2] - p0[2]], st.ORANGE, size=46)
    ax.annotate("centre of mass\n(uniform density)", (com[0] - p0[0], com[2] - p0[2]), xytext=(10, -4),
                textcoords="offset points", fontsize=7.5, color=st.INK2)
    ax.autoscale()
    ax.set_aspect("equal")
    ax.set_xlabel("horizontal position (m)")
    ax.set_ylabel("height above stem base (m)")
    names = ["stem", "1st-order branches", "2nd-order branches", "3rd order and finer"]
    ax.legend([Line2D([], [], color=c, lw=2.5) for c in st.ORDINAL], names, loc="lower left",
              bbox_to_anchor=(1.0, 0.0), fontsize=7.5)
    branch = cyl.loc[cyl.branch_order > 0]
    bv = float((np.pi * branch.radius**2 * branch.length).sum())
    st.titled(ax, "c. TreeQSM cylinder model",
              f"{len(cyl):,} cylinders, {vol:.2f} m³ of wood, {100 * bv / vol:.0f} % of it in branches")
    fig.suptitle(f"Example: European beech {tree_id.split(':')[1]} from the Belgian harvest", x=0.125, ha="left",
                 fontsize=11, fontweight="semibold", y=1.0)
    fig.savefig(path)
    plt.close(fig)
    return {"tree": tree_id, "dbh_cm": feats["pc_dbh_cm"], "height_m": feats["pc_height_m"],
            "crown_base_m": cb, "offset_m": float(np.hypot(*off)), "lean_deg": feats["pc_lean_deg"]}


# ----------------------------------------------------------------------------- ablation ladder
LADDER = [
    ("allometry A (DBH)", "Formula A: DBH only", True),
    ("allometry B (DBH+H+leaf type)", "Formula B: DBH, height, leaf type", True),
    ("residual C / ensemble", "B + correction: stem form (C)", False),
    ("residual D / ensemble", "B + correction: + crown (D)", False),
    ("residual E / ensemble", "B + correction: + QSM (E)", False),
    ("residual D over A / ensemble", "A + correction: set D", False),
    ("residual E over A / ensemble", "A + correction: set E", False),
]


def fig_feature_ladder(metrics: pd.DataFrame, path: Path) -> None:
    m = metrics[(metrics.experiment == "belgian") & (metrics.scheme == "leave_one_site_out") & (metrics.scenario == "scan")]
    ypos = [0, 1, 2.4, 3.4, 4.4, 5.8, 6.8]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 6.8), sharey=True)
    for ax, target in zip(axes.flat, TARGET_NAMES):
        d = m[m.target == target].set_index("model")
        vals = [float(d.loc[k, "relMAE_pct"]) for k, _, _ in LADDER]
        colors = [st.MUTED if base else st.BLUE for _, _, base in LADDER]
        ax.barh(ypos, vals, height=0.55, color=colors, zorder=2)
        ax.axvline(vals[0], color=st.MUTED, lw=0.8, zorder=1)
        for y, v in zip(ypos, vals):
            ax.text(v + 0.3, y, f"{v:.1f}", va="center", fontsize=7.5, color=st.INK2, bbox=st.LABEL_BOX, zorder=3)
        ax.set_yticks(ypos, [lab for _, lab, _ in LADDER])
        ax.grid(axis="y", visible=False)
        ax.set_xlim(0, max(vals) * 1.15)
        ax.set_xlabel("mean error per tree on held-out sites (%)")
        st.titled(ax, TARGET_NAMES[target], f"{int(d['n'].iloc[0])} trees, DBH and height from the scan")
    axes[0, 0].invert_yaxis()
    handles = [Line2D([], [], color=st.MUTED, lw=6), Line2D([], [], color=st.BLUE, lw=6)]
    fig.legend(handles, ["formula only", "formula + learned correction (average of ridge, XGBoost, GP)"],
               loc="upper left", ncol=2, bbox_to_anchor=(0.01, 1.05))
    fig.tight_layout(h_pad=2.5, w_pad=2.0)
    fig.savefig(path)
    plt.close(fig)


# ----------------------------------------------------------------------------- what the formula misses
def fig_formula_errors(preds: pd.DataFrame, path: Path) -> pd.DataFrame:
    from treewm import experiments as ex
    from treewm.baselines import allometry as al
    from treewm.geometry.build import load_features
    W, T = ex._tables()
    df = al.belgian_frame(W, load_features("belgian"), T, "scan")
    base = _loso_scan(preds)
    base = base[base.model == BASELINE]
    panels = [("agb_dry_kg", "form_factor_qsm", "QSM form factor (QSM volume ÷ DBH-height cylinder)"),
              ("fresh_mass_total_kg", "form_factor_pc", "scan form factor (stem volume ÷ DBH-height cylinder)"),
              ("fresh_mass_total_kg", "pc_lean_deg", "stem lean from the scan (degrees)")]
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 3.9), sharey=True)
    rows = []
    for ax, (target, feat, label) in zip(axes, panels):
        d = base[base.target == target].set_index("tree_id")
        ratio = d.y / d.yhat
        x = df.loc[d.index, feat]
        ok = x.notna()
        rho = float(x[ok].rank().corr(ratio[ok].rank()))
        rows.append({"target": target, "feature": feat, "spearman": round(rho, 2), "n": int(ok.sum())})
        ax.axhline(1, color=st.MUTED, lw=0.8, zorder=1)
        larch = df.loc[d.index, "species_latin"].eq("Larix decidua") & ok
        st.dots(ax, x[ok & ~larch], ratio[ok & ~larch], st.BLUE, label="pine, beech, ash")
        st.dots(ax, x[larch], ratio[larch], st.ORANGE, label="larch")
        ax.set_yscale("log")
        ticks = [0.6, 0.8, 1.0, 1.25, 1.5]
        ax.set_yticks(ticks, [f"{t:g}" for t in ticks])
        ax.minorticks_off()
        ax.set_xlabel(label)
        st.titled(ax, f"{TARGET_NAMES[target]} vs {label.split(' (')[0]}",
                  f"Spearman ρ = {rho:+.2f}, n = {int(ok.sum())}")
    axes[0].set_ylabel("measured ÷ DBH-formula prediction")
    axes[0].legend(loc="lower right")
    for ax in axes:
        ax.text(0.01, 0.02, "formula over-predicts", transform=ax.transAxes, fontsize=7, color=st.MUTED)
        ax.text(0.01, 0.98, "formula under-predicts", transform=ax.transAxes, va="top", fontsize=7, color=st.MUTED)
    fig.tight_layout(w_pad=2.5)
    fig.savefig(path)
    plt.close(fig)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- per species
def fig_species(preds: pd.DataFrame, path: Path) -> pd.DataFrame:
    p = _loso_scan(preds)
    fig, axes = plt.subplots(1, 4, figsize=(14, 2.8), sharey=True)
    rows = []
    for ax, target in zip(axes, TARGET_NAMES):
        top = 0.0
        for i, sp in enumerate(SPECIES):
            q = p[(p.target == target) & (p.species_latin == sp)]
            b, c = _rel_mae(q[q.model == BASELINE]), _rel_mae(q[q.model == CORRECTED])
            n = int((q.model == BASELINE).sum())
            rows.append({"target": target, "species": sp, "n": n, "dbh_formula_pct": round(b, 1),
                         "corrected_pct": round(c, 1)})
            ax.plot([b, c], [i, i], color=st.CONTEXT, lw=2, zorder=1, solid_capstyle="round")
            st.dots(ax, [b], [i], st.BLUE_LIGHT, size=42)
            st.dots(ax, [c], [i], st.BLUE_DARK, size=42)
            top = max(top, b, c)
        counts = p[(p.target == "fresh_mass_total_kg") & (p.model == BASELINE)].species_latin.value_counts()
        ax.set_yticks(range(len(SPECIES)), [f"{s} ({counts.get(s, 0)})" for s in SPECIES])
        ax.set_ylim(len(SPECIES) - 0.5, -0.5)
        ax.grid(axis="y", visible=False)
        ax.set_xlim(0, top * 1.12)
        ax.set_xlabel("mean error per tree (%)")
        st.titled(ax, TARGET_NAMES[target])
    handles = [Line2D([], [], marker="o", ls="", ms=7, mfc=st.BLUE_LIGHT, mec=st.SURFACE),
               Line2D([], [], marker="o", ls="", ms=7, mfc=st.BLUE_DARK, mec=st.SURFACE)]
    fig.legend(handles, ["DBH formula", "DBH formula + correction (set E)"], loc="upper left", ncol=2,
               bbox_to_anchor=(0.01, 1.12))
    fig.tight_layout(w_pad=1.5)
    fig.savefig(path)
    plt.close(fig)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- CEDA by study
def fig_ceda(preds: pd.DataFrame, path: Path) -> pd.DataFrame:
    c = preds[preds.experiment == "ceda"]
    models = [("published allometry (reported)", "published allometry", st.MUTED),
              ("TLS-QSM (reported)", "TLS-QSM", st.ORANGE),
              ("published + residual E / ensemble", "published allometry + correction", st.BLUE)]
    tab = pd.DataFrame({lab: c[c.model == m].groupby("study_id")[["y", "yhat"]].apply(_rel_mae)
                        for m, lab, _ in models})
    tab["n"] = c[c.model == models[0][0]].groupby("study_id").size()
    tab = tab.sort_values(models[0][1], ascending=False)
    fig, ax = plt.subplots(figsize=(8, 4.4))
    for i, (_, row) in enumerate(tab.iterrows()):
        v = [row[lab] for _, lab, _ in models]
        ax.plot([min(v), max(v)], [i, i], color=st.GRID, lw=2, zorder=1)
        for (_, _, col), x in zip(models, v):
            st.dots(ax, [x], [i], col, size=40)
    ax.set_yticks(range(len(tab)), [f"{s} ({int(n)})" for s, n in zip(tab.index, tab.n)])
    ax.set_ylim(len(tab) - 0.5, -0.5)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, tab[[lab for _, lab, _ in models]].to_numpy().max() * 1.08)
    ax.set_xlabel("mean error per tree (%)")
    handles = [Line2D([], [], marker="o", ls="", ms=7, mfc=col, mec=st.SURFACE) for _, _, col in models]
    ax.legend(handles, [lab for _, lab, _ in models], loc="lower right")
    st.titled(ax, "Global compilation: dry biomass error per held-out study",
              "each study is predicted by a correction trained on the other eight (trees per study in brackets)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return tab.round(1)


def build(out: Path = ROOT / "reports" / "v1", log=print) -> list[Path]:
    st.apply()
    fig_dir = out / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    preds = pd.read_parquet(OUTPUTS / "predictions_v1.parquet")
    metrics = pd.read_csv(out / "metrics.csv")
    b = _belgian()
    geo = geometry_validation(b)
    geo.to_csv(out / "geometry_validation.csv", index=False)
    log(geo.to_string(index=False))
    paths = [out / "geometry_validation.csv"]
    steps = [("example_tree.png", lambda p: fig_example_tree(b, p)),
             ("geometry_validation.png", lambda p: fig_geometry(b, p)),
             ("feature_ladder.png", lambda p: fig_feature_ladder(metrics, p)),
             ("formula_errors.png", lambda p: fig_formula_errors(preds, p)),
             ("species_errors.png", lambda p: fig_species(preds, p)),
             ("ceda_studies.png", lambda p: fig_ceda(preds, p))]
    for name, fn in steps:
        res = fn(fig_dir / name)
        paths.append(fig_dir / name)
        if res is not None:
            log(f"{name}:\n{res if isinstance(res, dict) else res.to_string()}")
    return paths
