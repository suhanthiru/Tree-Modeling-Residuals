"""Where the density in "rTwig volume x density" comes from, and whether published species
densities could replace the learned one (follow-up to experiment v1.1).

Dry biomass of the Belgian trees, whole site held out. The learned density of a leaf type is
the geometric mean of dry mass / rTwig volume over the training trees of that leaf type; it is
what the v1.1 model "QSM x fold density" learns, without the smearing step. Published densities
come from configs/wood_density.yaml and are used as they are, or scaled by one factor learned
from the training trees (for all trees, or per leaf type).

Writes density_check.md and density_check.csv (per-tree estimates) into the v1.1 folder.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from treewm.baselines import allometry as al
from treewm.baselines.density import lookup
from treewm.baselines.density import table as density_table
from treewm.eval.metrics import paired_bootstrap, summarize
from treewm.eval.report import _md

SHORT = {"Fagus sylvatica": "Beech", "Fraxinus excelsior": "Ash", "Larix decidua": "Larch", "Pinus sylvestris": "Scots pine"}


def geo(x) -> float:
    return float(np.exp(np.mean(np.log(np.asarray(x, float)))))


def _fmt(df: pd.DataFrame, digits: int, overrides: dict | None = None) -> pd.DataFrame:
    """Numbers as fixed-decimal text, blanks for missing values (for the markdown tables)."""
    d = df.copy()
    for c in d.select_dtypes("number"):
        n = (overrides or {}).get(c, digits)
        d[c] = [("" if pd.isna(v) else f"{v:.{n}f}") for v in d[c]]
    return d.fillna("")


def frame(W: pd.DataFrame, F: pd.DataFrame, R: pd.DataFrame, T: pd.DataFrame) -> pd.DataFrame:
    """One row per tree scored for dry biomass in v1.1, with TreeQSM / rTwig volume and densities."""
    b = al.belgian_frame(W, F, T, "scan")
    d = b[b["agb_dry_kg"].notna() & b["agb_allom_dry_kg"].notna() & b["agb_qsm_dry_kg"].notna()].copy()
    d["v_treeqsm"] = d["qsm_volume_total_m3"]
    d["v_rtwig"] = R.loc[d.index, "rtwig_volume_total_m3"]
    hit = d["species_latin"].map(lookup)
    if hit.isna().any():
        raise KeyError(f"no published density for {sorted(d.species_latin[hit.isna()].unique())}")
    d["rho_table"] = hit.str[0]
    d["rho_table_row"] = hit.str[1]
    return d


def held_out(d: pd.DataFrame, fit) -> pd.Series:
    """Leave-one-site-out: fit(train, test) -> predictions for the test site's trees."""
    out = pd.Series(np.nan, index=d.index)
    for site in d["site_id"].unique():
        te = d["site_id"] == site
        out[te] = fit(d[~te], d[te])
    return out


def _same_leaf(tr: pd.DataFrame, te: pd.DataFrame) -> pd.DataFrame:
    return tr[tr["leaf_type"] == te["leaf_type"].iloc[0]]


def learned_leaf(tr, te):
    t = _same_leaf(tr, te)
    return te["v_rtwig"] * geo(t["agb_dry_kg"] / t["v_rtwig"])


def table_one_factor(tr, te):
    return te["v_rtwig"] * te["rho_table"] * geo(tr["agb_dry_kg"] / (tr["v_rtwig"] * tr["rho_table"]))


def table_leaf_factor(tr, te):
    t = _same_leaf(tr, te)
    return te["v_rtwig"] * te["rho_table"] * geo(t["agb_dry_kg"] / (t["v_rtwig"] * t["rho_table"]))


def estimates(d: pd.DataFrame) -> dict[str, tuple[int, pd.Series]]:
    """model -> (numbers fitted, out-of-sample dry biomass per tree)."""
    return {
        "TreeQSM volume x published density": (0, d["v_treeqsm"] * d["rho_table"]),
        "rTwig volume x published density": (0, d["v_rtwig"] * d["rho_table"]),
        "rTwig volume x published density x one learned factor": (1, held_out(d, table_one_factor)),
        "rTwig volume x published density x learned factor per leaf type": (2, held_out(d, table_leaf_factor)),
        "rTwig volume x learned density per leaf type (v1.1 model)": (2, held_out(d, learned_leaf)),
        "rTwig volume x the tree's own base-disc density": (0, d["v_rtwig"] * d["basic_density_kg_m3"]),
        "Published allometry chosen by the data owners": (0, d["agb_allom_dry_kg"]),
    }


def error_table(d: pd.DataFrame, est: dict) -> pd.DataFrame:
    rows = []
    for name, (k, p) in est.items():
        s = summarize(d["agb_dry_kg"], p)
        r = {"model": name, "fitted": k, "all": s["relMAE_pct"], "bias": s["bias_pct"]}
        for sp, g in d.groupby("species_latin"):
            r[SHORT.get(sp, sp)] = 100 * float(np.mean(np.abs(p[g.index] / g["agb_dry_kg"] - 1)))
        rows.append(r)
    return pd.DataFrame(rows)


