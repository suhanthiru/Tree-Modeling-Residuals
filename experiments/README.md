# Experiments

Each experiment is one self-contained folder. Shared code lives in `treewm/`; an experiment
folder holds only what defines it and what it produced.

| Experiment | Question | Status | Headline |
|---|---|---|---|
| [v1-residuals](v1-residuals/) | Do learned corrections on top of allometry beat allometry on unseen sites? | done (`v1.0`) | Dry AGB relMAE 17.5 % → 9.8 % on held-out Belgian sites |
| v1.1-rtwig | Does correcting QSM twig radii with rTwig make QSM volume a better estimate and a better residual feature? | planned | — |

## Conventions

- **Naming:** `v<stage>.<n>-<short-name>`. The stage follows the roadmap (v1 forestry
  estimation, v2 learned 3D representations, …); `.n` numbers sub-experiments within a stage.
- **Contents of a folder:**
  - `README.md`: question, setup, results table, takeaways, how to reproduce, code version.
  - `config.yaml`: the experiment definition the code reads.
  - Results (`metrics.csv`, `tables.md`, `figures/`) written by `treewm` commands. A longer
    hand-written `report.md` is optional.
- **Comparability:** a sub-experiment reuses its parent's folds, targets and learners and
  changes one thing, so its numbers can be read against the parent's directly.
- **Provenance:** when an experiment is finished, tag the commit that produced its numbers
  (`v1.0`, `v1.1`, …) and name the tag in its README.
- **Workflow:** one branch and one pull request per experiment. The PR description records
  what changed and what was found.
- Large or regenerable files (raw data, predictions, model bundles, logs) stay in `data/` and
  `outputs/`, which are not in git.
