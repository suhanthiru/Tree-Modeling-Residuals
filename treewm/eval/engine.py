"""Nested cross-validation for log-scale models.

Outer folds give the honest test predictions. Inside each training fold, an inner CV gives
out-of-fold log residuals, which provide
  * Duan's smearing factor (mean of exp(residual)) to back-transform log predictions, and
  * a split-conformal 90 % interval half-width (finite-sample quantile of |residual|).
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd

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


def cross_validate(make: Callable, df: pd.DataFrame, outer: list, group_col: str, scheme: str,
                   level: float = 0.9) -> pd.DataFrame:
    """make() returns a fresh unfitted model. df must contain TARGET (log y)."""
    out = []
    for fold, (tr, te) in enumerate(outer):
        train, test = df.iloc[tr], df.iloc[te]
        model = make().fit(train)
        raw = model.predict_log(test)
        smear, q = _calibrate(make, train, train[group_col].to_numpy(), scheme, level)
        out.append(pd.DataFrame({
            "tree_id": test.index, "fold": fold, "y": np.exp(test[TARGET].to_numpy()),
            "yhat": np.exp(raw) * smear, "lo": np.exp(raw - q), "hi": np.exp(raw + q),
        }))
    return pd.concat(out, ignore_index=True)


def fit_calibrated(make: Callable, df: pd.DataFrame, group_col: str, scheme: str, level: float = 0.9):
    """Fit on all rows and calibrate smearing / interval width by CV (for deployment)."""
    model = make().fit(df)
    smear, q = _calibrate(make, df, df[group_col].to_numpy(), scheme, level)
    return model, smear, q
