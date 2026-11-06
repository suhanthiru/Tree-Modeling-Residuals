"""Result tables and figures for experiment v1.1 (rTwig-corrected QSMs).

Writes into the experiment folder: metrics.csv, volume_check.csv (per-tree QSM vs harvest),
by_group.csv (per-species errors), tables.md and figures/. The README is written by hand.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from treewm.eval import style as st
from treewm.eval.metrics import by_group
from treewm.eval.report import _md

plt = st.plt

SOURCES = {"none": "no QSM", "treeqsm": "TreeQSM", "rtwig": "rTwig", "both": "TreeQSM + rTwig"}
SPECIES = ["Fagus sylvatica", "Fraxinus excelsior", "Larix decidua", "Pinus sylvestris"]
TARGETS = {"fresh_mass_total_kg": "Fresh mass", "agb_dry_kg": "Dry biomass",
           "volume_total_m3": "Total woody volume", "volume_stem_m3": "Stem volume"}
# rows of the comparison: (label, model name for treeqsm / rtwig, model name for both)
KEY = [("QSM volume (raw)", "QSM volume (raw)", None),
       ("QSM stem volume (raw)", "QSM stem volume (raw)", None),
       ("QSM x fold density", "QSM x fold density", None),
       ("QSM x fold density + correction E", "QSM x fold density + residual E / ensemble",
        "QSM x fold density + residual E+rTwig / ensemble"),
       ("DBH formula (A) + correction E, ensemble", "residual E over A / ensemble", "residual E+rTwig over A / ensemble"),
       ("DBH formula (A) + correction E, ridge", "residual E over A / ridge", "residual E+rTwig over A / ridge"),
       ("DBH+H formula (B) + correction E, ensemble", "residual E / ensemble", "residual E+rTwig / ensemble"),
       ("Published allometry + correction E, ensemble", "published allometry + residual E / ensemble",
        "published allometry + residual E+rTwig / ensemble")]
REFERENCE = ["allometry A (DBH)", "allometry B (DBH+H+leaf type)", "residual D over A / ensemble"]


def volume_check(W: pd.DataFrame, F: pd.DataFrame, R: pd.DataFrame, T: pd.DataFrame) -> pd.DataFrame:
    """Per tree: QSM volume / harvested volume for the whole tree, stem and branches, before and after."""
    d = W[["volume_total_m3", "volume_stem_m3"]].dropna().join(
        F[["qsm_volume_total_m3", "qsm_volume_stem_m3", "qsm_volume_branch_m3"]], how="inner").join(
        R[["rtwig_volume_total_m3", "rtwig_volume_stem_m3", "rtwig_volume_branch_m3", "twig_radius_mm",
           "twig_source", "rtwig_modified_fraction"]], how="inner").join(
        T.set_index("tree_id")[["site_id", "species_latin"]])
    d["volume_branch_m3"] = d["volume_total_m3"] - d["volume_stem_m3"]
    for part in ["total", "stem", "branch"]:
        d[f"ratio_{part}_treeqsm"] = d[f"qsm_volume_{part}_m3"] / d[f"volume_{part}_m3"]
        d[f"ratio_{part}_rtwig"] = d[f"rtwig_volume_{part}_m3"] / d[f"volume_{part}_m3"]
    return d


def volume_summary(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sp, g in list(d.groupby("species_latin")) + [("all", d)]:
        r = {"species": sp, "n": len(g), "twig_radius_mm": g["twig_radius_mm"].iloc[0] if sp != "all" else np.nan,
             "twig_source": g["twig_source"].iloc[0] if sp != "all" else ""}
        for part in ["total", "stem", "branch"]:
            for src in ["treeqsm", "rtwig"]:
                x = g[f"ratio_{part}_{src}"]
                r[f"{part}_median_ratio_{src}"] = float(x.median())
                if part == "total":
                    r[f"total_relMAE_pct_{src}"] = float(100 * (x - 1).abs().mean())
                    r[f"total_bias_pct_{src}"] = float(100 * (x - 1).mean())
        r["closer_after"] = int(((g["ratio_total_rtwig"] - 1).abs() < (g["ratio_total_treeqsm"] - 1).abs()).sum())
        rows.append(r)
    return pd.DataFrame(rows)


def comparison(metrics: pd.DataFrame, scheme: str, scenario: str, value: str = "relMAE_pct") -> dict:
    """target -> table: one row per model, one column per QSM source."""
    m = metrics[(metrics.scheme == scheme) & (metrics.scenario == scenario)]
    out = {}
    for target in TARGETS:
        t = m[m.target == target]
        rows = []
        for model in REFERENCE:
            v = t[(t.qsm_source == "none") & (t.model == model)][value]
            if len(v):
                rows.append({"model": model, "no QSM": float(v.iloc[0])})
        for label, name, both in KEY:
            r = {"model": label}
            for src in ["treeqsm", "rtwig"]:
                v = t[(t.qsm_source == src) & (t.model == name)][value]
                if len(v):
                    r[SOURCES[src]] = float(v.iloc[0])
            v = t[(t.qsm_source == "both") & (t.model == both)][value] if both else []
            if len(v):
                r[SOURCES["both"]] = float(v.iloc[0])
            if len(r) > 1:
                rows.append(r)
        out[target] = pd.DataFrame(rows, columns=["model", "no QSM", "TreeQSM", "rTwig", "TreeQSM + rTwig"])
    return out


def _table(df: pd.DataFrame, digits: int = 1) -> str:
    d = df.copy()
    for c in d.columns[1:]:
        d[c] = d[c].map(lambda v: "" if pd.isna(v) else f"{v:.{digits}f}")
    return _md(d, list(d.columns))


def fig_volume_ratio(d: pd.DataFrame, path: Path) -> None:
    """Per-tree QSM / harvest volume ratio before and after rTwig, one panel per species."""
    fig, axes = plt.subplots(1, len(SPECIES), figsize=(11, 3.6), sharey=True)
    for ax, sp in zip(axes, SPECIES):
        g = d[d.species_latin == sp]
        for _, r in g.iterrows():
            ax.plot([0, 1], [r.ratio_total_treeqsm, r.ratio_total_rtwig], color=st.CONTEXT, lw=0.9, zorder=1)
        st.dots(ax, np.zeros(len(g)), g.ratio_total_treeqsm, st.BLUE_LIGHT, size=24)
        st.dots(ax, np.ones(len(g)), g.ratio_total_rtwig, st.BLUE_DARK, size=24)
        ax.axhline(1, color=st.MUTED, lw=0.8, zorder=0)
        ax.set_yscale("log")
        ax.set_xlim(-0.35, 1.35)
        ax.set_xticks([0, 1], ["TreeQSM", "rTwig"])
        ax.grid(axis="x", visible=False)
        mae0 = 100 * (g.ratio_total_treeqsm - 1).abs().mean()
        mae1 = 100 * (g.ratio_total_rtwig - 1).abs().mean()
        st.titled(ax, f"{sp} ({len(g)})", f"mean error {mae0:.0f} % → {mae1:.0f} %, twig {g.twig_radius_mm.iloc[0]:.2f} mm")
    from matplotlib.ticker import FixedLocator, FuncFormatter
    axes[0].yaxis.set_major_locator(FixedLocator([0.5, 0.7, 1, 1.5, 2, 3]))
    axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    axes[0].yaxis.set_minor_locator(FixedLocator([]))
    axes[0].set_ylabel("QSM volume / harvested volume")
    fig.tight_layout(w_pad=1.2)
    fig.savefig(path)
    plt.close(fig)


def fig_loso(metrics: pd.DataFrame, path: Path, scenario: str = "scan") -> None:
    """LOSO error per model and target: TreeQSM vs rTwig vs both, against the DBH formula."""
    tabs = comparison(metrics, "leave_one_site_out", scenario)
    labels = [k[0] for k in KEY]
    fig, axes = plt.subplots(1, len(TARGETS), figsize=(15, 3.4), sharey=True)
    cols = [("TreeQSM", st.CONTEXT), ("rTwig", st.BLUE), ("TreeQSM + rTwig", st.ORANGE)]
    for ax, (target, name) in zip(axes, TARGETS.items()):
        t = tabs[target].set_index("model")
        top = 0.0
        for i, lab in enumerate(labels):
            if lab not in t.index:
                continue
            v = [t.loc[lab, c] for c, _ in cols]
            fin = [x for x in v if pd.notna(x)]
            ax.plot([min(fin), max(fin)], [i, i], color=st.GRID, lw=2, zorder=1)
            for (c, col), x in zip(cols, v):
                if pd.notna(x):
                    st.dots(ax, [x], [i], col, size=38)
            top = max(top, max(fin))
        ref = t.loc["allometry A (DBH)", "no QSM"]
        ax.axvline(ref, color=st.MUTED, lw=0.9, ls=(0, (3, 2)), zorder=0)
        ax.text(ref, len(labels) - 0.45, " DBH formula", color=st.INK2, fontsize=7, va="bottom", ha="left")
        ax.set_yticks(range(len(labels)), labels)
        ax.set_ylim(len(labels) - 0.4, -0.6)
        ax.grid(axis="y", visible=False)
        ax.set_xlim(0, max(top, ref) * 1.1)
        ax.set_xlabel("mean error per tree (%)")
        st.titled(ax, name)
    handles = [Line2D([], [], marker="o", ls="", ms=7, mfc=col, mec=st.SURFACE) for _, col in cols]
    fig.legend(handles, ["TreeQSM features (v1)", "rTwig features", "TreeQSM + rTwig features"], loc="upper left",
               ncol=3, bbox_to_anchor=(0.12, 1.1))
    fig.tight_layout(w_pad=1.2)
    fig.savefig(path)
    plt.close(fig)


def species_errors(preds: pd.DataFrame) -> pd.DataFrame:
    p = preds[(preds.scheme == "leave_one_site_out") & (preds.scenario == "scan")]
    sel = [("none", "allometry A (DBH)"), ("treeqsm", "QSM x fold density"), ("rtwig", "QSM x fold density"),
           ("treeqsm", "residual E over A / ensemble"), ("rtwig", "residual E over A / ensemble"),
           ("both", "residual E+rTwig over A / ensemble")]
    rows = []
    for target in TARGETS:
        for src, model in sel:
            q = p[(p.target == target) & (p.qsm_source == src) & (p.model == model)]
            if not q.empty:
                rows.append(by_group(q, "species_latin").assign(target=target, qsm_source=src, model=model))
    return pd.concat(rows, ignore_index=True)


def write(preds: pd.DataFrame, metrics: pd.DataFrame, vol: pd.DataFrame, out: Path) -> Path:
    st.apply()
    (out / "figures").mkdir(parents=True, exist_ok=True)
    metrics.to_csv(out / "metrics.csv", index=False)
    vol.reset_index().to_csv(out / "volume_check.csv", index=False)
    vs = volume_summary(vol)
    sp = species_errors(preds)
    sp.to_csv(out / "by_group.csv", index=False)
    fig_volume_ratio(vol, out / "figures" / "qsm_volume_ratio.png")
    fig_loso(metrics, out / "figures" / "loso_scan.png", "scan")
    L = ["# v1.1 rTwig: full result tables", "",
         "Written by `treewm evaluate-rtwig`. The question, setup and conclusions are in [README.md](README.md).",
         "Errors are out-of-sample relMAE % (mean absolute error per tree, relative to the measured value)",
         "unless a table says otherwise. QSM sources: TreeQSM radii as in v1; rTwig-corrected radii in place",
         "of TreeQSM's; or the TreeQSM features plus the corrected branch volume and the size of the correction.", "",
         "## 1. QSM volume against harvested volume", "",
         "Median ratio QSM / harvest, and the mean absolute error of total volume, per species:", ""]
    show = vs[["species", "n", "twig_radius_mm", "total_median_ratio_treeqsm", "total_median_ratio_rtwig",
               "total_relMAE_pct_treeqsm", "total_relMAE_pct_rtwig", "stem_median_ratio_treeqsm",
               "stem_median_ratio_rtwig", "branch_median_ratio_treeqsm", "branch_median_ratio_rtwig", "closer_after"]]
    L += [_md(show, list(show.columns), 2), "", "![QSM / harvest volume ratio](figures/qsm_volume_ratio.png)", ""]
    n = 2
    for scheme in ["leave_one_site_out", "within_site_5fold"]:
        for scen in ["scan", "inventory"]:
            L += [f"## {n}. {scheme}, {scen} DBH and height", ""]
            n += 1
            for target, tab in comparison(metrics, scheme, scen).items():
                L += [f"**{TARGETS[target]}** (`{target}`)", "", _table(tab), ""]
                cov = comparison(metrics, scheme, scen, "coverage90")[target]
                L += [f"90 % interval coverage, {TARGETS[target].lower()}:", "", _table(cov, 2), ""]
            if scheme == "leave_one_site_out" and scen == "scan":
                L += ["![LOSO error, scan inputs](figures/loso_scan.png)", ""]
    sp_show = sp.assign(relMAE_pct=sp.relMAE_pct.round(1), bias_pct=sp.bias_pct.round(1), coverage90=sp.coverage90.round(2))
    L += [f"## {n}. Errors by species, leave_one_site_out, scan inputs", "",
          _md(sp_show, ["target", "qsm_source", "model", "species_latin", "n", "relMAE_pct", "bias_pct", "coverage90"], 2), ""]
    path = out / "tables.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
