Findings

  1. The non-trading is real at the signal layer, not an execution/reporting artifact.
     The clean OOS run on ml_report_2026-03-06_to_2026-03-11.json shows:

  - signals_generated = 0
  - entries_executed = 0
  - exits_executed = 0
  - num_trades = 0

  2. Those dates are the true held-out test set for the current model.
     training_metrics.json lists test dates:

  - 2026-03-06
  - 2026-03-07
  - 2026-03-09
  - 2026-03-10
  - 2026-03-11

  3. The March 6 raw-L2 start lag is real, but it is secondary.
     For CCL, NCLH, and SMR on 2026-03-06, the first raw L2 snapshot is about 09:48:24 ET, while Polygon bars begin at 09:30:00 ET. So pre-09:48 bars are not ML-eligible.
     That reduces opportunity, but it does not explain the full failure because the later 2026-03-09 to 2026-03-11 window also finished with zero signals.
  4. The current production path is now trustworthy enough to interpret.
     The run now uses fresh contiguous windows in run_hypothesis_test.py, explicit ML readiness in engine.py, and direct threshold logic in ml_signal.py. The old silent-
     path bugs are no longer the primary explanation.

  Core Issue

  The core issue is activation failure caused by distribution/calibration mismatch, not plumbing.

  More concretely:

  - The model was selected on compact-cache classification performance and earlier overlap-window strategy behavior.
  - The clean OOS backtest evaluates full minute-bar production flow on the held-out March dates.
  - On that true OOS distribution, the model does not emit directional probabilities that cross the live entry thresholds, so signals_generated stays at zero.

  This is the strongest read from the evidence:

  - if execution were the problem, signals_generated would be non-zero
  - if only March 6 raw coverage were the problem, March 9-11 should still activate
  - if the old engine bug were still dominant, the patched windowed run would not be a clean zero-signal result

  So the non-trading problem is upstream of trade management:

  - not TP/SL
  - not cooldown
  - not max positions
  - not report generation

  It is the model/threshold combination on the actual OOS regime.

  Why This Happened

  Most likely contributors:

  - The training source and the live scoring domain are not aligned closely enough.
  - The current threshold (0.45) was not calibrated on the true March held-out probability surface.
  - The model’s held-out label accuracy (0.410) in training_report.md was never strong enough, by itself, to assume robust live activation.
  - March OOS names/dates appear to be a lower-confidence regime than the January overlap windows used earlier for policy tuning.

  The last two points are inference from the artifacts and run behavior.

  Fix Plan

  1. Do a held-out score audit before changing thresholds blindly.
     Target dates: exactly 2026-03-06, 2026-03-07, 2026-03-09, 2026-03-10, 2026-03-11.
     Measure, conditional on _ml_features_ready:

  - count of eligible bars
  - p_up, p_down, max(p_up, p_down) percentiles
  - fraction above 0.35, 0.40, 0.45, 0.50
  - by date and symbol

  2. Recalibrate probabilities on validation dates only.
     Do not retune on the test dates.
     Use validation dates from training_metrics.json:

  - 2026-02-19 to 2026-03-05
    Goal:
  - map raw model scores to calibrated probabilities
  - choose threshold from validation precision/activation tradeoff, not January overlap behavior

  3. Align training rows to execution-time reality.
     The next model iteration should be trained on rows that match live scoring conditions more closely:

  - only bars/snapshots that would be _ml_features_ready
  - same normalization path as backtest/live
  - reduce mismatch between compact-cache classification rows and bar-by-bar production inference

  4. Re-run model selection only after that alignment.
     Priority order:

  - recalibrated 60s model first
  - if still silent, then revisit horizon/label design
  - only then reconsider policy surface

  5. Do not spend cycles on exits or ticker filtering now.
     The strategy is failing before entry generation.
     So:

  - no TP/SL matrix
  - no time-limit search
  - no per-ticker exclusions

  Bottom Line

  The system is no longer blocked by a hidden backtest bug. The core issue is that the current model does not produce tradable directional confidence on the true March
  held-out OOS distribution. The next fix is model/score calibration and train-live alignment, not more execution tuning.
