"""Write the v1 evaluation report (markdown + CSV + figures)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from treewm.eval.metrics import by_group  # noqa: E402

COLS = ["model", "n", "relMAE_pct", "bias_pct", "total_bias_pct", "log_RMSE", "coverage90", "interval_width_pct"]


def _md(df: pd.DataFrame, cols=COLS, digits=2) -> str:
    d = df[[c for c in cols if c in df]].copy()
    for c in d.select_dtypes("number"):
        d[c] = d[c].round(digits)
    head = "| " + " | ".join(d.columns) + " |\n|" + "---|" * len(d.columns) + "\n"
    return head + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in d.itertuples(index=False)) + "\n"


def _scatter(ax, p: pd.DataFrame, title: str):
    lim = [min(p.y.min(), p.yhat.min()) * 0.8, max(p.y.max(), p.yhat.max()) * 1.2]
    ax.plot(lim, lim, color="0.6", lw=1)
    for g, d in p.groupby(p.columns[p.columns.get_loc("group")]):
        ax.errorbar(d.y, d.yhat, yerr=[d.yhat - d.lo, d.hi - d.yhat], fmt="o", ms=4, alpha=0.75, elinewidth=0.6, label=g)
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel("observed"); ax.set_ylabel("predicted")
    ax.set_title(title, fontsize=9)


def scatter_grid(preds: pd.DataFrame, panels: list[tuple[str, dict]], group_col: str, path: Path):
    fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 4.2), squeeze=False)
    for ax, (title, sel) in zip(axes[0], panels):
        p = preds
        for k, v in sel.items():
            p = p[p[k] == v]
        if p.empty:
            ax.set_visible(False)
            continue
        p = p.assign(group=p[group_col])
        _scatter(ax, p, title)
    axes[0][-1].legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def write_report(preds: pd.DataFrame, metrics: pd.DataFrame, out: Path, notes: dict | None = None) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(exist_ok=True)
    metrics.to_csv(out / "metrics.csv", index=False)
    lines = ["# Tree World Model v1 — evaluation results", ""]
    lines += ["All numbers are out-of-sample (outer cross-validation folds). Intervals are split-conformal",
              "90 % intervals calibrated by an inner CV inside each training fold. relMAE and bias are",
              "per-tree relative errors in %; total_bias compares summed predictions with summed observations.", ""]
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
            for model in ["allometry B (DBH+H+leaf type)", "residual E / ensemble", "QSM x fold density"]:
                p = pb[(pb.target == target) & (pb.model == model)]
                if not p.empty:
                    sp_rows.append(by_group(p, "species_latin").assign(experiment="belgian", target=target, model=model))
        scatter_grid(pb, [("fresh mass: allometry B", {"target": "fresh_mass_total_kg", "model": "allometry B (DBH+H+leaf type)"}),
                          ("fresh mass: QSM x fold density", {"target": "fresh_mass_total_kg", "model": "QSM x fold density"}),
                          ("fresh mass: residual E / ensemble", {"target": "fresh_mass_total_kg", "model": "residual E / ensemble"})],
                     "species_latin", out / "figures" / "belgian_fresh_mass_loso.png")
        lines += ["![Belgian fresh mass, leave-one-site-out](figures/belgian_fresh_mass_loso.png)", ""]

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
        scatter_grid(pc, [("published allometry", {"model": "published allometry (reported)"}),
                          ("TLS-QSM", {"model": "TLS-QSM (reported)"}),
                          ("published + residual E / ensemble", {"model": "published + residual E / ensemble"})],
                     "study_id", out / "figures" / "ceda_agb_loso.png")
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
    path = out / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
