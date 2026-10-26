# Tree Modeling Residuals

Tree World Model: estimate tree geometry, volume and biomass from LiDAR, and test whether
learned corrections (residuals) to classical allometric equations actually improve on them.
Every claim is checked against destructively harvested trees, with whole sites or whole studies
held out.

This is the first stage of a longer programme: forestry estimation first, then a physical
world model (mass distribution, gravitational moments, eventually fall dynamics). See
[Roadmap](#roadmap).

## Experiments

| Experiment | Question | Status | Headline |
|---|---|---|---|
| [v1 · residuals](experiments/v1-residuals/) | Do learned corrections on top of allometry beat allometry on unseen sites? | done (`v1.0`) | Dry AGB error 17.5 % → 9.8 % on held-out Belgian sites; 32.9 % → 17.3 % on held-out studies worldwide |
| v1.1 · rTwig | Does correcting QSM twig radii with rTwig make QSM volume a better estimate and a better residual feature? | planned | — |

Each experiment has its own folder with a README (question, setup, results, how to reproduce),
its config and its outputs. Conventions are in [experiments/README.md](experiments/README.md).

**v1 in short.** Learned corrections help when they sit on top of DBH-only allometry and use
scan-derived geometry (crown shape, QSM structure); re-weighting inventory variables alone does
not. QSM volume overestimates harvested volume by about 25 %, species-dependently, so it is
worse than DBH allometry used raw but a strong feature for the correction. Interval coverage
holds near 90 % on unseen sites. Details: [experiments/v1-residuals](experiments/v1-residuals/),
full write-up in [report.md](experiments/v1-residuals/report.md).

## Pipeline

```
download → ingest → features → evaluate → figures → train → predict
```

| Step | Command | What it does |
|---|---|---|
| Download | `uv run treewm download belgian ceda biodiv` | Fetches raw data into `data/raw/<dataset>/` with size checks and resumable transfers. BioDiv TLS (20 GB) is opt-in with `--parts tls`. |
| Ingest | `uv run treewm ingest` | Builds `trees`, `measurements` (long format, one unit and one definition per quantity, tagged measured / reconstructed / derived) and QSM cylinder tables as Parquet. |
| Features | `uv run treewm features` | Point-cloud stem tracking and crown geometry, QSM structure metrics, BioDiv graph and drone (ULS) features. Runs in parallel. |
| Evaluate | `uv run treewm evaluate` | Runs the three cross-validated v1 experiments and writes `metrics.csv`, `tables.md` and the measured-vs-predicted figures into `experiments/v1-residuals/`. |
| Figures | `uv run treewm figures` | Draws the explanatory figures in the report (example tree, geometry checks, ablation, per species and per study). |
| Train | `uv run treewm train` | Fits the deployable bundle on all Belgian trees with scan-only inputs. |
| Predict | `uv run treewm predict tree.laz --species "Pinus sylvestris" [--qsm tree.mat]` | JSON with DBH, height, lean, crown offset, stem volume, baseline and corrected volume/mass with 90 % intervals, extrapolation flags, and (with a QSM) centre of mass and base moments. |

Setup needs [uv](https://docs.astral.sh/uv/) and Python 3.12: `uv sync`, then `uv run pytest`.

## Data

| Dataset | Used for | Ground truth |
|---|---|---|
| [Belgian destructive harvest](https://zenodo.org/records/4557401) (Demol et al. 2021) | Main experiment: 65 trees, 4 species, 5 sites, TLS clouds + TreeQSM | Fresh mass (total/stem/crown), disc densities, harvest volume |
| [Global TLS vs harvest compilation](https://catalogue.ceda.ac.uk/uuid/ddcad11fd71245d3b9d0e669b3fd9169/) (Demol et al. 2025) | External benchmark: 10 studies, 391 trees, tabular | Dry AGB, plus each study's allometric and QSM estimates |
| [BioDiv-3DTrees](https://doi.org/10.25625/8PB1IF) (Griese et al. 2025) | Scale: 4,952 trees, drone clouds, 3,386 QSM graphs | None physical; QSM volume used as a reconstructed target only |

All three are CC BY 4.0. Provenance notes:

- The CEDA compilation contains the same 65 Belgian trees (author `Demol2021`). Their rows are
  attached to the Belgian tree ids, so they add dry AGB and the published allometric estimate
  and can never leak into the external benchmark as separate trees.
- Belgian CSV units are undocumented. The ingest checks them: masses kg, densities g/cm³,
  harvest and QSM volumes litres, `qsm_DBHqsm` metres. One scanned tree (FEXC12) has no
  harvest row and is kept as an unlabelled tree.
- BioDiv graphs rebuilt into cylinders give about 3 % more volume than the published
  `volQSM` (median ratio 1.03), consistent across trees.
- TreeScope, TreeScanPL10K (94 GB) and Shivalik (access-restricted) are in the manifest but
  not used in v1.

## Method

**Geometry.** The stem is tracked upward in 10 cm slices with RANSAC circle fits, giving DBH,
lean (overall, base, at cut height), sweep, curvature, taper and stem volume (integrated under
a non-increasing radius profile so forks cannot inflate it). Crown metrics are computed on a
10 cm voxel grid so scan density does not bias them: crown base, width by azimuth sector,
projection and hull areas, centroid offset from the stem base, sector asymmetry and a
completeness score. QSM metrics add stem/branch volume, branch-order volumes, branch
asymmetry, centre of mass and base moments.

**Models.** Every model predicts log(target). Baselines are fitted-in-fold allometry
(`log y = a + b log D` and `+ c log H + leaf type`), the published allometry and QSM estimates
as reported by the data owners, and QSM volume × a fold-learned effective density. Residual
models add `f(X)` to a baseline: ridge, XGBoost (depth 2, strong regularisation), a Gaussian
process, and their average. Feature sets follow the ablation in the design doc: A DBH, B + height
and leaf type, C + stem form, D + crown, E + QSM structure.

**Evaluation.** Outer folds are leave-one-site-out for the Belgian trees (close to
leave-one-species-out, since four of five sites are single-species), leave-one-study-out for
the compilation, and plot-grouped 5-fold for BioDiv. Inside each training fold an inner CV sets
Duan's smearing factor for the back-transform and split-conformal 90 % interval widths.

## Repository layout

```
experiments/  one folder per experiment: README, config.yaml, results, figures
configs/      datasets.yaml (download manifest), allometry/published.yaml
treewm/io/    downloads, archive extraction, point cloud and TreeQSM readers
treewm/data/  schema (quantity registry) and per-dataset ingest
treewm/qsm/   cylinder metrics, centre of mass, base moments, GraphML → cylinders
treewm/geometry/  stem tracking, crown metrics, feature pipeline
treewm/baselines/, treewm/models/  allometry, feature sets, residual learners
treewm/eval/  CV schemes, nested CV engine, metrics, result tables, report figures
treewm/experiments.py, treewm/deploy.py, treewm/cli.py
tests/        unit tests on synthetic trees
data/, outputs/   local only (gitignored)
```

## Roadmap

From the design document, after v1:

- **V2, learned 3D representations.** Add TreeScanPL10K and Shivalik; pretrain a PointNet++
  encoder on thousands of scans with geometric targets, try graph networks over QSMs, and
  compare learned features with the handcrafted ones on the same held-out sites.
- **V3, probabilistic structural model.** Distributions over hidden branches, density
  allocation and centre of mass for partial scans; Bayesian propagation of density and
  reconstruction uncertainty; possibly conditional generative completion.
- **V4, dynamics.** Calibrated rigid / multibody felling simulation seeded by the mass
  distribution (`treewm predict --qsm` already reports centre of mass, gravity moment and
  inertia about the base), then residual correction against observed felling outcomes.

Main limitation of v1: only 65 harvested trees from 4 European species. Results show what
transfers between these sites, not a validated estimator for other regions or species.

## License

Code is MIT ([LICENSE](LICENSE)). The datasets are CC BY 4.0 and belong to their authors; cite
them as listed under [Data](#data).
