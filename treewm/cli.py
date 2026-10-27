"""treewm command line: download | ingest | features | evaluate | figures | train | predict."""
from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main():
    """Tree World Model: LiDAR geometry, volume and biomass estimation."""


@app.command()
def download(datasets: list[str] = typer.Argument(..., help="belgian, biodiv, ceda, treescope, treescanpl10k"),
             parts: Optional[str] = typer.Option(None, help="Comma-separated file keys, e.g. labels,graphs,uls,tls")):
    """Download raw datasets into data/raw/<dataset>/."""
    from treewm.io.download import download as dl
    plist = parts.split(",") if parts else None
    for d in datasets:
        dl(d, plist)


@app.command()
def ingest():
    """Build trees / measurements / cylinder tables from data/raw/."""
    from treewm.data.build import build
    print(build())


@app.command()
def features(datasets: str = typer.Option("belgian,biodiv", help="Comma-separated datasets"),
             workers: Optional[int] = typer.Option(None, help="Parallel worker processes")):
    """Extract point-cloud and QSM geometry features."""
    from treewm.geometry.build import build_features
    print(build_features(tuple(datasets.split(",")), workers))


@app.command()
def evaluate(experiments: str = typer.Option("belgian,ceda,biodiv", help="Comma-separated experiments"),
             out: str = typer.Option("experiments/v1-residuals", help="Report folder (metrics.csv, tables.md, figures)"),
             jobs: int = typer.Option(-1, help="Parallel worker processes (-1 = all cores, 1 = serial)")):
    """Run the v1 cross-validated experiments and write the result tables."""
    import pandas as pd

    from treewm import experiments as ex
    from treewm.eval.report import write_report
    from treewm.paths import OUTPUTS, ROOT
    runners = {"belgian": ex.run_belgian, "ceda": ex.run_ceda, "biodiv": ex.run_biodiv}
    names = [n for n in experiments.split(",") if n]
    P, R = [], []
    pred_path, met_path = OUTPUTS / "predictions_v1.parquet", ROOT / out / "metrics.csv"
    if pred_path.exists() and met_path.exists():  # keep results of experiments not rerun
        old_p, old_m = pd.read_parquet(pred_path), pd.read_csv(met_path)
        P.append(old_p[~old_p.experiment.isin(names)]); R.append(old_m[~old_m.experiment.isin(names)])
    for name in names:
        p, r = runners[name](n_jobs=jobs)
        P.append(p); R.append(r)
    preds, metrics = pd.concat(P, ignore_index=True), pd.concat(R, ignore_index=True)
    OUTPUTS.mkdir(exist_ok=True)
    preds.to_parquet(pred_path, index=False)
    print(write_report(preds, metrics, ROOT / out))


@app.command()
def figures(out: str = typer.Option("experiments/v1-residuals", help="Report folder written by `treewm evaluate`")):
    """Draw the explanatory report figures (example tree, geometry checks, ablation, per species)."""
    from treewm.eval.figures import build
    from treewm.paths import ROOT
    for p in build(ROOT / out):
        print(p)


@app.command()
def train(metrics: str = typer.Option("experiments/v1-residuals/metrics.csv", help="Metrics from `treewm evaluate`")):
    """Fit the deployable model bundle on all Belgian trees (scan-only inputs)."""
    from treewm.deploy import train as tr
    from treewm.paths import ROOT
    print(tr(ROOT / metrics))


@app.command()
def predict(cloud: str = typer.Argument(..., help="Single-tree point cloud (.laz/.las/.txt/.xyz/.pcd)"),
            species: Optional[str] = typer.Option(None, help="Latin name, e.g. 'Pinus sylvestris'"),
            leaf_type: Optional[str] = typer.Option(None, help="conifer or broadleaf (if species unknown)"),
            qsm: Optional[str] = typer.Option(None, help="Optional TreeQSM .mat for the same tree"),
            out: Optional[str] = typer.Option(None, help="Write JSON here instead of stdout")):
    """Estimate geometry, volume and mass for one tree scan."""
    from pathlib import Path

    from treewm.deploy import predict as pr
    from treewm.deploy import to_json
    s = to_json(pr(cloud, species, leaf_type, qsm))
    if out:
        Path(out).write_text(s)
    print(s)


if __name__ == "__main__":
    app()
