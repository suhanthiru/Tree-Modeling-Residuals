"""Python side of the rTwig step (treewm.qsm.rtwig). R is never run: the rTwig output is
replaced by synthetic CSVs written the way rtwig.R writes them (R's write.csv)."""
import numpy as np
import pandas as pd
import pytest
import scipy.io as sio

from tests.synthetic import make_cylinders, stem_with_branch
from treewm.io.treeqsm_mat import CYLINDER_COLUMNS, read_treeqsm
from treewm.qsm import rtwig
from treewm.qsm.cylinders import qsm_features

# Column order of the CSV written by rtwig.R (its `keep` vector).
RTWIG_COLUMNS = [
    "start.x", "start.y", "start.z", "axis.x", "axis.y", "axis.z", "end.x", "end.y", "end.z",
    "length", "radius", "OldRadius", "UnmodRadius", "parent", "extension", "added",
    "BranchOrder", "PositionInBranch", "branch", "modified",
]

# Stem: four vertical 1 m cylinders, radii unchanged by rTwig.
STEM_R = [0.20, 0.18, 0.16, 0.14]
# Branches: (TreeQSM radius, corrected radius, length). Order 1 along +x from the stem at 2 m
# (two cylinders), order 2 along +y from the end of the first order-1 cylinder (one cylinder).
ORDER1 = [(0.05, 0.035, 1.0), (0.04, 0.025, 0.8)]
ORDER2 = [(0.02, 0.008, 0.5)]


def _fmt(v):
    if isinstance(v, (bool, np.bool_)):
        return "TRUE" if v else "FALSE"  # R logicals
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    return repr(float(v))  # full precision, like write.csv's 15 significant digits or better


