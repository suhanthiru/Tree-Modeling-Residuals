"""Feature construction and the baseline / residual model zoo.

Feature sets follow the ablation table of the design doc (cumulative):
  A  DBH only
  B  DBH + height + leaf type (species group)
  C  B + stem form (taper, form factor, lean, sweep) from the point cloud
  D  C + crown geometry from the point cloud
  E  D + QSM structure (branch volume, branch ratio, asymmetry, centre of mass)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from treewm.models.residual import FixedModel, LogLinear, ResidualModel


def _log(s):
    s = pd.to_numeric(s, errors="coerce")
    return np.log(s.where(s > 0))


SET_A = ["log_dbh"]
SET_B = ["log_dbh", "log_h", "broadleaf"]
STEM = ["form_factor_pc", "taper_rel", "form_d50", "pc_lean_deg", "pc_sweep_m", "pc_curvature", "pc_lean_change_deg"]
CROWN = ["pc_crown_ratio", "log_crown_diam", "log_crown_area", "log_crown_hull", "log_crown_occupied",
         "pc_crown_offset_m", "pc_crown_asymmetry", "pc_crown_asymmetry_hw", "pc_crown_completeness",
         "pc_crown_centroid_height_ratio"]
QSM = ["log_qsm_total", "log_qsm_branch", "qsm_branch_ratio", "qsm_branch_asymmetry", "qsm_com_height_ratio",
       "qsm_com_offset_m", "qsm_added_fraction", "log_qsm_order2plus", "form_factor_qsm"]
FEATURE_SETS = {"A": SET_A, "B": SET_B, "C": SET_B + STEM, "D": SET_B + STEM + CROWN, "E": SET_B + STEM + CROWN + QSM}


def belgian_frame(W: pd.DataFrame, F: pd.DataFrame, trees: pd.DataFrame, scenario: str) -> pd.DataFrame:
    """One row per Belgian tree: targets, baselines and features for a scenario.

    inventory: DBH and height from the field (tape DBH, felled height).
    scan:      DBH and height from the point cloud (QSM DBH if the slice fit failed).
    """
    # QSM volumes reported in the harvest CSV (mean of 10 TreeQSM runs) get a _reported suffix; the
    # feature columns come from the single optimal QSM, which is what a deployed scan would have.
    df = W.join(F, how="inner", lsuffix="_reported").join(trees.set_index("tree_id")[["site_id", "species_latin", "leaf_type"]])
    if scenario == "inventory":
        dbh, h = df["dbh_cm"], df["height_m"]
    elif scenario == "scan":
        dbh = df["pc_dbh_cm"].fillna(df["qsm_dbh_cm"])
        h = df["pc_height_m"]
    else:
        raise ValueError(scenario)
    return add_features(df, dbh, h)


def add_features(df: pd.DataFrame, dbh: pd.Series, h: pd.Series) -> pd.DataFrame:
    df = df.copy()
    df["dbh_used_cm"], df["h_used_m"] = dbh, h
    df["log_dbh"], df["log_h"] = _log(dbh), _log(h)
    df["broadleaf"] = (df["leaf_type"] == "broadleaf").astype(float)
    cyl = np.pi / 4 * (dbh / 100) ** 2 * h  # volume of a cylinder with diameter DBH and height H (m3)
    g = lambda c: df[c] if c in df else pd.Series(np.nan, index=df.index)  # noqa: E731
    df["form_factor_pc"] = g("pc_stem_volume_m3") / cyl
    df["taper_rel"] = g("pc_taper_cm_per_m") / dbh
    df["form_d50"] = g("pc_d_rel50_cm") / dbh
    df["log_crown_diam"] = _log(g("pc_crown_diameter_m"))
    df["log_crown_area"] = _log(g("pc_crown_projection_area_m2"))
    df["log_crown_hull"] = _log(g("pc_crown_hull_volume_m3"))
    df["log_crown_occupied"] = _log(g("pc_crown_occupied_m3"))
    df["log_qsm_total"] = _log(g("qsm_volume_total_m3"))
    df["log_qsm_branch"] = _log(g("qsm_volume_branch_m3"))
    df["log_qsm_order2plus"] = _log(g("qsm_volume_order2plus_m3"))
    df["form_factor_qsm"] = g("qsm_volume_total_m3") / cyl
    for c in STEM + CROWN + QSM:
        if c not in df:
            df[c] = np.nan
    return df


def allometry(set_name: str) -> LogLinear:
    return LogLinear(FEATURE_SETS[set_name])


def residual(set_name: str, learner: str, xgb_params=None, base=None) -> ResidualModel:
    return ResidualModel(base=base or allometry("B"), features=FEATURE_SETS[set_name], learner=learner,
                         xgb_params=xgb_params, members=["ridge", "xgb", "gp"])


def qsm_offset(qsm_col: str = "qsm_volume_total_m3") -> LogLinear:
    """log y = log(QSM volume) + intercept by leaf type: QSM volume x fold-learned effective density."""
    return LogLinear(["broadleaf"], offset=qsm_col)


def fixed(col: str) -> FixedModel:
    return FixedModel(col)
