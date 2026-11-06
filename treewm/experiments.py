"""The three v1 experiments. Each returns (predictions, metrics) tables."""
from __future__ import annotations

from functools import partial

import numpy as np
import pandas as pd
import yaml

from treewm.baselines import allometry as al
from treewm.data.schema import wide
from treewm.eval.engine import cross_validate_many
from treewm.eval.metrics import summarize
from treewm.eval.splits import group_kfold, leave_one_group_out, stratified_kfold
from treewm.geometry.build import load_features
from treewm.models.residual import TARGET, LogLinear, ResidualModel
from treewm.paths import LABELS, PROCESSED, V1, V1_1

MASS_TARGETS = {"fresh_mass_total_kg", "agb_dry_kg"}


def config() -> dict:
    return yaml.safe_load((V1 / "config.yaml").read_text())


def _tables():
    M = pd.read_parquet(LABELS / "measurements.parquet")
    T = pd.read_parquet(PROCESSED / "trees.parquet")
    return wide(M), T


def belgian_models(target: str, learners: list[str], xgb: dict) -> dict:
    """name -> (factory, feature_set label, family)."""
    m = {
        "allometry A (DBH)": (partial(al.allometry, "A"), "A", "fitted allometry"),
        "allometry B (DBH+H+leaf type)": (partial(al.allometry, "B"), "B", "fitted allometry"),
    }
    for s in ["B", "C", "D", "E"]:
        for lr in learners:
            m[f"residual {s} / {lr}"] = (partial(al.residual, s, lr, xgb), s, "residual over allometry B")
    for s in ["D", "E"]:  # same corrections on top of the DBH-only equation
        for lr in ["ridge", "ensemble"]:
            m[f"residual {s} over A / {lr}"] = (
                lambda s=s, lr=lr: al.residual(s, lr, xgb, base=al.allometry("A")), s, "residual over allometry A")
    if target in MASS_TARGETS or target == "volume_total_m3":
        m["QSM x fold density"] = (partial(al.qsm_offset), "qsm", "geometry x density")
        m["QSM x fold density + residual E / ensemble"] = (
            lambda: ResidualModel(base=al.qsm_offset(), features=al.FEATURE_SETS["E"], learner="ensemble",
                                  xgb_params=xgb, members=["ridge", "xgb", "gp"]), "E", "residual over QSM")
    if target == "volume_total_m3":
        m["QSM volume (raw)"] = (partial(al.fixed, "qsm_volume_total_m3"), "qsm", "reconstruction")
    if target == "volume_stem_m3":
        m["QSM stem volume (raw)"] = (partial(al.fixed, "qsm_volume_stem_m3"), "qsm", "reconstruction")
        m["point-cloud stem volume (raw)"] = (partial(al.fixed, "pc_stem_volume_m3"), "pc", "reconstruction")
        m["point-cloud stem volume x fold factor"] = (lambda: LogLinear(["broadleaf"], offset="pc_stem_volume_m3"), "pc", "reconstruction")
    if target == "fresh_mass_total_kg":
        m["QSM x measured density (oracle)"] = (partial(al.fixed, "qsm_mass_oracle_kg"), "oracle", "oracle")
    if target == "agb_dry_kg":
        m["published allometry (reported)"] = (partial(al.fixed, "agb_allom_dry_kg"), "published", "published")
        m["QSM x basic density (reported)"] = (partial(al.fixed, "agb_qsm_dry_kg"), "published", "published")
        m["published allometry + residual E / ensemble"] = (
            lambda: ResidualModel(base=al.fixed("agb_allom_dry_kg"), features=al.FEATURE_SETS["E"], learner="ensemble",
                                  xgb_params=xgb, members=["ridge", "xgb", "gp"]), "E", "residual over published")
    return m


def belgian_rows(base: pd.DataFrame, target: str) -> pd.DataFrame:
    """The trees every Belgian model is scored on for a target, with TARGET = log(target)."""
    df = base[base[target].notna() & base["log_dbh"].notna() & base["log_h"].notna()].copy()
    if target == "agb_dry_kg":  # compare every model on the trees that have the published estimate
        df = df[df["agb_allom_dry_kg"].notna() & df["agb_qsm_dry_kg"].notna()]
    if target == "volume_stem_m3":  # same for the raw point-cloud stem volume
        df = df[df["pc_stem_volume_m3"].notna()]
    df[TARGET] = np.log(df[target])
    return df


