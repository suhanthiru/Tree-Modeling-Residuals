"""Models that predict log(target).

Every model exposes fit(df) and predict_log(df), so the evaluation engine can treat a fixed
published estimate, a fitted allometric equation and a learned residual correction the same way.

Residual models follow the design doc:  log y_hat = log y_base(X) + f_theta(X)
where the base is refit on each training fold and f_theta is fitted to the base's
in-sample log residuals (the base has at most four parameters, so these are close to
out-of-fold residuals).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

TARGET = "_logy"


class FixedModel:
    """A precomputed estimate (e.g. published allometry) used as-is."""

    def __init__(self, column: str):
        self.column = column
        self.features: list[str] = []

    def fit(self, df: pd.DataFrame):
        return self

    def predict_log(self, df: pd.DataFrame) -> np.ndarray:
        return np.log(df[self.column].to_numpy(dtype=float))


class LogLinear:
    """OLS on log-scale features, optionally with a log offset column: log y = offset + X b."""

    def __init__(self, features: list[str], offset: str | None = None):
        self.features, self.offset = list(features), offset

    def _off(self, df):
        return np.log(df[self.offset].to_numpy(dtype=float)) if self.offset else 0.0

    def fit(self, df: pd.DataFrame):
        y = df[TARGET].to_numpy() - self._off(df)
        if self.features:
            self.m = make_pipeline(SimpleImputer(strategy="median"), LinearRegression()).fit(df[self.features], y)
        else:
            self.c = float(np.mean(y))
        return self

    def predict_log(self, df: pd.DataFrame) -> np.ndarray:
        base = self.m.predict(df[self.features]) if self.features else self.c
        return base + self._off(df)


def make_learner(kind: str, xgb_params: dict | None = None, seed: int = 0):
    if kind == "ridge":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             RidgeCV(alphas=np.logspace(-2, 3, 30)))
    if kind == "xgb":
        from xgboost import XGBRegressor
        p = dict(n_estimators=200, max_depth=2, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                 min_child_weight=3, reg_lambda=5.0)
        p.update(xgb_params or {})
        return XGBRegressor(**p, random_state=seed, n_jobs=1, verbosity=0)
    if kind == "gp":
        kernel = ConstantKernel(0.05, (1e-4, 10)) * RBF(3.0, (0.3, 100)) + WhiteKernel(0.02, (1e-5, 1))
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             GaussianProcessRegressor(kernel=kernel, normalize_y=False, n_restarts_optimizer=1,
                                                      random_state=seed))
    raise ValueError(kind)


@dataclass
class ResidualModel:
    base: object
    features: list[str]
    learner: str
    xgb_params: dict | None = None
    members: list[str] = field(default_factory=list)  # for learner == "ensemble"

    def fit(self, df: pd.DataFrame):
        self.base.fit(df)
        r = df[TARGET].to_numpy() - self.base.predict_log(df)
        ok = np.isfinite(r)
        r = r[ok]
        kinds = self.members if self.learner == "ensemble" else [self.learner]
        X = df.loc[ok, self.features].astype(float)
        self.models = []
        for k in kinds:
            m = make_learner(k, self.xgb_params)
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m.fit(X, r)
            self.models.append(m)
        return self

    def predict_log(self, df: pd.DataFrame) -> np.ndarray:
        X = df[self.features].astype(float)
        corr = np.mean([m.predict(X) for m in self.models], axis=0)
        return self.base.predict_log(df) + corr
