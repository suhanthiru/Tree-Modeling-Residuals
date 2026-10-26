import numpy as np
import pytest

from tests.synthetic import point_cloud_tree
from treewm.geometry.features import cloud_features
from treewm.geometry.stem import fit_circle_ransac


def test_circle_fit_with_outliers():
    rng = np.random.default_rng(1)
    th = rng.uniform(0, 2 * np.pi, 300)
    xy = np.c_[2 + 0.25 * np.cos(th), -1 + 0.25 * np.sin(th)] + rng.normal(0, 0.003, (300, 2))
    xy = np.vstack([xy, rng.uniform(-3, 3, (60, 2))])
    cx, cy, r, inl = fit_circle_ransac(xy, rng)
    assert (cx, cy, r) == pytest.approx((2, -1, 0.25), abs=0.01)
    assert inl > 0.7


def test_upright_tree_dbh_height():
    f = cloud_features(point_cloud_tree(dbh=0.4, height=20.0))
    expected_d = 40 * (1 - 0.8 * 1.3 / 20)
    assert f["pc_dbh_cm"] == pytest.approx(expected_d, rel=0.05)
    assert f["pc_height_m"] == pytest.approx(20.0, abs=0.3)
    assert f["pc_lean_deg"] < 1.0
    assert f["pc_crown_offset_m"] < 0.3


def test_leaning_tree_and_offset_crown():
    f = cloud_features(point_cloud_tree(lean_deg=8.0, crown_offset=(0.0, 1.5)))
    assert f["pc_lean_deg"] == pytest.approx(8.0, abs=1.0)
    assert f["pc_lean_azimuth_deg"] == pytest.approx(0.0, abs=10) or f["pc_lean_azimuth_deg"] > 350
    assert f["pc_crown_offset_m"] > 1.0
    assert f["pc_crown_asymmetry"] > 0.1