def run_belgian(log=print, n_jobs: int = -1) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = config()
    c = cfg["belgian"]
    W, T = _tables()
    F = load_features("belgian")
    jobs, metas = [], []
    for scenario in c["scenarios"]:
        base = al.belgian_frame(W, F, T, scenario)
        base["qsm_mass_oracle_kg"] = base["qsm_volume_total_m3"] * base["fresh_density_kg_m3"]
        for target in c["targets"]:
            df = belgian_rows(base, target)
            for scheme in c["schemes"]:
                outer = leave_one_group_out(df["site_id"]) if scheme == "leave_one_site_out" else stratified_kfold(df["site_id"], 5)
                for name, (make, fs, fam) in belgian_models(target, c["learners"], cfg["xgboost"]).items():
                    jobs.append({"make": make, "df": df, "outer": outer, "group_col": "site_id", "scheme": scheme,
                                 "level": cfg["interval_level"]})
                    metas.append({"experiment": "belgian", "target": target, "scenario": scenario, "scheme": scheme,
                                  "model": name, "feature_set": fs, "family": fam})
    log(f"belgian: {len(jobs)} cross-validated runs")
    preds, rows = [], []
    for job, meta, (p, seconds) in zip(jobs, metas, cross_validate_many(jobs, n_jobs)):
        p = p.merge(job["df"][["site_id", "species_latin", "dbh_used_cm"]], left_on="tree_id", right_index=True)
        preds.append(p.assign(**meta))
        rows.append({**meta, **summarize(p.y, p.yhat, p.lo, p.hi), "seconds": round(seconds, 1)})
    log("belgian done")
    return pd.concat(preds, ignore_index=True), pd.DataFrame(rows)


def run_ceda(log=print, n_jobs: int = -1) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = config()
    W, T = _tables()
    t = T.set_index("tree_id")
    df = W[W["agb_dry_kg"].notna()].join(t[["study_id", "species_latin", "leaf_type", "foliage"]])
    df = df[df[["agb_allom_dry_kg", "agb_qsm_dry_kg", "dbh_cm", "height_tls_m", "dbh_qsm_cm"]].notna().all(axis=1)].copy()
    df["foliage"] = df["foliage"].fillna("needle_on")  # Belgian trees were scanned with needles/leaves on
    df["log_dbh"], df["log_h"] = np.log(df["dbh_cm"]), np.log(df["height_tls_m"])
    df["broadleaf"] = (df["leaf_type"] == "broadleaf").astype(float)
    df["foliage_on"] = df["foliage"].str.endswith("_on").astype(float)
    df["log_qsm_ratio"] = np.log(df["agb_qsm_dry_kg"] / df["agb_allom_dry_kg"])
    df["log_dbh_ratio"] = np.log(df["dbh_qsm_cm"] / df["dbh_cm"])
    df["agb_geomean_kg"] = np.sqrt(df["agb_qsm_dry_kg"] * df["agb_allom_dry_kg"])
    df[TARGET] = np.log(df["agb_dry_kg"])
    sets = {"B": ["log_dbh", "log_h", "broadleaf", "foliage_on"],
            "E": ["log_dbh", "log_h", "broadleaf", "foliage_on", "log_qsm_ratio", "log_dbh_ratio"]}
    xgb = cfg["xgboost"]
    models = {
        "published allometry (reported)": (lambda: al.fixed("agb_allom_dry_kg"), "published", "published"),
        "TLS-QSM (reported)": (lambda: al.fixed("agb_qsm_dry_kg"), "published", "published"),
        "geometric mean of allometry and QSM": (lambda: al.fixed("agb_geomean_kg"), "published", "published"),
        "fitted allometry A (DBH)": (lambda: LogLinear(["log_dbh"]), "A", "fitted allometry"),
        "fitted allometry B (DBH+H+leaf type+foliage)": (lambda: LogLinear(sets["B"]), "B", "fitted allometry"),
    }
    for s in ["B", "E"]:
        for lr in cfg["ceda"]["learners"]:
            models[f"published + residual {s} / {lr}"] = (
                partial(lambda s, lr: ResidualModel(al.fixed("agb_allom_dry_kg"), sets[s], lr, xgb, ["ridge", "xgb", "gp"]), s, lr),
                s, "residual over published")
    models["TLS-QSM + residual E / ensemble"] = (
        lambda: ResidualModel(al.fixed("agb_qsm_dry_kg"), sets["E"], "ensemble", xgb, ["ridge", "xgb", "gp"]), "E", "residual over QSM")
    outer = leave_one_group_out(df["study_id"])
    jobs = [{"make": make, "df": df, "outer": outer, "group_col": "study_id", "scheme": "leave_one_study_out",
             "level": cfg["interval_level"]} for make, _, _ in models.values()]
    preds, rows = [], []
    for (name, (_, fs, fam)), (p, _) in zip(models.items(), cross_validate_many(jobs, n_jobs)):
        p = p.merge(df[["study_id", "species_latin", "dbh_cm"]], left_on="tree_id", right_index=True)
        meta = {"experiment": "ceda", "target": "agb_dry_kg", "scenario": "inventory+TLS", "scheme": "leave_one_study_out",
                "model": name, "feature_set": fs, "family": fam}
        preds.append(p.assign(**meta))
        rows.append({**meta, **summarize(p.y, p.yhat, p.lo, p.hi)})
    log(f"ceda: {len(df)} trees, {df.study_id.nunique()} studies done")
    return pd.concat(preds, ignore_index=True), pd.DataFrame(rows)


