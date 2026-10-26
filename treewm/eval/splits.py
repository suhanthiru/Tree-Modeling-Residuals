"""Cross-validation schemes. Each returns a list of (train_idx, test_idx) over positional rows."""
from __future__ import annotations

import numpy as np
from sklearn.model_selection import GroupKFold, KFold, LeaveOneGroupOut, StratifiedKFold


def leave_one_group_out(groups) -> list:
    g = np.asarray(groups)
    return list(LeaveOneGroupOut().split(g, groups=g))


def stratified_kfold(strata, k: int = 5, seed: int = 0) -> list:
    s = np.asarray(strata)
    k = min(k, np.bincount(np.unique(s, return_inverse=True)[1]).min())
    return list(StratifiedKFold(k, shuffle=True, random_state=seed).split(s, s))


def group_kfold(groups, k: int = 5) -> list:
    g = np.asarray(groups)
    return list(GroupKFold(min(k, len(set(g)))).split(g, groups=g))


def kfold(n: int, k: int = 5, seed: int = 0) -> list:
    return list(KFold(min(k, n), shuffle=True, random_state=seed).split(np.arange(n)))


def inner_splits(groups, scheme: str):
    """Splits used inside a training fold to estimate smearing and conformal widths."""
    g = np.asarray(groups)
    if scheme in ("leave_one_site_out", "leave_one_study_out") and len(set(g)) >= 3:
        return leave_one_group_out(g)
    if scheme == "group_5fold_by_plot":
        return group_kfold(g, 5)
    return kfold(len(g), 5)
