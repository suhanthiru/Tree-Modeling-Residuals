import numpy as np
import pytest

from tests.synthetic import leaning_stem, stem_with_branch
from treewm.qsm import cylinders as qc


def test_volume_matches_analytic():
    cyl = stem_with_branch()
    expected_stem = np.pi * 0.2**2 * 10
    expected_branch = np.pi * 0.05**2 * 3
    f = qc.qsm_features(cyl)
    assert f["qsm_volume_stem_m3"] == pytest.approx(expected_stem, rel=1e-9)
    assert f["qsm_volume_branch_m3"] == pytest.approx(expected_branch, rel=1e-9)
    assert f["qsm_dbh_cm"] == pytest.approx(40.0)
    assert f["qsm_height_m"] == pytest.approx(10.0)


def test_lean_recovered():
    cyl = leaning_stem(lean_deg=12.0, azimuth_deg=90.0)
    lean = qc.stem_lean(cyl)
    assert lean["lean_deg"] == pytest.approx(12.0, abs=1e-6)
    assert lean["lean_azimuth_deg"] == pytest.approx(90.0, abs=1e-6)


def test_center_of_mass_and_moment():
    cyl = stem_with_branch()
    vs, vb = np.pi * 0.04 * 10, np.pi * 0.0025 * 3
    com, vol = qc.center_of_mass(cyl)
    assert vol == pytest.approx(vs + vb)
    assert com[0] == pytest.approx(vb * 1.5 / (vs + vb), rel=1e-9)
    assert com[2] == pytest.approx((vs * 5 + vb * 6) / (vs + vb), rel=1e-9)
    m = qc.base_moments(cyl, density=800.0)
    assert m["mass_kg"] == pytest.approx(800 * (vs + vb))
    assert m["gravity_moment_Nm"] == pytest.approx(m["mass_kg"] * 9.81 * com[0], rel=1e-9)


def test_branch_asymmetry_one_sided():
    cyl = stem_with_branch()
    sec = qc.sector_volumes(cyl, (cyl["branch_order"] > 0).to_numpy())
    assert sec.sum() == pytest.approx(np.pi * 0.0025 * 3)
    assert qc.directional_asymmetry(sec) > 0.9
    assert qc.directional_asymmetry(np.ones(8)) == pytest.approx(0.0, abs=1e-12)