def run_biodiv(log=print, n_jobs: int = -1) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = config()
    W, T = _tables()
    F = load_features("biodiv")
    t = T.set_index("tree_id")
    df = W[W["qsm_volume_total_m3"].notna()].join(t[["site_id", "species_latin", "genus", "leaf_type"]], how="inner")
    df = df[df.index.str.startswith("biodiv:")].join(F, how="left")
    df = df[df[["dbh_tls_cm", "height_tls_m"]].notna().all(axis=1)].copy()
    df["log_dbh"], df["log_h"] = np.log(df["dbh_tls_cm"]), np.log(df["height_tls_m"])
    top = ["Fagus", "Quercus", "Acer", "Fraxinus", "Carpinus"]
    for g in top:
        df[f"genus_{g}"] = (df["genus"] == g).astype(float)
    df["log_cpa_tls"] = np.log(df["crown_projection_area_tls_m2"].where(df["crown_projection_area_tls_m2"] > 0))
    uls = {"log_uls_crown_diam": "uls_crown_diameter_m", "log_uls_crown_area": "uls_crown_projection_area_m2",
           "log_uls_crown_hull": "uls_crown_hull_volume_m3", "log_uls_crown_occupied": "uls_crown_occupied_m3",
           "log_uls_points": "uls_n_points"}
    for k, v in uls.items():
        df[k] = np.log(df[v].where(df[v] > 0)) if v in df else np.nan
    for c in ["uls_crown_ratio", "uls_crown_asymmetry", "uls_crown_offset_m", "uls_crown_completeness", "uls_height_m"]:
        if c not in df:
            df[c] = np.nan
    df[TARGET] = np.log(df["qsm_volume_total_m3"])
    genus = [f"genus_{g}" for g in top]
    sets = {"A": ["log_dbh"], "B": ["log_dbh", "log_h"] + genus,
            "D_tls": ["log_dbh", "log_h", "log_cpa_tls"] + genus,
            "D_tls_uls": ["log_dbh", "log_h", "log_cpa_tls"] + genus + list(uls) +
                         ["uls_crown_ratio", "uls_crown_asymmetry", "uls_crown_offset_m", "uls_crown_completeness", "uls_height_m"]}
    xgb = cfg["xgboost"]
    models = {"fitted allometry A (DBH)": (lambda: LogLinear(sets["A"]), "A", "fitted allometry"),
              "fitted allometry B (DBH+H+genus)": (lambda: LogLinear(sets["B"]), "B", "fitted allometry")}
    for s in ["D_tls", "D_tls_uls"]:
        for lr in cfg["biodiv"]["learners"]:
            models[f"residual {s} / {lr}"] = (
                partial(lambda s, lr: ResidualModel(LogLinear(sets["B"]), sets[s], lr, xgb, ["ridge", "xgb"]), s, lr),
                s, "residual over allometry B")
    outer = group_kfold(df["site_id"], 5)
    jobs = [{"make": make, "df": df, "outer": outer, "group_col": "site_id", "scheme": "group_5fold_by_plot",
             "level": cfg["interval_level"]} for make, _, _ in models.values()]
    preds, rows = [], []
    for (name, (_, fs, fam)), (p, _) in zip(models.items(), cross_validate_many(jobs, n_jobs)):
        p = p.merge(df[["site_id", "species_latin", "dbh_tls_cm"]], left_on="tree_id", right_index=True)
        meta = {"experiment": "biodiv", "target": "qsm_volume_total_m3 (reconstructed)", "scenario": "TLS+ULS",
                "scheme": "group_5fold_by_plot", "model": name, "feature_set": fs, "family": fam}
        preds.append(p.assign(**meta))
        rows.append({**meta, **summarize(p.y, p.yhat, p.lo, p.hi)})
    log(f"biodiv: {len(df)} trees, {df.site_id.nunique()} plots done")
    return pd.concat(preds, ignore_index=True), pd.DataFrame(rows)


