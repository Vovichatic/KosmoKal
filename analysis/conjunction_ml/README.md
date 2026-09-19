# ML forecast of final conjunction risk

This experiment trains two CatBoost models on the official ESA Collision
Avoidance Challenge CDM sequences:

- a high-risk classifier for `final log10(Pc) >= -6`, optimized around F2;
- a residual regressor for final `log10(Pc)` on high and borderline events.

Every feature is built only from CDMs available at least two days before TCA.
The final CDM is used solely as the label. Events, rather than individual CDM
rows, are split between train, validation and holdout test.

## Result

The final holdout contains 1,659 test-like events whose last label CDM arrived
within one day of TCA. Only 0.78% are high risk. The label row is always removed
from model inputs, including older-ending auxiliary sequences.

| Model | PR-AUC | Precision | Recall | F2 |
|---|---:|---:|---:|---:|
| Hybrid CDM + CatBoost | **0.146** | **0.140** | **0.615** | **0.367** |
| Latest known risk baseline | 0.072 | 0.127 | 0.538 | 0.327 |

High-risk final-risk RMSE improves from 1.377 log10 units for the strongest
causal baseline (`risk_max`) to 0.794 for the residual CatBoost. Because the
holdout contains only 13 positive events, these estimates have high sampling
uncertainty and should be accompanied by cross-validation or bootstrap ranges.

The hybrid is deliberately monotonic with respect to an existing CDM alert:
ML may add an early warning, but it cannot suppress a warning already implied
by the latest published `risk` value.

These are conjunction-risk metrics for tracked objects. They are not a
probability of a fragment striking an astronaut and do not model untracked
micrometeoroids.

## Reproduce

Download `train_data.zip` and `test_data.csv` from the ESA challenge data page,
extract `train_data.csv`, then run:

```bash
python3 analysis/conjunction_ml/train_esa_cdm.py
```

Inference for a CSV with the ESA CDM schema:

```bash
python3 analysis/conjunction_ml/predict_cdm.py input.csv predictions.csv
```

Raw downloads and the 42 MB/8 MB event tables are excluded from Git. Compact
models, metrics, feature importance and challenge predictions are retained.

`challenge_submission.csv` contains exactly the two columns required by the
ESA competition format. `challenge_predictions.csv` additionally retains the
classifier probability for analysis and operational thresholding.
