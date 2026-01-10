
# 2025-11-14 – Intraday ML Model & Policy Enhancement Plan (v4)

Target audience: **non-reasoning Codex CLI coder** working on the `quantstack` intraday ML pipeline.

Strategy context (do not change unless explicitly told):
- Universe: Russell 5–50 “Stock-in-Play” (SIP) shortlist, ~30–40 names per day, built by existing SIP tooling.
- Timeframe: intraday, 10-minute decision bars, 1-minute execution bars (already in codebase).
- Holding horizon: 15–240 minutes, **flat by EOD**.
- Style: **few trades per day (3–5 globally)**, *high-probability*, **big-move** trades (moves of ≥ ~1–2 ATR over 60–120 minutes).
- Execution: **signal on bar close → entry at next 1-minute bar open**, with explicit slippage model.
- Models: tree-based (LightGBM) + SIP/feature stack already present. You will enhance labels, policy, and evaluation, not redesign everything from scratch.

Hard constraints:
- **No forward-looking bias or leakage**. All features, labels, and policies MUST use only information observable up to the decision time.
- **No mock / placeholder / synthetic logic** unless explicitly labelled as a temporary test helper and kept completely out of production paths.
- **Do not silently change core backtest semantics.** Any change to execution, risk, or policy must be explicit and gated through config.
- **No full multi-month PhaseA runs as tests.** Use focused smoke tests, short-window test configs, and unit tests.

You must follow the sprint tasks in order. Each task has:
- **Goal**: what the task must accomplish.
- **Files**: suggested files to touch (create or modify). If a file does not exist, create it.
- **Steps**: concrete actions and checks.
- **Tests**: minimal tests you MUST add or run.

Use existing patterns in the repo for config structure, logging, and tests where possible.

---

## Status – 2025-11-14

**Progress & decisions**
- Sprint 0 documentation captured in `docs/extensions/intraday_ml_models/current_policy_spec.md`; it reflects the pre-change Phase A behaviour we observed in the SIP pilot.
- Config + loader refactor complete: `configs/extensions/intraday_ml/policy_config.json` now acts as the single policy source of truth and `run_phaseA_pipeline.py` consumes it through the new loader.
- Policy core updated (`extensions/intraday_ml_policies/intraday_ml_decision_policy.py`) with the EntryCandidate schema, TOD profiles, asymmetric thresholds, ATR-only risk, lifecycle gates, and daily risk budgeting; helper + execution paths updated accordingly (`extensions/intraday_ml/risk_levels.py`, `extensions/intraday_ml/backtest.py`).
- Added policy + risk unit tests under `tests/extensions/intraday_ml/test_policy_limits.py` and `tests/extensions/intraday_ml/test_risk_and_execution.py`.
- Fixed the `process_signals` per-bar accumulation bug (`extensions/intraday_ml_policies/intraday_ml_decision_policy.py`, `tests/extensions/intraday_ml/test_policy_limits.py`) so every timestamp persists its accepted entries before advancing.
- Added explicit regression coverage: `tests/extensions/intraday_ml_policies/test_intraday_ml_decision_policy.py::test_process_signals_accumulates_entries` and `tests/extensions/intraday_ml/test_risk_and_execution.py::test_daily_risk_budget_blocks_after_hits`.
- Sprint 2 lifecycle controls landed: ATR-only stops/targets, early-loss and dead-trade exits, winner-extension limits, risk-budget gating, and next-bar slippage execution now flow through `extensions/intraday_ml_policies/intraday_ml_decision_policy.py`, `extensions/intraday_ml/risk_levels.py`, and `extensions/intraday_ml/backtest.py`.
- Regression safety net expanded with new coverage in `tests/extensions/intraday_ml/test_risk_and_execution.py` (hold-limit extensions, time-stop enforcement, daily risk budget, ATR scaling, execution slippage). Latest proof: `pytest tests/extensions/intraday_ml/test_risk_and_execution.py`.
- Sprint 3 assets delivered: ATR big-move labeler (`extensions/intraday_ml/labeling/big_move_labels.py`), updated config (`configs/extensions/intraday_ml/targets_bigmove.yaml`), and spec (`docs/extensions/intraday_ml_models/big_move_target_spec.md`). Covered by `pytest tests/extensions/intraday_ml/test_big_move_labels.py`.
- Stage 1 & 2 training harness added (`extensions/intraday_ml_models/train_lgbm_bigmove.py`) with integration tests (`tests/extensions/intraday_ml_models/test_train_lgbm_bigmove.py`) to guarantee deterministic model builds before policy wiring.
- Sprint 4 policy wiring finished: `policy_mode` toggle, `BigMovePolicyAdapter`, big-move-aware configs (`configs/extensions/intraday_ml/policy_config*.json`), and the short-window sweep harness (`extensions/intraday_ml/experiments/policy_sweep.py`) are all covered by new adapter/policy/sweep tests.