def species_table(d: pd.DataFrame, W: pd.DataFrame) -> pd.DataFrame:
    """Per species: measured and published density, and what dry mass, fresh mass and harvested
    volume are per m3 of rTwig volume."""
    rows = []
    for sp, g in d.groupby("species_latin"):
        w = W.loc[g.index]
        rows.append({"species": SHORT.get(sp, sp), "leaf type": g["leaf_type"].iloc[0], "trees": len(g),
                     "published density": g["rho_table"].iloc[0], "published row": g["rho_table_row"].iloc[0],
                     "measured base-disc density": g["basic_density_kg_m3"].mean(),
                     "dry mass / rTwig volume": geo(g["agb_dry_kg"] / g["v_rtwig"]),
                     "fresh mass / rTwig volume": geo(w["fresh_mass_total_kg"] / g["v_rtwig"]),
                     "harvested volume / rTwig volume": geo(w["volume_total_m3"] / g["v_rtwig"])})
    for lt, g in d.groupby("leaf_type"):
        rows.append({"species": f"all {lt}", "leaf type": lt, "trees": len(g),
                     "dry mass / rTwig volume": geo(g["agb_dry_kg"] / g["v_rtwig"])})
    return pd.DataFrame(rows)


def site_table(d: pd.DataFrame) -> pd.DataFrame:
    """The density each model gives a site's trees when that site is held out."""
    rows = []
    for site in sorted(d["site_id"].unique()):
        te = d["site_id"] == site
        tr, t = d[~te], d[te]
        same = _same_leaf(tr, t)
        rows.append({"site held out": site, "species": SHORT.get(t["species_latin"].iloc[0]),
                     "own dry mass / rTwig volume": geo(t["agb_dry_kg"] / t["v_rtwig"]),
                     "learned per leaf type": geo(same["agb_dry_kg"] / same["v_rtwig"]),
                     "published x factor per leaf type":
                         t["rho_table"].iloc[0] * geo(same["agb_dry_kg"] / (same["v_rtwig"] * same["rho_table"])),
                     "learned from": ", ".join(sorted(SHORT.get(s, s) for s in same["species_latin"].unique()))})
    return pd.DataFrame(rows)


def write(W: pd.DataFrame, F: pd.DataFrame, R: pd.DataFrame, T: pd.DataFrame, out: Path) -> Path:
    d = frame(W, F, R, T)
    est = estimates(d)
    err = error_table(d, est)
    learned = est["rTwig volume x learned density per leaf type (v1.1 model)"][1]
    pub = est["rTwig volume x published density x learned factor per leaf type"][1]
    bs = paired_bootstrap(learned, pub, d["agb_dry_kg"])
    by_sp = (np.abs(pub / d["agb_dry_kg"] - 1) - np.abs(learned / d["agb_dry_kg"] - 1)).mul(100).groupby(
        d["species_latin"]).mean()
    per_tree = d[["site_id", "species_latin", "leaf_type", "agb_dry_kg", "v_treeqsm", "v_rtwig", "rho_table",
                  "basic_density_kg_m3"]].copy()
    for name, (_, p) in est.items():
        per_tree[name] = p
    per_tree.reset_index().to_csv(out / "density_check.csv", index=False)

    src = density_table()["source"].strip()
    sp_tab = _fmt(species_table(d, W), 0, {c: 2 for c in ["harvested volume / rTwig volume"]})
    site_tab = _fmt(site_table(d), 0)
    err_tab = _fmt(err, 1, {"fitted": 0})
    L = ["# v1.1 follow-up: where the density comes from", "",
         "Written by `treewm density-check`. Dry biomass of the 65 Belgian trees; every estimate that",
         "learns a number learns it with the tree's whole site held out. Errors are mean absolute error",
         "per tree, % of harvested dry biomass. Densities are in kg of dry mass per m3.", "",
         "The learned densities here are plain geometric means, without the smearing step of the main",
         "v1.1 run, so the v1.1 model shows a slightly lower error here than in [tables.md](tables.md).", "",
         f"Published densities: basic wood density of stemwood from {src}", "",
         "## 1. Error by density source", "",
         _md(err_tab, list(err_tab.columns)), "",
         "## 2. Densities per species", "",
         "Fresh mass / rTwig volume is the fresh density the same model would need for fresh mass.", "",
         _md(sp_tab, list(sp_tab.columns)), "",
         "## 3. The density a held-out site gets", "",
         _md(site_tab, list(site_tab.columns)), "",
         "## 4. Learned density per leaf type against published density x factor per leaf type", "",
         f"Published minus learned: {bs['diff_pp']:+.2f} percentage points of mean error, 95 % bootstrap "
         f"interval {bs['lo']:+.2f} to {bs['hi']:+.2f} (over trees, ignoring that trees of a site share errors). "
         f"The learned density is closer on {bs['a_better']} of {bs['n']} trees.", "",
         "By species (percentage points): " + ", ".join(f"{SHORT.get(k, k)} {v:+.1f}" for k, v in by_sp.items()) + ".",
         ""]
    path = out / "density_check.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
