"""Published wood density lookup and the held-out-site density estimates of density_check."""
import numpy as np
import pandas as pd
import pytest

from treewm.baselines.density import lookup
from treewm.eval import density_check as dc


def test_lookup_species_then_genus():
    assert lookup("Fagus sylvatica") == (580.0, "Fagus sylvatica")
    assert lookup("Fraxinus excelsior") == (570.0, "Fraxinus")  # only the genus row is listed
    assert lookup("Pinus strobus") == (320.0, "Pinus strobus")  # species row wins over any genus row
    assert lookup("Eucalyptus globulus") is None
    assert lookup(None) is None


def _trees():
    """Four sites, two per leaf type, every tree with its site's exact dry density over rTwig volume."""
    rho = {"A": 500.0, "B": 600.0, "C": 400.0, "D": 480.0}
    leaf = {"A": "broadleaf", "B": "broadleaf", "C": "conifer", "D": "conifer"}
    table = {"A": 550.0, "B": 550.0, "C": 400.0, "D": 400.0}
    rows = []
    for s in rho:
        for v in (0.5, 1.0, 2.0):
            rows.append({"site_id": s, "leaf_type": leaf[s], "v_rtwig": v, "agb_dry_kg": rho[s] * v,
                         "rho_table": table[s]})
    return pd.DataFrame(rows), rho


def test_learned_density_comes_from_the_other_site_of_the_same_leaf_type():
    d, rho = _trees()
    p = dc.held_out(d, dc.learned_leaf)
    for own, other in [("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")]:
        m = d.site_id == own
        np.testing.assert_allclose(p[m], rho[other] * d.v_rtwig[m])


def test_published_density_factor_per_leaf_type():
    d, rho = _trees()
    p = dc.held_out(d, dc.table_leaf_factor)
    m = d.site_id == "C"  # factor from site D: 480 / 400, applied to C's published 400
    np.testing.assert_allclose(p[m], 400.0 * (480.0 / 400.0) * d.v_rtwig[m])


def test_paired_bootstrap_of_identical_models_is_zero():
    d, _ = _trees()
    p = d.v_rtwig * 520.0
    bs = dc.paired_bootstrap(p, p, d.agb_dry_kg, n=200)
    assert bs["diff_pp"] == pytest.approx(0) and bs["lo"] == pytest.approx(0) and bs["hi"] == pytest.approx(0)
    assert bs["a_better"] == 0 and bs["n"] == len(d)
