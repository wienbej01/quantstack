# Sprint 3 – ATR Big-Move Target Specification

This document captures the Sprint 3 label definition and training contract for
the new ATR-based big-move models. It is written for Codex CLI contributors who
maintain the intraday ML pipeline.

## 1. Label definition

* Big-move flag (`y_bigmove`)
  * A bar qualifies as a big move when the forward return over the configured
    horizon exceeds the larger of:
    * `atr_multiple * atr_return` (ATR expressed in return terms) and
    * `min_return_floor_pct`.
  * The default configuration uses a 60-minute horizon on 10-minute bars,
    `atr_multiple = 1.5`, and `min_return_floor_pct = 0.75%`.
  * The threshold is computed per timestamp → no symbol-level lookahead is
    required.
* Direction label (`y_bigmove_direction`)
  * `+1` for qualifying positive moves, `-1` for qualifying negative moves,
    `0` otherwise.
  * Only defined when `y_bigmove == 1`.
* Forward return column (`fwd_return_bigmove`)
  * Deterministic forward return (next-bar open to horizon close). Used for
    diagnostics and Stage 2 regression targets.

Refer to `extensions/intraday_ml/labeling/big_move_labels.py` and
`configs/extensions/intraday_ml/targets_bigmove.yaml` for the source-of-truth
implementation.

## 2. Data contract

The labeler expects the following columns on the 10-minute bar dataset:

| Column                | Description                                |
|-----------------------|--------------------------------------------|
| `symbol`              | String ticker identifier                   |
| `ts`                  | Timestamp (UTC)                            |
| `close`               | Decision-bar close price                   |
| `f__vol__atr_6`       | ATR feature expressed as percentage return |

Key parameters (see `targets_bigmove.yaml` under `big_move`):

* `bar_minutes`: 10
* `forward_minutes`: 60 (with optional 120-minute variant)
* `atr_multiple`: 1.5
* `min_return_floor_pct`: 0.0075 (75 bps)
* `atr_is_return_pct`: true (ATR column already normalized by price)
* `realized_r_floor` / `realized_r_cap`: winsorization bounds for regression

## 3. Training pipeline

Defined in `extensions/intraday_ml_models/train_lgbm_bigmove.py`.

1. **Stage 1 – Big-Move probability**
   * Model: `LGBMClassifier` (binary).
   * Input label: `y_bigmove`.
   * Metrics: accuracy, precision, recall, F1, log-loss, ROC‑AUC.

2. **Stage 2a – Directional odds**
   * Condition on `y_bigmove == 1`.
   * Label mapping: `-1 → 0`, `+1 → 1`.
   * Model+metrics identical to Stage 1.

3. **Stage 2b – Expected R regression**
   * Condition on `y_bigmove == 1`.
   * Target: `realized_r_bigmove` after winsorising to the configured
     floor/cap.
   * Model: `LGBMRegressor`.
   * Metrics: MAE, RMSE, R².

Splitting: each stage uses a deterministic `train_test_split` with
`validation_split` sourced from respective stage configs (default 25%).

## 4. Tests and validation

* Label regression coverage:
  * `pytest tests/extensions/intraday_ml/test_big_move_labels.py`
* Legacy labeler sanity (ensures packaging change does not regress):
  * `pytest tests/extensions/intraday_ml/test_compute_label_for_timestamp.py`
* Training harness:
  * `pytest tests/extensions/intraday_ml_models/test_train_lgbm_bigmove.py`

These suites run deterministically and should be executed before shipping any
changes to labels or training logic.
