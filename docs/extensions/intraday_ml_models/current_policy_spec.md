# Current Phase A Policy Specification

Documented below is the live policy behaviour captured for the May 2024 `phaseA_full_sip` run (artifacts stored under `artefacts/extensions/intraday_ml/phaseA_full_sip`). All thresholds below originate from the saved `policy_config.json` and the `IntradayMLDecisionPolicy` implementation (`extensions/intraday_ml_policies/intraday_ml_decision_policy.py`).

## Entry logic
- **Config anchors**: `prob_threshold_long` / `prob_threshold_short` = 0.62, `score_margin` = 0.06, `min_directional_gap` = 0.055, `min_conviction_score` = 0.015, `prob_neutral` is ignored as long as one directional probability dominates.
- **Time window**: entries only inside [09:40, 15:50] ET; a hard `force_flat_time` at 15:59:59 ET triggers forced exits and disallows new entries thereafter.
- **Cooldown**: after any trade (entry or exit) the same symbol is blocked for 18 minutes; the cooldown is enforced before any new entry, even if the symbol has been flat.
- **Max entries per day**: counter keyed by `(symbol, day)` enforces a hard cap of 3 entries for each symbol per trading day; there is no global counter or cross-symbol cap today.
- **Probability / directional gating**: a signal must pass the direction-specific threshold (`prob_long` or `prob_short` ≥ 0.62) _and_ beat the opposite direction by at least 0.06; the directional gap (`|prob_long - prob_short|`) must exceed 0.055 and conviction must exceed 0.015 (with dynamic decay if a trade is already open).
- **Risk gate**: once a candidate side passes the probability gate, the ATR/resistance-based risk helper (`extensions/intraday_ml/risk_levels.py`) calculates stop/target and `expected_r`; trades with `expected_r < 1.5`, non-finite values, or missing support/resistance (when not allowed) are rejected.
- **Strategy checks**: enabled strategies (e.g., momentum) can enforce additional feature-level constraints before an order is created.
- **Ranking**: signals are processed in chronological order (sorted by timestamp) and accepted sequentially. There is no explicit cross-sectional ranking; the first candidate that satisfies the gates is executed (subject to the per-symbol cooldown / entry limit).

## Exit logic
- **Conviction decay**: once held for `max(gap_exit_delay_minutes=18, conviction_decay_min_hold_minutes=18)`, a trade whose current directional gap or conviction falls below decayed thresholds (derived from the entry statistics) is flipped immediately with `reason = "conviction_decay"`.
- **Exit probability thresholds**: longs exit once `prob_short ≥ exit_threshold_short` (default 0.62) or after `max_hold_minutes = 60`; shorts exit symmetrically with `prob_long ≥ 0.62`. Exits triggered by these clauses are marked as `flatten_long` / `flatten_short`.
- **Forced flat**: any remaining positions are force-closed at 15:59:59 ET (the last bar of the day) regardless of their state, with `reason = "force_flat"`.

## Risk limits & constraints
- **ATR-based stops/targets**: the `risk` block uses `atr_feature = f__vol__atr_6`, a maximum ATR multiple of 1.25, and buffers (e.g., `support_buffer_atr = 0.15`) to set stop distances; the `target_r_multiple = 1.6` defines the take-profit distance, but the stop distance is clamped between `min_stop_pct = 0.002` (0.2%) and `max_stop_pct = 0.045` (4.5%) to avoid extremes.
- **Expected-R floor**: each candidate must project at least `min_expected_r = 1.5` before it becomes an order; this floor is enforced after the ATR/STP/TP calculations and is also calibrated during rollout.
- **Calibration**: `SymbolThresholdCalibrator` uses percentile-based floors/ceilings (`prob_long` & `prob_short` percentiles at 0.85, gap 0.7, conviction 0.8, expected R 0.4) plus hard floors (`min_directional_gap = 0.04`, `score_margin = 0.04`, `min_expected_r = 1.5`) and ceilings (`min_expected_r ≤ 4.0`) to keep per-symbol thresholds within an acceptable band.
- **Single position per symbol**: the policy tracks at most one open trade per symbol via `position_state`; new entries for that symbol are rejected until the prior trade flatly exits.
- **Target trades reporting**: `target_trades_min = 3` and `target_trades_max = 5` are recorded for reporting (`write_trade_report`) but are not actively enforced by the gate.

## Execution assumptions
- **Signal-to-fill mapping**: decisions are made on 10-minute (or whatever `bars` feed) bar closings and are executed at the next available 1-minute open via `_shift_to_next_bar` in `extensions/intraday_ml/backtest.py`. If the next bar is missing, the order is dropped silently (no fallback). The signal timestamp is retained (`signal_ts`) for traceability while `ts` is replaced with the execution timestamp.
- **Slippage & costs**: `DefaultFiller` applies 5 basis points of slippage, $0.0035 commission per share, and a $0.35 minimum commission. Partial fills are possible (`partial_fill_probability = 0.3`). Fill probabilities are 95% with a maximum partial fill ratio of 0.5.
- **Intraday constraints**: `next_bar_execution = True`, `flat_eod_time = 15:59:59`, `no_overnight_positions = True`, and `eod_buffer_minutes = 5` ensure every position is flat before the NYSE close, matching the `force_flat_time` guard in the policy.

## Observed behaviour (May 2024 run / `phaseA_full_sip` artifacts)
- **Trade volume**: `metrics.json` reports 146 trades with a 52.7% win rate, but the raw `trade_summary.parquet` shows 343 completed round-trip entries across 22 trading days (~15.6 trades/day) because the summary logs every unique entry/exit pair even when multiple fills occur per order.
- **Symbol concentration**: the top five symbols were `AES`, `PLTR`, `USB`, `CZR`, and `RF`, each appearing ~19–21 times (per-day counts were most active on these names).
- **Duration**: the average trade lasted ~23.8 minutes (per `duration_minutes` in `trade_summary`).
- **Stopped / target distances**: `orders.parquet` shows average `stop_loss_pct ≈ 0.36%`, `take_profit_pct ≈ 0.57%`, and `expected_r = 1.6` (matching the `target_r_multiple`). Stops are bound by the percent floors/ceilings noted above, but the dynamic ATR calculation (with `max_atr_multiple = 1.25`) is the dominant driver.
- **Exit reasons**: the bulk of exits were `conviction_decay` (226 samples), followed by `flatten_short` (104) and `flatten_long` (13), reflecting the long cooldown/time exit logic and the heavy short bias in the model.
- **Directional bias**: trades were overwhelmingly short (303 shorts vs. 40 longs in `trade_summary`), suggesting the model favored downside moves in this rollout.
- **Performance snapshot**: from `metrics.json` the run had `annualized_return ≈ -0.01%`, `max_drawdown ≈ -0.067%`, and `avg_R ≈ -0.93`, signalling that the calibration thresholds let through marginal trades during this window.

By capturing these inputs, thresholds, and observed statistics we build a clear “before” picture to compare against the forthcoming policy enhancements.