def write_rtwig_csv(path, d: pd.DataFrame):
    """Write a table with rTwig column names as R's write.csv does (quoted header, TRUE/FALSE)."""
    lines = [",".join(f'"{c}"' for c in RTWIG_COLUMNS)]
    lines += [",".join(_fmt(v) for v in row) for row in d[RTWIG_COLUMNS].itertuples(index=False)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def synthetic_rtwig_table() -> pd.DataFrame:
    """Synthetic tree in rTwig's output columns, corrected radius < OldRadius on branches only."""
    # rows for make_cylinders: (parent, start, axis, length, radius, branch, order, position)
    rows = [(i, (0, 0, i), (0, 0, 1), 1.0, r, 1, 0, i + 1) for i, r in enumerate(STEM_R)]
    old = list(STEM_R)
    new = list(STEM_R)
    x = 0.0
    for k, (r_old, r_new, length) in enumerate(ORDER1):
        rows.append((2 if k == 0 else 5, (x, 0, 2), (1, 0, 0), length, r_new, 2, 1, k + 1))
        old.append(r_old)
        new.append(r_new)
        x += length
    for k, (r_old, r_new, length) in enumerate(ORDER2):
        rows.append((5, (ORDER1[0][2], 0, 2), (0, 1, 0), length, r_new, 3, 2, k + 1))
        old.append(r_old)
        new.append(r_new)
    c = make_cylinders(rows)
    n = len(c)
    return pd.DataFrame({
        "start.x": c.start_x, "start.y": c.start_y, "start.z": c.start_z,
        "axis.x": c.axis_x, "axis.y": c.axis_y, "axis.z": c.axis_z,
        "end.x": c.end_x, "end.y": c.end_y, "end.z": c.end_z,
        "length": c.length,
        "radius": np.array(new),
        "OldRadius": np.array(old),
        "UnmodRadius": 1.25 * np.array(old),  # distinct from both, to check the mapping
        "parent": c.parent,
        "extension": [2, 3, 4, 0, 6, 0, 0],
        "added": [False] * (n - 1) + [True],  # the order-2 cylinder is a TreeQSM gap filler
        "BranchOrder": c.branch_order,
        "PositionInBranch": c.branch_position,
        "branch": c.branch,
        "modified": [False] * len(STEM_R) + [True] * (n - len(STEM_R)),
    })


def _vol(cyls):
    return sum(np.pi * r**2 * length for r, length in cyls)


STEM_V = _vol((r, 1.0) for r in STEM_R)
ORDER1_NEW = _vol((r_new, length) for _, r_new, length in ORDER1)
ORDER1_OLD = _vol((r_old, length) for r_old, _, length in ORDER1)
ORDER2_NEW = _vol((r_new, length) for _, r_new, length in ORDER2)
ORDER2_OLD = _vol((r_old, length) for r_old, _, length in ORDER2)


def test_native_id():
    assert rtwig.native_id("belgian:PSYLA-01") == "PSYLA-01"
    assert rtwig.native_id("belgian:a:b") == "a:b"  # only the dataset prefix is stripped


def test_read_cylinders_renames_to_treewm_columns(tmp_path):
    src = synthetic_rtwig_table()
    d = rtwig.read_cylinders(write_rtwig_csv(tmp_path / "t.csv", src))

    assert list(d.columns) == [
        "id", "start_x", "start_y", "start_z", "axis_x", "axis_y", "axis_z",
        "end_x", "end_y", "end_z", "length", "radius", "treeqsm_radius", "raw_radius",
        "parent", "extension", "added", "branch_order", "branch_position", "branch", "rtwig_modified",
    ]
    assert set(CYLINDER_COLUMNS) <= set(d.columns)
    assert d["id"].tolist() == list(range(1, len(src) + 1))
    np.testing.assert_array_equal(d["radius"], src["radius"])  # corrected radius
    np.testing.assert_array_equal(d["treeqsm_radius"], src["OldRadius"])
    np.testing.assert_array_equal(d["raw_radius"], src["UnmodRadius"])
    np.testing.assert_array_equal(d["branch_order"], src["BranchOrder"])
    np.testing.assert_array_equal(d["branch_position"], src["PositionInBranch"])
    np.testing.assert_array_equal(d["rtwig_modified"], src["modified"])
    np.testing.assert_array_equal(d[["start_x", "start_y", "start_z"]], src[["start.x", "start.y", "start.z"]])
    np.testing.assert_array_equal(d[["end_x", "end_y", "end_z"]], src[["end.x", "end.y", "end.z"]])
    assert d["added"].dtype == bool
    assert d["added"].tolist() == src["added"].tolist()


def test_read_cylinders_added_from_integers(tmp_path):
    # added written as 0/1 must still come back as a boolean mask (not integer indices)
    src = synthetic_rtwig_table().assign(added=lambda t: t["added"].astype(int))
    d = rtwig.read_cylinders(write_rtwig_csv(tmp_path / "t.csv", src))
    assert d["added"].dtype == bool
    assert d["added"].tolist() == [False] * (len(src) - 1) + [True]


def test_read_cylinders_works_with_qsm_features(tmp_path):
    d = rtwig.read_cylinders(write_rtwig_csv(tmp_path / "t.csv", synthetic_rtwig_table()))
    f = qsm_features(d)
    total = STEM_V + ORDER1_NEW + ORDER2_NEW
    assert f["qsm_volume_total_m3"] == pytest.approx(total, rel=1e-9)
    assert f["qsm_volume_stem_m3"] == pytest.approx(STEM_V, rel=1e-9)
    assert f["qsm_volume_order1_m3"] == pytest.approx(ORDER1_NEW, rel=1e-9)
    assert f["qsm_volume_order2plus_m3"] == pytest.approx(ORDER2_NEW, rel=1e-9)
    assert f["qsm_added_fraction"] == pytest.approx(ORDER2_NEW / total, rel=1e-9)
    assert f["qsm_dbh_cm"] == pytest.approx(200 * STEM_R[1], rel=1e-9)  # 1.3 m is in cylinder 2
    assert f["qsm_height_m"] == pytest.approx(len(STEM_R), rel=1e-9)
    assert f["qsm_crown_base_m"] == pytest.approx(2.0, rel=1e-9)
    assert f["qsm_n_cylinders"] == 7
    assert f["qsm_n_branches"] == 2
    assert f["qsm_max_order"] == 2


@pytest.fixture
def work(tmp_path, monkeypatch):
    w = tmp_path / "rtwig"
    monkeypatch.setattr(rtwig, "WORK", w)
    return w


def test_rtwig_features_analytic(work):
    write_rtwig_csv(work / "cylinders" / "PSYLA-01.csv", synthetic_rtwig_table())
    row = rtwig.rtwig_features("belgian:PSYLA-01")

    new_total = STEM_V + ORDER1_NEW + ORDER2_NEW
    old_total = STEM_V + ORDER1_OLD + ORDER2_OLD
    assert row["tree_id"] == "belgian:PSYLA-01"
    assert not [k for k in row if k.startswith("qsm_")]
    # every QSM feature is also computed from the uncorrected radii, for build()'s consistency check
    expected = {k.replace("qsm_", "check_", 1) for k in qsm_features(rtwig.read_cylinders(work / "cylinders" / "PSYLA-01.csv"))}
    assert {k for k in row if k.startswith("check_")} == expected

    assert row["rtwig_volume_total_m3"] == pytest.approx(new_total, rel=1e-9)
    assert row["check_volume_total_m3"] == pytest.approx(old_total, rel=1e-9)
    assert row["rtwig_volume_branch_m3"] == pytest.approx(ORDER1_NEW + ORDER2_NEW, rel=1e-9)
    assert row["rtwig_volume_order1_m3"] == pytest.approx(ORDER1_NEW, rel=1e-9)
    assert row["rtwig_volume_order2plus_m3"] == pytest.approx(ORDER2_NEW, rel=1e-9)
    assert row["rtwig_log_shrink"] == pytest.approx(np.log(new_total / old_total), rel=1e-9)
    assert row["rtwig_log_shrink"] < 0
    assert row["rtwig_modified_fraction"] == pytest.approx(3 / 7, rel=1e-9)
    # stem radii are unchanged, so the stem volume is too
    assert row["rtwig_volume_stem_m3"] == pytest.approx(STEM_V, rel=1e-9)
    assert row["check_volume_stem_m3"] == pytest.approx(STEM_V, rel=1e-9)


def test_rtwig_features_no_correction_gives_zero_shrink(work):
    t = synthetic_rtwig_table()
    write_rtwig_csv(work / "cylinders" / "T1.csv", t.assign(radius=t["OldRadius"], modified=False))
    row = rtwig.rtwig_features("ds:T1")
    assert row["rtwig_volume_total_m3"] == pytest.approx(row["check_volume_total_m3"], rel=1e-9)
    assert row["rtwig_log_shrink"] == pytest.approx(0.0, abs=1e-12)
    assert row["rtwig_modified_fraction"] == 0.0


def test_find_rscript_raises_when_nothing_found(tmp_path, monkeypatch):
    monkeypatch.delenv("TREEWM_RSCRIPT", raising=False)
    monkeypatch.setattr(rtwig.shutil, "which", lambda *a, **k: None)
    with pytest.raises(FileNotFoundError):
        rtwig.find_rscript(str(tmp_path / "missing" / "Rscript.exe"))
    with pytest.raises(FileNotFoundError):
        rtwig.find_rscript()


def test_find_rscript_uses_env_var(tmp_path, monkeypatch):
    exe = tmp_path / "Rscript.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("TREEWM_RSCRIPT", str(exe))
    monkeypatch.setattr(rtwig.shutil, "which", lambda *a, **k: None)
    assert rtwig.find_rscript() == str(exe)
    with pytest.raises(FileNotFoundError):  # a wrong explicit path is an error, not a silent fallback
        rtwig.find_rscript(str(tmp_path / "missing.exe"))


def test_find_rscript_order_argument_env_path(tmp_path, monkeypatch):
    arg, env, on_path = (tmp_path / f"{n}.exe" for n in ("arg", "env", "path"))
    for p in (arg, env, on_path):
        p.write_bytes(b"")
    monkeypatch.setenv("TREEWM_RSCRIPT", str(env))
    monkeypatch.setattr(rtwig.shutil, "which", lambda *a, **k: str(on_path))
    assert rtwig.find_rscript(str(arg)) == str(arg)
    monkeypatch.delenv("TREEWM_RSCRIPT")
    assert rtwig.find_rscript() == str(on_path)


def _treeqsm_mat(path):
    """A Belgian-style TreeQSM .mat: `qsm` plus the `optmodels` and `vresults` rTwig rejects."""
    c = stem_with_branch()
    cylinder = {
        "radius": c.radius.to_numpy()[:, None], "length": c.length.to_numpy()[:, None],
        "start": c[["start_x", "start_y", "start_z"]].to_numpy(),
        "axis": c[["axis_x", "axis_y", "axis_z"]].to_numpy(),
        "parent": c.parent.to_numpy(float)[:, None], "extension": np.zeros((len(c), 1)),
        "added": c.added.to_numpy(float)[:, None], "UnmodRadius": c.raw_radius.to_numpy()[:, None],
        "branch": c.branch.to_numpy(float)[:, None], "BranchOrder": c.branch_order.to_numpy(float)[:, None],
        "PositionInBranch": c.branch_position.to_numpy(float)[:, None],
    }
    sio.savemat(path, {
        "qsm": {"cylinder": cylinder, "treedata": {"TotalVolume": 1234.5}},
        "optmodels": np.arange(1, 4, dtype=float),
        "vresults": {"Volume": np.ones((3, 1))},
    })
    return path


def test_write_qsm_only_keeps_only_qsm(tmp_path):
    src = _treeqsm_mat(tmp_path / "src.mat")
    assert sorted(n for n, *_ in sio.whosmat(src)) == ["optmodels", "qsm", "vresults"]
    dst = tmp_path / "dst.mat"

    assert rtwig.write_qsm_only(str(src), dst) == dst
    assert [n for n, *_ in sio.whosmat(dst)] == ["qsm"]
    assert [k for k in sio.loadmat(dst) if not k.startswith("__")] == ["qsm"]
    # the qsm struct survives: same cylinders and tree data as the source
    c_src, td_src = read_treeqsm(src)
    c_dst, td_dst = read_treeqsm(dst)
    pd.testing.assert_frame_equal(c_dst, c_src)
    pd.testing.assert_frame_equal(c_dst, stem_with_branch(), check_dtype=False)
    assert td_dst["TotalVolume"] == td_src["TotalVolume"] == 1234.5


def test_write_qsm_only_does_not_rewrite_existing(tmp_path):
    src = _treeqsm_mat(tmp_path / "src.mat")
    dst = tmp_path / "dst.mat"
    dst.write_bytes(b"already here")
    mtime = dst.stat().st_mtime_ns
    assert rtwig.write_qsm_only(src, dst) == dst
    assert dst.read_bytes() == b"already here"
    assert dst.stat().st_mtime_ns == mtime


def test_done_reruns_stale_or_smoothed_outputs(tmp_path):
    out = tmp_path / "T1.csv"
    assert not rtwig._done(out, "Pinus sylvestris")  # nothing written yet
    out.write_text("x\n1\n")
    meta = tmp_path / "T1.csv.meta.csv"
    pd.DataFrame({"tree_id": ["ds:T1"], "twig_radius_mm": [3.01]}).to_csv(meta, index=False)
    assert not rtwig._done(out, "Pinus sylvestris")  # made before species and smoothing were recorded
    pd.DataFrame({"tree_id": ["ds:T1"], "species_latin": ["Pinus sylvestris"], "smooth": [True]}).to_csv(meta, index=False)
    assert not rtwig._done(out, "Pinus sylvestris")  # smoothed run
    pd.DataFrame({"tree_id": ["ds:T1"], "species_latin": ["Pinus sylvestris"], "smooth": [False]}).to_csv(meta, index=False)
    assert rtwig._done(out, "Pinus sylvestris")
    assert not rtwig._done(out, "Larix decidua")  # species changed
