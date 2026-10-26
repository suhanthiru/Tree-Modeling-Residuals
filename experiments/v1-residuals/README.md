# v1 — Residual corrections over allometry

**Status:** done · **Code:** tag `v1.0` · **Full write-up:** [report.md](report.md)

## Question

Does a learned correction (a residual on top of a classical allometric equation), fed with
geometry measured from a LiDAR scan, predict tree volume and mass better than the equation
alone, on whole sites or whole studies the model has never seen?

## Setup

- **Data:** Belgian destructive harvest (65 trees, 4 species, 5 sites), the global TLS vs
  harvest compilation (373 trees, 9 studies), BioDiv-3DTrees (QSM volume as a reconstructed
  target only).
- **Models:** every model predicts log(target). Baselines are fitted allometry, published
  allometry and QSM estimates. Residual models (ridge, XGBoost, GP, ensemble) add a correction
  using feature sets A–E (DBH → + height and leaf type → + stem form → + crown → + QSM structure).
- **Evaluation:** leave-one-site-out (Belgian), leave-one-study-out (compilation), plot-grouped
  5-fold (BioDiv). Inner CV sets the back-transform smearing factor and 90 % conformal intervals.
- **Definition:** [config.yaml](config.yaml).

## Results

**Belgian harvest, 65 trees, whole site held out, DBH and height taken from the scan.**
Relative mean absolute error per tree (%):

| Target | DBH allometry | QSM-based | Best residual model | 90 % interval coverage |
|---|---|---|---|---|
| Fresh mass | 14.8 | 32.3 (QSM × fold density) | 11.4 (D over A, ensemble) | 0.94 |
| Dry AGB | 17.5 | 17.8 (QSM × fold density); published allometry 36.5 | 9.8 (E over A, ensemble) | 0.94 |
| Total woody volume | 10.6 | 18.4 (raw QSM) | 7.7 (E over A, ensemble) | 0.91 |
| Stem volume | 18.3 | 13.9 (raw QSM); 14.3 (point-cloud slices) | 11.6 (D, ridge) | 0.92 |

**Global compilation, dry AGB, 373 trees, whole study held out (9 studies).**

| Model | relMAE % | log RMSE | 90 % coverage |
|---|---|---|---|
| Published allometry (as reported) | 32.9 | 0.369 | 0.90 |
| TLS-QSM (as reported) | 21.9 | 0.288 | 0.90 |
| Published allometry + residual from inventory only | 31.7 | 0.357 | 0.89 |
| Published allometry + residual with TLS-QSM terms | 17.3 | 0.216 | 0.91 |

**BioDiv, QSM volume as a reconstructed target, whole plot held out.** Adding drone (ULS)
crown geometry lowers log RMSE from 0.398 (DBH + height + genus) to 0.365.

## Takeaways

- Learned corrections help when they sit on top of DBH-only allometry and use scan-derived
  geometry (crown shape, QSM structure). Re-weighting inventory variables alone does not help.
- Height + leaf-type allometry fitted on other species transfers worse than DBH alone for
  fresh mass. The four species differ too much in height-to-mass relations.
- QSM volume overestimates harvested volume by about 25 %, by an amount that depends on species
  (about 2x for one larch). Used raw it is worse than DBH allometry, but it is a strong residual
  feature. This is the starting point for [v1.1](../README.md).
- Interval coverage holds near 90 % for the residual models on unseen sites. The DBH-only
  fresh-mass baseline undercovers at 0.81.
- Caveat: about 25 models are scored on the same folds, so the best numbers are slightly
  optimistic. The "E over A, ensemble" model is best or close to best on every target.

## Reproduce

```bash
uv run treewm evaluate
uv run treewm figures
uv run treewm train
```

(after `download`, `ingest` and `features`; see the [top-level README](../../README.md#pipeline)).

## Files

| File | Contents |
|---|---|
| [report.md](report.md) | Full write-up: data, geometry, models, ablation, per-species and per-study results |
| [tables.md](tables.md) | Every model × target × scenario × scheme |
| [metrics.csv](metrics.csv) | Machine-readable metrics for all 430 evaluated combinations |
| [by_group.csv](by_group.csv) | Per-species and per-study errors |
| [geometry_validation.csv](geometry_validation.csv) | Scan and QSM geometry against field and harvest values |
| figures/ | Figures used in the report |
