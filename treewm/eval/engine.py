"""Nested cross-validation for log-scale models.

Outer folds give the honest test predictions. Inside each training fold, an inner CV gives
out-of-fold log residuals, which provide
  * Duan's smearing factor (mean of exp(residual)) to back-transform log predictions, and
  * a split-conformal 90 % interval half-width (finite-sample quantile of |residual|).
"""
from __future__ import annotations

import math
import time
from typing import Callable

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from treewm.eval.splits import inner_splits
from treewm.models.residual import TARGET


def _calibrate(make: Callable, train: pd.DataFrame, groups, scheme: str, level: float):
    oof = np.full(len(train), np.nan)
    for itr, iva in inner_splits(groups, scheme):
        m = make().fit(train.iloc[itr])
        oof[iva] = m.predict_log(train.iloc[iva])
    res = train[TARGET].to_numpy() - oof
    res = res[np.isfinite(res)]
    smear = float(np.mean(np.exp(res))) if len(res) else 1.0
    n = len(res)
    k = min(n, math.ceil((n + 1) * level))
    q = float(np.sort(np.abs(res))[k - 1]) if n else np.nan
    return smear, q


def _fold(make: Callable, df: pd.DataFrame, tr, te, fold: int, group_col: str, scheme: str,
          level: float) -> tuple[pd.DataFrame, float]:
    t0 = time.time()
    train, test = df.iloc[tr], df.iloc[te]
    model = make().fit(train)
    raw = model.predict_log(test)
    smear, q = _calibrate(make, train, train[group_col].to_numpy(), scheme, level)
    p = pd.DataFrame({
        "tree_id": test.index, "fold": fold, "y": np.exp(test[TARGET].to_numpy()),
        "yhat": np.exp(raw) * smear, "lo": np.exp(raw - q), "hi": np.exp(raw + q),
    })
    return p, time.time() - t0


def cross_validate(make: Callable, df: pd.DataFrame, outer: list, group_col: str, scheme: str,
                   level: float = 0.9) -> pd.DataFrame:
    """make() returns a fresh unfitted model. df must contain TARGET (log y)."""
    out = [_fold(make, df, tr, te, fold, group_col, scheme, level)[0] for fold, (tr, te) in enumerate(outer)]
    return pd.concat(out, ignore_index=True)


def cross_validate_many(jobs: list[dict], n_jobs: int = -1) -> list[tuple[pd.DataFrame, float]]:
    """cross_validate for many runs at once, one worker task per (run, outer fold).

    Each job holds cross_validate's arguments. Returns (predictions, compute seconds) per job, in
    job order. Every model is seeded, so the predictions match running the jobs one by one.
    """
    tasks = [(i, fold, tr, te) for i, j in enumerate(jobs) for fold, (tr, te) in enumerate(j["outer"])]
    res = Parallel(n_jobs=n_jobs)(
        delayed(_fold)(jobs[i]["make"], jobs[i]["df"], tr, te, fold, jobs[i]["group_col"], jobs[i]["scheme"],
                       jobs[i].get("level", 0.9))
        for i, fold, tr, te in tasks)
    by_job = [[] for _ in jobs]
    for (i, *_), r in zip(tasks, res):
        by_job[i].append(r)
    return [(pd.concat([p for p, _ in rs], ignore_index=True), sum(s for _, s in rs)) for rs in by_job]


def fit_calibrated(make: Callable, df: pd.DataFrame, group_col: str, scheme: str, level: float = 0.9):
    """Fit on all rows and calibrate smearing / interval width by CV (for deployment)."""
    model = make().fit(df)
    smear, q = _calibrate(make, df, df[group_col].to_numpy(), scheme, level)
    return model, smear, q
