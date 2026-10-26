"""treewm command line: download | ingest | features | train | evaluate | predict."""
from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main():
    """Tree World Model v1: LiDAR geometry, volume and biomass estimation."""


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


if __name__ == "__main__":
    app()
