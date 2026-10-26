"""Write the v1 result tables (tables.md + CSV + observed-vs-predicted figures).

The narrative report (experiments/v1-residuals/report.md) is written by hand around these outputs and the
explanatory figures from `treewm figures`; `treewm evaluate` never overwrites it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from treewm.eval import style as st
from treewm.eval.metrics import by_group, summarize

plt = st.plt

COLS = ["model", "n", "relMAE_pct", "bias_pct", "total_bias_pct", "log_RMSE", "coverage90", "interval_width_pct"]


def _md(df: pd.DataFrame, cols=COLS, digits=2) -> str:
    d = df[[c for c in cols if c in df]].copy()
    for c in d.select_dtypes("number"):
        d[c] = d[c].round(digits)
    head = "| " + " | ".join(d.columns) + " |\n|" + "---|" * len(d.columns) + "\n"
    return head + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in d.itertuples(index=False)) + "\n"


def _scatter(ax, p: pd.DataFrame, title: str, unit: str, lim: list[float]):
    from matplotlib.ticker import FuncFormatter, LogLocator
    ax.plot(lim, lim, color=st.MUTED, lw=0.8, zorder=1)
    ax.errorbar(p.y, p.yhat, yerr=[p.yhat - p.lo, p.hi - p.yhat], fmt="none", ecolor=st.BLUE_LIGHT,
                elinewidth=0.8, alpha=0.7, zorder=2)
    st.dots(ax, p.y, p.yhat, size=22)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_aspect("equal")
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_locator(LogLocator(base=10, subs=(1.0, 3.0)))
        axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}"))
        axis.set_minor_locator(LogLocator(base=10, subs=()))
    ax.set_xlabel(f"measured ({unit})")
    ax.set_ylabel(f"predicted ({unit})")
    m = summarize(p.y, p.yhat, p.lo, p.hi)
    st.titled(ax, title, f"mean error {m['relMAE_pct']:.1f} %, 90 % range covers {100 * m['coverage90']:.0f} % of trees")


def scatter_grid(preds: pd.DataFrame, panels: list[tuple[str, dict]], path: Path, unit: str = "kg"):
    """Observed vs predicted on log axes, one panel per model; bars are the 90 % ranges."""
    fig, axes = plt.subplots(1, len(panels), figsize=(4.4 * len(panels), 4.6), squeeze=False)
    sel_frames = []
    for _, sel in panels:
        p = preds
        for k, v in sel.items():
            p = p[p[k] == v]
        sel_frames.append(p)
    allp = pd.concat(sel_frames)
    lim = [min(allp.y.min(), allp.lo.min()) * 0.8, max(allp.y.max(), allp.hi.max()) * 1.25]
    for ax, (title, _), p in zip(axes[0], panels, sel_frames):
        if p.empty:
            ax.set_visible(False)
            continue
        _scatter(ax, p, title, unit, lim)
    fig.tight_layout(w_pad=2.5)
    fig.savefig(path)
    plt.close(fig)


def write_report(preds: pd.DataFrame, metrics: pd.DataFrame, out: Path, notes: dict | None = None) -> Path:
    st.apply()
    out.mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(exist_ok=True)
    metrics.to_csv(out / "metrics.csv", index=False)
    lines = ["# Tree World Model v1: full result tables", "",
             "Every model, target, scenario and cross-validation scheme from `treewm evaluate`. The",
             "narrative report that explains the data, methods and findings is [report.md](report.md).", ""]
    lines += ["All numbers are out-of-sample (outer cross-validation folds). Intervals are split-conformal",
              "90 % intervals calibrated by an inner CV inside each training fold. relMAE and bias are",
              "per-tree relative errors in %; total_bias compares summed predictions with summed observations.", "",
              "Model selection caveat: around 25 models are scored on the same outer folds. The error of",
              "whichever model looks best is therefore slightly optimistic; compare model families and",
              "the consistency of a model across targets rather than single best numbers.", ""]
    if notes:
        lines += [f"- {k}: {v}" for k, v in notes.items()] + [""]

    sp_rows = []
    # ---------------- Belgian
    b = metrics[metrics.experiment == "belgian"]
    if not b.empty:
        lines += ["## 1. Belgian destructive harvest (65 trees, 4 species, 5 sites)", "",
                  "Targets are harvested quantities. leave_one_site_out holds out a whole site; because every",
                  "site is a single species except the two pine sites, this is close to leave-one-species-out.",
                  "within_site_5fold is the optimistic bound (the test trees' sites and species are in training).", ""]
        ens = b[b.model.str.contains("ensemble") & b.model.str.startswith("residual")]
        base = b[b.model.str.startswith("allometry")]
        abl = pd.concat([base, ens])
        abl = abl.assign(row=abl.model.str.replace(" / ensemble", "", regex=False))
        for scheme in ["leave_one_site_out", "within_site_5fold"]:
            for scen in ["inventory", "scan"]:
                d = abl[(abl.scheme == scheme) & (abl.scenario == scen)]
                if d.empty:
                    continue
                pv = d.pivot_table(index="row", columns="target", values="relMAE_pct", sort=False).round(1)
                lines += [f"### Ablation, relMAE % — {scheme}, {scen} DBH/height", "",
                          _md(pv.reset_index(), list(pv.reset_index().columns)), ""]
        for target in b.target.unique():
            d = b[(b.target == target) & (b.scheme == "leave_one_site_out") & (b.scenario == "inventory")]
            lines += [f"### {target} — leave_one_site_out, inventory (all models)", "", _md(d.sort_values("relMAE_pct")), ""]
        d = b[(b.scheme == "leave_one_site_out") & (b.scenario == "scan")]
        for target in d.target.unique():
            lines += [f"### {target} — leave_one_site_out, scan-only (all models)", "",
                      _md(d[d.target == target].sort_values("relMAE_pct")), ""]
        pb = preds[(preds.experiment == "belgian") & (preds.scheme == "leave_one_site_out") & (preds.scenario == "inventory")]
        for target in pb.target.unique():
            for model in ["allometry A (DBH)", "residual E over A / ensemble", "QSM x fold density"]:
                p = pb[(pb.target == target) & (pb.model == model)]
                if not p.empty:
                    sp_rows.append(by_group(p, "species_latin").assign(experiment="belgian", target=target, model=model))
        ps = preds[(preds.experiment == "belgian") & (preds.scheme == "leave_one_site_out") & (preds.scenario == "scan")]
        scatter_grid(ps, [("DBH formula (A)", {"target": "agb_dry_kg", "model": "allometry A (DBH)"}),
                          ("QSM volume x learned density", {"target": "agb_dry_kg", "model": "QSM x fold density"}),
                          ("DBH formula + correction (set E)", {"target": "agb_dry_kg", "model": "residual E over A / ensemble"})],
                     out / "figures" / "belgian_agb_loso.png")
        lines += ["![Belgian dry AGB, leave-one-site-out, scan-only inputs](figures/belgian_agb_loso.png)", ""]

    # ---------------- CEDA
    c = metrics[metrics.experiment == "ceda"]
    if not c.empty:
        n_st = preds[preds.experiment == "ceda"].study_id.nunique()
        lines += [f"## 2. Global harvested-biomass compilation — dry AGB, leave-one-study-out ({n_st} studies)", "",
                  "Corrects each study's reported allometric AGB with a learned log-residual. Trees with missing",
                  "inputs are dropped so that every model is scored on the same trees.", "",
                  _md(c.sort_values("relMAE_pct")), ""]
        pc = preds[preds.experiment == "ceda"]
        for model in ["published allometry (reported)", "TLS-QSM (reported)", "published + residual E / ensemble"]:
            p = pc[pc.model == model]
            sp_rows.append(by_group(p, "study_id").rename(columns={"study_id": "species_latin"}).assign(experiment="ceda (by study)", target="agb_dry_kg", model=model))
        scatter_grid(pc, [("Published allometry", {"model": "published allometry (reported)"}),
                          ("TLS-QSM", {"model": "TLS-QSM (reported)"}),
                          ("Published allometry + correction", {"model": "published + residual E / ensemble"})],
                     out / "figures" / "ceda_agb_loso.png")
        lines += ["![CEDA AGB, leave-one-study-out](figures/ceda_agb_loso.png)", ""]

    # ---------------- BioDiv
    d = metrics[metrics.experiment == "biodiv"]
    if not d.empty:
        lines += ["## 3. BioDiv-3DTrees — QSM volume (reconstructed target), 5-fold grouped by plot", "",
                  "The target is TreeQSM volume, not a physical measurement, so this only shows whether drone",
                  "(ULS) crown geometry adds information beyond TLS DBH and height for predicting QSM volume.", "",
                  _md(d.sort_values("relMAE_pct")), ""]
    if sp_rows:
        sp = pd.concat(sp_rows, ignore_index=True)
        sp.to_csv(out / "by_group.csv", index=False)
        lines += ["## Errors by species / study", "",
                  _md(sp, ["experiment", "target", "model", "species_latin", "n", "relMAE_pct", "bias_pct", "coverage90"], 1), ""]
    path = out / "tables.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
