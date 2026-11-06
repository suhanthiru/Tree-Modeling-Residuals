# v1.1 follow-up: where the density comes from

Written by `treewm density-check`. Dry biomass of the 65 Belgian trees; every estimate that
learns a number learns it with the tree's whole site held out. Errors are mean absolute error
per tree, % of harvested dry biomass. Densities are in kg of dry mass per m3.

The learned densities here are plain geometric means, without the smearing step of the main
v1.1 run, so the v1.1 model shows a slightly lower error here than in [tables.md](tables.md).

Published densities: basic wood density of stemwood from IPCC Good Practice Guidance for LULUCF (2003), table 3A.1.9-1, as reproduced in FAO Global Forest Resources Assessment 2005, guidelines for country reporting, appendix 5, table 5.2 (https://www.fao.org/4/j2132e/J2132e16.htm). Row source for every value below: Dietz (1975), Holz Roh- Werkstoff 33: 135-141.

## 1. Error by density source

| model | fitted | all | bias | Beech | Ash | Larch | Scots pine |
|---|---|---|---|---|---|---|---|
| TreeQSM volume x published density | 0 | 26.2 | 23.8 | 28.1 | 34.7 | 101.3 | 8.3 |
| rTwig volume x published density | 0 | 13.5 | -10.5 | 6.6 | 5.0 | 14.9 | 20.9 |
| rTwig volume x published density x one learned factor | 1 | 15.1 | 1.6 | 20.4 | 15.5 | 4.4 | 14.0 |
| rTwig volume x published density x learned factor per leaf type | 2 | 7.9 | 0.2 | 6.8 | 5.6 | 8.5 | 9.5 |
| rTwig volume x learned density per leaf type (v1.1 model) | 2 | 7.3 | 0.5 | 6.5 | 5.0 | 3.4 | 9.4 |
| rTwig volume x the tree's own base-disc density | 0 | 9.4 | -8.2 | 5.0 | 6.3 | 7.5 | 13.5 |
| Published allometry chosen by the data owners | 0 | 28.1 | 5.2 | 13.8 | 59.7 | 15.2 | 21.6 |


## 2. Densities per species

Fresh mass / rTwig volume is the fresh density the same model would need for fresh mass.

| species | leaf type | trees | published density | published row | measured base-disc density | dry mass / rTwig volume | fresh mass / rTwig volume | harvested volume / rTwig volume |
|---|---|---|---|---|---|---|---|---|
| Beech | broadleaf | 15 | 580 | Fagus sylvatica | 559 | 569 | 1059 | 1.03 |
| Ash | broadleaf | 15 | 570 | Fraxinus | 549 | 577 | 849 | 1.02 |
| Larch | conifer | 5 | 460 | Larix decidua | 500 | 541 | 955 | 1.10 |
| Scots pine | conifer | 30 | 420 | Pinus sylvestris | 462 | 534 | 1064 | 1.21 |
| all broadleaf | broadleaf | 30 |  |  |  | 573 |  |  |
| all conifer | conifer | 35 |  |  |  | 535 |  |  |


## 3. The density a held-out site gets

| site held out | species | own dry mass / rTwig volume | learned per leaf type | published x factor per leaf type | learned from |
|---|---|---|---|---|---|
| FEXC | Ash | 577 | 569 | 559 | Beech |
| FSYL | Beech | 569 | 577 | 587 | Ash |
| LXDC | Larch | 541 | 534 | 584 | Scots pine |
| PSYLA | Scots pine | 551 | 523 | 511 | Larch, Scots pine |
| PSYLB | Scots pine | 517 | 548 | 536 | Larch, Scots pine |


## 4. Learned density per leaf type against published density x factor per leaf type

Published minus learned: +0.63 percentage points of mean error, 95 % bootstrap interval -0.08 to +1.37 (over trees, ignoring that trees of a site share errors). The learned density is closer on 39 of 65 trees.

By species (percentage points): Beech +0.2, Ash +0.6, Larch +5.1, Scots pine +0.1.