# ---------------------------------------------------------------- v1.1: rTwig-corrected QSMs

# TreeQSM feature columns that rTwig changes. DBH, height, crown base and lean stay TreeQSM's,
# so the only difference between sources is cylinder radii and the volumes built from them.
RTWIG_SWAP = ["qsm_volume_total_m3", "qsm_volume_stem_m3", "qsm_volume_branch_m3", "qsm_branch_ratio",
              "qsm_volume_order1_m3", "qsm_volume_order2plus_m3", "qsm_branch_asymmetry",
              "qsm_com_height_ratio", "qsm_com_offset_m", "qsm_added_fraction"]
SET_E_BOTH = al.FEATURE_SETS["E"] + ["log_rtwig_branch", "rtwig_log_shrink"]
QSM_SOURCES = ["none", "treeqsm", "rtwig", "both"]  # none: models without QSM inputs, scored once


def rtwig_config() -> dict:
    cfg = yaml.safe_load((V1_1 / "config.yaml").read_text())
    parent = config()
    return {**cfg, "xgboost": parent["xgboost"], "interval_level": parent["interval_level"],
            "learners": parent["belgian"]["learners"]}


def with_qsm_source(F: pd.DataFrame, R: pd.DataFrame | None, source: str) -> pd.DataFrame:
    """TreeQSM feature table F with the QSM features of `source`; R holds the rtwig_ features,
    on the same index (one row per tree; also used for a single tree in `treewm predict`)."""
    if source in ("none", "treeqsm"):
        return F
    if source == "rtwig":
        F = F.copy()
        for c in RTWIG_SWAP:
            F[c] = R[c.replace("qsm_", "rtwig_", 1)]
        return F
    if source == "both":
        F = F.join(R[["rtwig_volume_branch_m3", "rtwig_log_shrink"]])
        F["log_rtwig_branch"] = al._log(F["rtwig_volume_branch_m3"])  # NaN (imputed) for a QSM without branches
        return F
    raise ValueError(source)


def qsm_feature_table(source: str) -> pd.DataFrame:
    R = None if source in ("none", "treeqsm") else load_features("belgian_rtwig")
    return with_qsm_source(load_features("belgian"), R, source)


