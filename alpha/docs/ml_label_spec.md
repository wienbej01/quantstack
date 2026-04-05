# ML Label Specification

Date: 2026-03-11

## Purpose

This document freezes the causal semantics for the laptop-optimized L2 ML pipeline.
The core rule is simple:

- labels are always generated from the highest available path resolution
- compact feature caching must not change the future path used for labeling

## Supported Label Families

### Mid-return labels

Columns:

- `ret_fwd_{h}s`
- `label_{h}s`

Definition:

- `ret_fwd_{h}s = (mid(t + h) - mid(t)) / mid(t)`
- `label_{h}s = 0` when return is below the lower threshold
- `label_{h}s = 1` when return is between thresholds
- `label_{h}s = 2` when return is above the upper threshold

Threshold modes:

- `quantile`: compute thresholds from the symbol-day return distribution
- `fixed`: use `fixed_bps`

Missing-future policy:

- if no future observation exists inside the horizon window, the label is `NaN`

### Barrier / execution labels

Columns:

- `barrier_outcome_{h}s`
- `barrier_label_{h}s`

Barrier outcomes:

- `tp_first`
- `sl_first`
- `neither`
- `simultaneous`

Numeric mapping:

- `2 = tp_first`
- `1 = neither` or `simultaneous`
- `0 = sl_first`

Definition:

- evaluate the full-resolution future mid-price path after the current row
- determine the first point where take-profit or stop-loss barrier is reached
- compare the first TP hit index and first SL hit index

Direction semantics:

- `long`: favorable move is upward, adverse move is downward
- `short`: favorable move is downward, adverse move is upward

Tie-break policy:

- `worst_case`: simultaneous hit resolves to `sl_first`
- `best_case`: simultaneous hit resolves to `tp_first`
- `neutral`: simultaneous hit resolves to `simultaneous`

Missing-future policy:

- if the horizon contains no future row, the label is `NaN`

## Causality Rules

- Do not compute labels from compacted feature rows.
- Do not infer TP/SL order from bucket summaries.
- If features are resampled, attach labels by aligning compact timestamps back to the
  full-resolution label artifact.
- Training may downsample feature rows after labels are computed, but never before.

## Training Default

Current default training target:

- `mid_return`
- horizon selected by CLI `--horizon`

The pipeline also supports `barrier` and `both` at artifact/cache build time for
future execution-style modeling.