**Issues / blockers encountered**
- Previously, `process_signals` appended only the final bar’s accepted candidates before returning. This is now resolved; `pytest tests/extensions/intraday_ml/test_policy_limits.py` covers the regression.
- No open blockers; monitoring daily-risk telemetry before starting the Sprint 3 label work.

**Next steps**
- Use the sweep tooling to tune the frontier + hit-rate expectations ahead of any production pilot, and prep Sprint 5 deliverables (policy+exec stress tests) while keeping the Sprint 2/3/4 regression suites green.

---

## Immediate fix – per-bar accumulation inside `process_signals`

### Goal
Ensure every bar’s accepted entry candidates are persisted before advancing the loop so global limits, daily counters, and tests observe the correct trade counts.

### Files
- `extensions/intraday_ml_policies/intraday_ml_decision_policy.py`
- `tests/extensions/intraday_ml/test_policy_limits.py`

### Steps
1. In `process_signals`, keep `entry_candidates` scoped to each grouped timestamp and make sure the block that sorts and consumes those candidates is indented inside the `for _, group in grouped` loop. Today it sits after the loop, so only the final bar’s entries ever reach `orders`.
2. After fixing the indentation, explicitly reset `entries_this_bar` for every timestamp and append orders before continuing to the next group.
3. Double-check that `self.entries_per_day`, `self.global_entries_today`, and `self.last_trade_ts` are updated immediately after each accepted candidate so counters remain monotonic when multiple bars are processed in one call.
4. Add a regression test (or extend `test_global_max_entries_is_enforced`) to construct two timestamps with admissible candidates and assert that both bars contribute to `orders`.
5. Rerun:
   - `pytest tests/extensions/intraday_ml/test_policy_limits.py`
   - `pytest tests/extensions/intraday_ml_policies/test_intraday_ml_decision_policy.py::test_process_signals_accumulates_entries`
   - `pytest tests/extensions/intraday_ml/test_risk_and_execution.py::test_daily_risk_budget_blocks_after_hits`

---

## Sprint 0 – Baseline audit (read-only, no behaviour change)

### Goal
Document the CURRENT live behaviour of the intraday policy, exits, risk limits, and execution assumptions so later changes are deliberate, not accidental.

### Files
- `extensions/intraday_ml/policy/` (exact structure may differ; find the policy module actually used by PhaseA).
- `configs/extensions/intraday_ml/policy_config*.yaml` (or `.json` where present).
- `artefacts/extensions/intraday_ml/phaseA_full_sip/metrics.json`
- `artefacts/extensions/intraday_ml/phaseA_full_sip/trades/*` (trade logs / parquet)
- **New**: `docs/extensions/intraday_ml_models/current_policy_spec.md`

### Steps
1. Locate the **production policy implementation** used by `run_phaseA_pipeline.py`:
   - Start from the config used by `configs/extensions/intraday_ml/phaseA_sip_full.yaml`.
   - Find where model predictions are converted into trade actions (entry/exit decisions).
   - Identify:
     - Where `prob_threshold_*`, `directional_gap`, `conviction`, `min_expected_r` are read and applied.
     - Where `max_entries_per_day`, `cooldown_minutes`, and `max_hold_minutes` are enforced.
     - Where SL/TP distances are computed (stop % vs ATR) and how exit reasons are set.

2. Inspect one recent run’s `metrics.json` and trade logs:
   - Confirm:
     - Average trades per day.
     - Per-symbol trade counts.
     - Average duration in minutes.
     - Typical stop and target distances (% and ATR).
     - Common exit reasons.

3. Write a short **CURRENT POLICY SPEC** document:
   - Create `docs/extensions/intraday_ml_models/current_policy_spec.md`.
   - Describe, in plain language and bullet points:
     - Entry logic: thresholds, gating conditions, how many trades are allowed per day, per symbol, per bar.
     - Exit logic: SL, TP, time-based exits, conviction-based exits.
     - Risk limits: any daily caps or portfolio constraints currently in effect.
     - Execution assumptions: which bar is used for entry/exit prices, any slippage/fees model currently applied.