def rtwig_models(target: str, source: str, xgb: dict) -> dict:
    """name -> (factory, feature set, family). Names match v1 so the TreeQSM rows can be checked against it."""
    def corr(base, feats, learner="ensemble"):
        return lambda: ResidualModel(base=base(), features=feats, learner=learner, xgb_params=xgb,
                                     members=["ridge", "xgb", "gp"])
    A, B = partial(al.allometry, "A"), partial(al.allometry, "B")
    if source == "none":
        return {"allometry A (DBH)": (A, "A", "fitted allometry"),
                "allometry B (DBH+H+leaf type)": (B, "B", "fitted allometry"),
                "residual D over A / ensemble": (corr(A, al.FEATURE_SETS["D"]), "D", "residual over allometry A")}
    feats, tag = (SET_E_BOTH, "E+rTwig") if source == "both" else (al.FEATURE_SETS["E"], "E")
    qsm_target = target in MASS_TARGETS or target == "volume_total_m3"
    m = {}
    if source != "both":
        if target == "volume_total_m3":
            m["QSM volume (raw)"] = (partial(al.fixed, "qsm_volume_total_m3"), "qsm", "reconstruction")
        if target == "volume_stem_m3":
            m["QSM stem volume (raw)"] = (partial(al.fixed, "qsm_volume_stem_m3"), "qsm", "reconstruction")
        if qsm_target:
            m["QSM x fold density"] = (partial(al.qsm_offset), "qsm", "geometry x density")
    if qsm_target:
        m[f"QSM x fold density + residual {tag} / ensemble"] = (corr(al.qsm_offset, feats), tag, "residual over QSM")
    if target == "agb_dry_kg":
        m[f"published allometry + residual {tag} / ensemble"] = (
            corr(partial(al.fixed, "agb_allom_dry_kg"), feats), tag, "residual over published")
    m[f"residual {tag} / ensemble"] = (corr(B, feats), tag, "residual over allometry B")
    for lr in ["ridge", "ensemble"]:
        m[f"residual {tag} over A / {lr}"] = (corr(A, feats, lr), tag, "residual over allometry A")
    return m


def check_rtwig_features(R: pd.DataFrame, cfg: dict) -> None:
    """The corrected features must come from the rTwig version and smoothing setting in the config."""
    versions = set(R["rtwig_version"].astype(str))
    if versions != {cfg["rtwig"]["package_version"]}:
        raise RuntimeError(f"features were built with rTwig {versions}, config expects {cfg['rtwig']['package_version']}")
    if R["smooth"].astype(bool).any() != bool(cfg["rtwig"]["smooth"]):
        raise RuntimeError("features were built with a different rTwig smoothing setting than the config")


def run_rtwig(log=print, n_jobs: int = -1) -> tuple[pd.DataFrame, pd.DataFrame]:
    """v1 Belgian experiment with the QSM features taken from TreeQSM, rTwig, or both."""
    cfg = rtwig_config()
    c = cfg["belgian"]
    W, T = _tables()
    check_rtwig_features(load_features("belgian_rtwig"), cfg)
    jobs, metas = [], []
    for source in QSM_SOURCES:
        F = qsm_feature_table(source)
        for scenario in c["scenarios"]:
            base = al.belgian_frame(W, F, T, scenario)
            for target in c["targets"]:
                df = belgian_rows(base, target)
                for scheme in c["schemes"]:
                    outer = leave_one_group_out(df["site_id"]) if scheme == "leave_one_site_out" else stratified_kfold(df["site_id"], 5)
                    for name, (make, fs, fam) in rtwig_models(target, source, cfg["xgboost"]).items():
                        jobs.append({"make": make, "df": df, "outer": outer, "group_col": "site_id", "scheme": scheme,
                                     "level": cfg["interval_level"]})
                        metas.append({"experiment": "belgian_rtwig", "qsm_source": source, "target": target,
                                      "scenario": scenario, "scheme": scheme, "model": name, "feature_set": fs, "family": fam})
    log(f"belgian_rtwig: {len(jobs)} cross-validated runs")
    preds, rows = [], []
    for job, meta, (p, seconds) in zip(jobs, metas, cross_validate_many(jobs, n_jobs)):
        p = p.merge(job["df"][["site_id", "species_latin", "dbh_used_cm"]], left_on="tree_id", right_index=True)
        preds.append(p.assign(**meta))
        rows.append({**meta, **summarize(p.y, p.yhat, p.lo, p.hi), "seconds": round(seconds, 1)})
    log("belgian_rtwig done")
    return pd.concat(preds, ignore_index=True), pd.DataFrame(rows)