### Tests
- None beyond `pytest` smoke on relevant policy modules to confirm they still import and run.
- Do NOT change behaviour in this sprint. This is documentation only.

---

## Sprint 1 – Global trade caps, concurrency, TOD thresholds, ranking, and directional asymmetry

### Goal
Implement a **clean, config-driven policy layer** with:
- Global trade caps (by count and risk).
- Portfolio-level concurrency caps.
- Time-of-day (TOD) threshold profiles for entries.
- Cross-sectional ranking at each decision time.
- Separate thresholds for longs vs shorts.

### Files
- `extensions/intraday_ml/policy/*.py` (existing policy implementation – extend, don’t replace blindly).
- `configs/extensions/intraday_ml/policy_config.json` (or `.yaml` – adapt to actual format).
- **New**: `tests/extensions/intraday_ml/test_policy_limits.py`
- **New** (optional helper): `extensions/intraday_ml/policy/tod_utils.py`

### 1.1 – Convert `max_entries_per_day` to GLOBAL semantics

**Steps**
1. In the policy module, find where `max_entries_per_day` is used.
2. Ensure it is interpreted as **global per strategy per day**, not per symbol.
   - Maintain a counter of **total entries for the current trading day**.
   - Increment the counter whenever a new position is opened.
   - Block any new entries once the counter reaches `max_entries_per_day`.

3. Update config schema:
   - In `policy_config.json`, document that `max_entries_per_day` is global.

**Tests**
- Add unit tests in `test_policy_limits.py`:
  - Simulate a sequence of candidate trades across multiple symbols.
  - Verify that once the global count hits the configured cap, no further entries are allowed even if per-symbol constraints are not hit.

### 1.2 – Add portfolio-level concurrency caps

**Steps**
1. Extend config with:
   - `max_open_positions_global`: integer, max concurrent positions across ALL symbols.
   - `max_trades_per_symbol_per_day`: integer, max entries per symbol per day.
   - `max_trades_per_bar_global`: integer, max new entries on any single decision bar (time slice).

2. In the policy evaluation function at decision time:
   - Compute current open positions and map by symbol.
   - Before accepting a new trade:
     - Check `max_open_positions_global` (current open positions + 1 must not exceed the cap).
     - Check `max_trades_per_symbol_per_day` for that symbol.
     - Keep a rolling counter for entries on the current bar; ensure it does not exceed `max_trades_per_bar_global`.

**Tests**
- Extend `test_policy_limits.py`:
  - Scenario: multiple candidate trades fired at the same bar; verify global bar cap is enforced.
  - Scenario: excessive trades for a single symbol; verify per-symbol daily cap blocks additional entries.
  - Scenario: too many concurrent positions; verify new signals are ignored.

### 1.3 – Time-of-day (TOD) aware threshold profiles

**Steps**
1. Add TOD bucket configuration in `policy_config.json`, e.g.:

```jsonc
"tod_profiles": {
  "OPEN": {
    "start_time": "09:40",
    "end_time": "10:10",
    "prob_threshold_long": 0.70,
    "prob_threshold_short": 0.75,
    "min_directional_gap_long": 0.08,
    "min_directional_gap_short": 0.10,
    "min_conviction_long": 0.02,
    "min_conviction_short": 0.03,
    "min_expected_r_long": 1.8,
    "min_expected_r_short": 2.0
  },
  "MID": {
    "start_time": "10:10",
    "end_time": "14:30",
    "prob_threshold_long": 0.65,
    "prob_threshold_short": 0.70,
    "min_directional_gap_long": 0.06,
    "min_directional_gap_short": 0.08,
    "min_conviction_long": 0.015,
    "min_conviction_short": 0.025,
    "min_expected_r_long": 1.6,
    "min_expected_r_short": 1.9
  },
  "LATE": {
    "start_time": "14:30",
    "end_time": "15:50",
    "prob_threshold_long": 0.62,
    "prob_threshold_short": 0.68,
    "min_directional_gap_long": 0.055,
    "min_directional_gap_short": 0.075,
    "min_conviction_long": 0.015,
    "min_conviction_short": 0.025,
    "min_expected_r_long": 1.5,
    "min_expected_r_short": 1.8
  }
}
````

2. Implement TOD selection logic:

   * Given the decision timestamp (bar close time in exchange time), pick the active TOD bucket.
   * Expose a helper like `get_tod_profile(dt)` in a small utility module.

3. Replace hard-coded thresholds in the policy with values pulled from the active TOD profile and direction (long/short).

**Tests**

* New tests in `test_policy_limits.py`:

  * Mock timestamps in each TOD bucket and verify that correct thresholds are loaded.
  * Verify that a signal that passes `MID` thresholds but fails `OPEN` thresholds is accepted in MID and rejected in OPEN.

### 1.4 – Cross-sectional ranking at decision time

**Steps**

1. Define a composite score for each candidate symbol at decision time, using ONLY current-bar model outputs:

   * Inputs: `prob_max`, `directional_gap`, `conviction`, and `expected_R` (if available).
   * Example implementation:

```python
score = prob_max * directional_gap * max(conviction, 0.0) * max(expected_r, 0.0)
```

2. Policy logic at decision time:

   * For all symbols:

     * Evaluate whether they pass TOD + directional thresholds.
     * If they pass and are not blocked by caps/cooldowns, compute `score`.
   * Sort candidates by score descending.
   * Sequentially accept candidates until:

     * `max_trades_per_bar_global` is reached, or
     * `max_open_positions_global` is reached, or
     * Risk budget (see Sprint 2) is exhausted.

3. Ensure that this ranking is used consistently in both CV trading sim and OOS / PhaseA runs.

**Tests**

* Add a small deterministic test:

  * Create 5 candidate signals with fixed `prob_max`, `directional_gap`, `conviction`, `expected_r` values.
  * Configure caps to allow only 2 trades.
  * Verify that only the top-2 highest-score candidates are selected.

### 1.5 – Direction-specific thresholds (long vs short asymmetry)

**Steps**

1. Ensure policy config has **separate** thresholds as shown in the TOD profiles above:

   * `prob_threshold_long` vs `prob_threshold_short`
   * `min_directional_gap_long` vs `min_directional_gap_short`
   * `min_conviction_long` vs `min_conviction_short`
   * `min_expected_r_long` vs `min_expected_r_short`

2. In the policy:

   * For a given candidate direction (long/short), use the appropriate set of thresholds from the active TOD profile.
   * Do NOT apply a single, shared threshold for both directions.

**Tests**

* Unit test:

  * Construct two candidates, one long and one short, with identical raw stats.
  * Configure stricter thresholds for short.
  * Verify that long passes and short fails under the same conditions.

---

## Sprint 2 – Exit logic, ATR-based stops/targets, daily risk budget, and next-bar execution

### Goal

Align exits and risk with “few trades / big move / ATR-scaled” logic, and enforce a **daily risk budget**. Implement standardised next-bar execution with slippage.

### Files

* `extensions/intraday_ml/policy/risk.py` (or equivalent – locate actual risk/SL/TP code).
* `configs/extensions/intraday_ml/policy_config.json`
* `extensions/intraday_ml/execution/*.py` (execution adapter; create if missing).
* `tests/extensions/intraday_ml/test_risk_and_execution.py`

### 2.1 – ATR-based stop and target distances

**Implementation (2025-11-14)**
- `extensions/intraday_ml/risk_levels.py` now computes stop/target distances strictly from ATR via `stop_atr_multiple` and `tp_r_multiple`, applying only the configured `min_stop_pct`/`max_stop_pct` clamps.
- `IntradayMLDecisionPolicy` feeds the helper through `_risk_helper_config`, storing the `stop_pct`, `take_profit_pct`, ATR multiples, and metadata on every `EntryCandidate` so trade logs and analytics retain the ATR distances.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml/test_risk_and_execution.py::test_atr_based_stop_and_target_scaling`

### 2.2 – Price-path-based early exit for losers and dead trades

**Implementation (2025-11-14)**
- Lifecycle configuration now includes `early_loss_cut_r`, `early_loss_cut_minutes`, `dead_trade_exit_minutes`, and `dead_trade_pnl_band_r` (see `configs/extensions/intraday_ml/policy_config.json`), and `IntradayMLDecisionPolicy` wires those knobs into `_evaluate_position_exit`.
- The policy computes unrealised PnL in R from ATR stops and emits explicit `early_loss_cut` / `dead_trade_exit` orders so logs and run metrics capture why a trade exited early across CV + OOS flows.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml/test_risk_and_execution.py::test_early_loss_cut_exit_triggers`
- `pytest tests/extensions/intraday_ml/test_risk_and_execution.py::test_dead_trade_exit_fires_with_flat_pnl`

### 2.3 – “Let winners run” adjustment and max hold

**Implementation (2025-11-14)**
- Added `max_hold_minutes_flat_or_loser`, `max_hold_minutes_in_the_money`, `trail_activation_r`, and `trail_stop_r` to the lifecycle config; `process_signals` adjusts the per-trade hold limit dynamically based on current `pnl_r` so ≥1R winners inherit the extended window while losers are clamped to the flat limit.
- `_evaluate_position_exit` now prioritises trailing stops, conviction shrinkage, and time stops with explicit reason codes (`holding_long/short` rejections keep appearing while positions run); the force-flat-by-EOD guard remains unchanged.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml/test_risk_and_execution.py::test_profitable_trade_is_allowed_to_run_past_flat_hold_limit`
- `pytest tests/extensions/intraday_ml/test_risk_and_execution.py::test_time_stop_triggers_for_losing_trade_at_flat_hold_limit`

### 2.4 – Daily risk budget (max daily loss in R)

**Implementation (2025-11-14)**
- `max_daily_loss_R` and `trade_risk_R` sit in `policy_config.json`; `IntradayMLDecisionPolicy` tracks `daily_realized_r`, subtracts the per-trade risk prior to each entry, and logs `risk_budget_exhausted` when the projected drawdown breaches the limit.
- Day rollover resets counters, so risk budget and `entries_per_day` stay scoped to a UTC trading date while rejections + metrics report the hits.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml/test_risk_and_execution.py::test_daily_risk_budget_blocks_new_entries`
- `pytest tests/extensions/intraday_ml/test_risk_and_execution.py::test_daily_risk_budget_blocks_after_hits`

### 2.5 – Next-bar execution and slippage

**Implementation (2025-11-14)**
- `extensions/intraday_ml/backtest.py::_shift_to_next_bar` shifts every policy order to the next 1-minute open, copies signal timestamps, and applies the configurable `slippage_bps` when computing `fill_price`/`execution_price`.
- The intraday constraints wrapper inserts these fill prices into `policy_orders`, ensuring downstream analytics and logs see next-bar execution assumptions consistently.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml/test_risk_and_execution.py::test_shift_to_next_bar_applies_slippage`

---

## Sprint 3 – ATR-based big-move labels and two-stage target design

### Goal

Introduce **ATR-based “big move” labels** and implement a two-stage target structure:

1. Big-move probability (is a big move likely?).
2. Direction / expected R conditional on big move.

Do NOT remove the existing multi-class target yet; keep it as a baseline until the new targets are proven.

### Files

* `extensions/intraday_ml/labeling/big_move_labels.py` (new).
* `configs/extensions/intraday_ml/targets_bigmove.yaml` (new label config).
* `extensions/intraday_ml_models/train_lgbm_bigmove.py` (or extend existing training script carefully).
* `tests/extensions/intraday_ml/test_big_move_labels.py`
* `docs/extensions/intraday_ml_models/big_move_target_spec.md`

### 3.1 – Define ATR-based big-move labels

**Implementation (2025-11-14)**
- Added `extensions/intraday_ml/labeling/big_move_labels.py` with `BigMoveLabelConfig` + `compute_big_move_labels` to emit:
  - `y_bigmove` (binary), `y_bigmove_direction` (ternary), and `fwd_return_bigmove`.
  - ATR thresholds follow `abs(ret_fwd) >= max(atr_multiple * atr, floor_pct)`.
- Extended `configs/extensions/intraday_ml/targets_bigmove.yaml` with a `big_move` block holding the label spec plus winsorization bounds for later stages.
- Authored the spec in `docs/extensions/intraday_ml_models/big_move_target_spec.md`.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml/test_big_move_labels.py`
- Legacy label suite still passes: `pytest tests/extensions/intraday_ml/test_compute_label_for_timestamp.py`

### 3.2 – Train Stage 1: big-move probability model

**Implementation (2025-11-14)**
- Built `extensions/intraday_ml_models/train_lgbm_bigmove.py` with `BigMoveModelTrainer` covering Stage 1 binary classification (LightGBM, stratified split, accuracy/precision/recall/F1/logloss/ROC‑AUC reporting).
- Trainer aligns feature frames with labels, fills NaNs deterministically, and exposes `train_stage1_probability` plus a `train_all_stages` convenience wrapper for later automation.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml_models/test_train_lgbm_bigmove.py::test_trainer_runs_all_stages_and_reports_metrics`

### 3.3 – Train Stage 2: direction / expected-R conditional on big moves

**Implementation (2025-11-14)**
- `train_lgbm_bigmove.BigMoveModelTrainer` now:
  - Filters conditioned samples (`y_bigmove == 1`) for Stage 2 direction, maps `-1/+1` to `0/1`, and trains a classifier with the same metric suite as Stage 1.
  - Builds the expected-R regression with LightGBM, after winsorising `realized_r_bigmove` using config-provided floors/caps; reports MAE/RMSE/R².
- All stages share deterministic splits + feature handling, and `train_all_stages` returns a dict of `StageTrainingResult` objects for downstream persistence.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml_models/test_train_lgbm_bigmove.py`
- Documentation anchored in `docs/extensions/intraday_ml_models/big_move_target_spec.md`.

---

## Sprint 4 – Policy integration of big-move models and policy frontier

### Goal

Wire the new big-move / expected-R models into the policy and support systematic policy sweeps (frontier search) without long full runs.

### Files

* `extensions/intraday_ml/policy/bigmove_policy_adapter.py` (new).
* `configs/extensions/intraday_ml/policy_config_bigmove.json` (new).
* `extensions/intraday_ml/experiments/policy_sweep.py` (new).
* `tests/extensions/intraday_ml/test_bigmove_policy_adapter.py`

### 4.1 – Big-move gating in policy

**Implementation (2025-11-14)**
- Added `BigMovePolicyAdapter` (`extensions/intraday_ml/policy/bigmove_policy_adapter.py`) which converts Stage 1/2 outputs (`prob_bigmove`, `prob_bigmove_long/short`, `expected_r_bigmove`) into the unconditional `prob_long/short/neutral`, an `_bigmove_allowed` gate, and `_bigmove_expected_r`.
- `IntradayMLDecisionPolicy` now honours a `policy_mode` toggle plus `bigmove_policy` config: the adapter runs inside `_prepare_signals`, entry evaluation enforces the `prob_bigmove` threshold (`bigmove_prob_below_threshold` / `bigmove_signal_missing` rejections), and Stage 2 expected-R overrides feed into the existing ATR risk metadata.
- Configs: baseline config gained explicit `policy_mode` + `bigmove_policy` defaults, and `policy_config_bigmove.json` codifies the production-ready big-move profile for quick switches.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml/test_bigmove_policy_adapter.py`
- `pytest tests/extensions/intraday_ml/test_policy_limits.py::test_bigmove_policy_blocks_low_probability_signals`
- `pytest tests/extensions/intraday_ml/test_policy_limits.py::test_bigmove_policy_accepts_high_probability_signals`
- Existing policy suites still green (`pytest tests/extensions/intraday_ml_policies/test_intraday_ml_decision_policy.py`)

### 4.2 – Policy sweep / frontier search (short-window)

**Implementation (2025-11-14)**
- Restructured the experiments module into a package and added `extensions/intraday_ml/experiments/policy_sweep.py` with helpers to load signals/bars, expand dot-notation grids, run a lightweight `IntradayMLDecisionPolicy → intraday_ml_run_backtest` loop, and emit a sweep DataFrame / CSV.
- `sweep_policy_configs` records `entries`, `rejections`, trades/day, average R multiple, hit rate, and prefixes engine metrics (`metric_total_return`, etc.) so the frontier can be filtered with a single pandas query.

**Tests (2025-11-14)**
- `pytest tests/extensions/intraday_ml/test_policy_sweep.py`
- Manual smoke: `python -m extensions.intraday_ml.experiments.policy_sweep --signals artefacts/.../oos_predictions.parquet --bars artefacts/.../bars_10m.parquet --policy-config configs/extensions/intraday_ml/policy_config_bigmove.json --grid path/to/grid.yaml --output artefacts/extensions/intraday_ml/policy_sweeps/example.csv`

---

## General testing and guardrails

1. **Never run the full multi-month PhaseA pipeline as part of unit tests.**

   * For integration tests, create dedicated **short-window configs** (a few days, few symbols) under `configs/extensions/intraday_ml/smoke/`.

2. **No forward-looking bias:**

   * Ensure all label and feature builders only look at data up to the decision time `t`.
   * In code that computes `ret_fwd`, always use explicit offsets and document them.

3. **No mock/placeholder production logic:**

   * If you need dummy data for unit tests, keep it strictly inside tests and do not leak any “fake logic” into production modules.

4. **Logging and metrics:**

   * For each major new behaviour (risk budget hit, early loss cut, big-move gate), add explicit log fields and structured metrics so behaviour can be analysed later.
