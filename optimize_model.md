
You are operating inside my intraday equity ML trading repository.

## High-level objective

I have a 3-class intraday ML setup for equities (labels: -1, 0, +1), with:
- Strong label imbalance: most bars are class 0 (“no trade / no big move”).
- Bar interval: 10-minute bars.
- **Trading objective**: I want **3–5 high-conviction trades per day across the universe**, only when the model is highly confident of a **big move and its direction**.

Your job is to:
1. Analyze the current ML setup (labels, model, CV, and calibration).
2. Identify and implement changes that make the system explicitly optimized for **profitability and risk-adjusted returns** (PnL, Sharpe, Sortino, drawdown), not classification metrics.
3. Design a sprint plan to implement and iterate on this, with **trading performance** as the sole intended outcome.

Logloss / accuracy / F1 can be used as diagnostics, but all **final decisions and tuning** must be guided by **trading PnL and risk-adjusted metrics** on properly out-of-sample data.

---

## Hard constraints (non-negotiable)

1. **No mock/synthetic/dummy data**, except for trivial unit tests of small pure functions.
   - All model analysis, backtesting, and performance evaluation must use the **real existing historical data** and the existing pipeline.
   - Do not fabricate fake price series or labels for “demo” purposes.

2. **No look-forward bias or data leakage.**
   - All targets must be constructed using only information *after* the decision time, consistent with the existing target logic.
   - All model training, hyperparameter tuning, and trade policy tuning must respect *time ordering*:
     - Train only on past data.
     - Validate/tune on a strictly later period.
     - Keep OOS strictly held out for final evaluation only.
   - No shuffling across time that breaks temporal order.
   - Cross-validation must be time-based with appropriate purge/embargo, no leaking future information into the past.

3. **Respect the existing project structure.**
   - Reuse existing modules, configuration patterns, artefact directories and backtesting components (if they exist).
   - Do not reorganize the repo or introduce heavy dependencies unless absolutely necessary.

---

## Known config and artefact locations

The current intraday ML configuration is:

- Master config:
  - `configs/extensions/intraday_ml/phaseA_multi_ticker.yaml`

- Component configs:
  - Universe: `configs/extensions/intraday_ml/universe_phaseA_multi.yaml`
  - Splits:  `configs/extensions/intraday_ml/splits_2024_multi.yaml`
  - Cuts:    `configs/extensions/intraday_ml/cuts_10m.yaml`
  - Features:`configs/extensions/intraday_ml/features_10m.yaml`
  - Targets: `configs/extensions/intraday_ml/targets_loose.yaml`
  - Model:   `configs/extensions/intraday_ml/model_lgbm.yaml`
  - CV:      `configs/extensions/intraday_ml/cv/phaseA.yaml`

- Artefacts for this run:
  - Manifest:             `artefacts/extensions/intraday_ml/phaseA_multi/manifest.json`
  - Training data:        `artefacts/extensions/intraday_ml/phaseA_multi/training_data.parquet`
  - Policy calibration:   `artefacts/extensions/intraday_ml/phaseA_multi/policy_calibration.json`
  - Trained model object: `artefacts/extensions/intraday_ml/phaseA_multi/model_lgbm` (LightGBM)

- Time splits from logs (must be confirmed from config):
  - train: 2024-06-01 to 2024-08-31
  - test:  2024-09-01 to 2024-09-30
  - oos:   2024-10-01 to 2024-10-31

Use these as hints, but always confirm via configs / data rather than trusting text snippets.

---

## Step 1: Repository and pipeline discovery

1. From the repo root, locate the intraday ML implementation that:
   - Loads the configs above.
   - Builds the dataset (features + labels).
   - Trains the LightGBM model.
   - Runs cross-validation.
   - Produces the policy calibration file and any existing evaluation artefacts.

2. Identify and document (in your output) the Python modules that implement:
   - Dataset manifest creation.
   - 10-minute feature engineering.
   - Target construction for the 3-class labels.
   - Model training for multi-class LightGBM.
   - Cross-validation logic.
   - Any existing evaluation / calibration logic.

3. Confirm that:
   - Splits in `splits_2024_multi.yaml` match the intended train/test/oos ranges.
   - Universe in `universe_phaseA_multi.yaml` matches the manifest and actual data.
   - `targets_loose.yaml` clearly defines:
     - Label names and mapping to {-1, 0, +1}.
     - Return horizons and thresholds.
     - Any volatility or normalization rules.

Produce a concise summary in your output (1–2 paragraphs + a short bulleted list of key files) describing the current ML & trading setup.

---

## Step 2: Diagnostic analysis (with trading metrics in mind)

Use **real data only**. This step is about understanding the current system, not yet changing it.

### 2.1. Label distribution and structure

- Load `training_data.parquet` (or the equivalent prepared dataset).
- Identify the target column(s) based on `targets_loose.yaml`.
- Compute and report, for **train**, **test**, and if possible **oos**:
  - Label counts and percentages for -1, 0, +1.
  - Per-symbol label distributions (e.g., GIS vs TTD vs BALL).
- Comment on:
  - How sparse the ±1 labels are.
  - Whether certain symbols or periods dominate ±1 events.

### 2.2. Baseline vs model logloss (diagnostic only)

Logloss is **diagnostic**, not an optimization target.

- For the existing model:
  - Reproduce or approximate:
    - Validation / CV logloss for the current LightGBM run.
- For a simple class-frequency baseline:
  - Predict constant probabilities equal to empirical label frequencies on the training data.
  - Compute its multi-class logloss on the validation sets.

Report these in a small table (baseline vs model, by fold or split), but keep in mind:
> These numbers are not the final success metric; they simply show that the model is not completely random.

### 2.3. Per-class predictive skill

On **test** and, if available, **oos**:

- Compute, for the model:
  - Confusion matrix for {-1, 0, +1}.
  - Per-class:
    - Precision
    - Recall
    - F1
  - Both globally and per-symbol.

Again, treat this as **diagnostic**, not as the ultimate objective.

---

## Step 3: Tail-focused trading evaluation (PnL, Sharpe, Sortino, drawdown)

From this point onward, PnL and risk-adjusted metrics are the primary concern.

### 3.1. Construct trade signals from model probabilities

For each bar in **test** and **oos**:

- Get predicted probabilities:
  - `p_up   = P(label = +1)`
  - `p_down = P(label = -1)`
  - `p_flat = P(label = 0)`
- Define:
  - `trade_prob     = max(p_up, p_down)`
  - `trade_direction = +1 if p_up >= p_down else -1`
  - `edge_margin    = trade_prob - p_flat` (or another monotonic measure of “confidence vs flat”)
  - A candidate trade score, e.g.:
    - `trade_score = trade_prob * edge_margin`
- These scores will be used to select **3–5 trades per day** across the universe.

### 3.2. Map trade signals to realized returns (no leakage)

Using the existing target horizon definition and real historical prices:

- For each potential trade signal:
  - Compute the **realized return** over the same horizon used for label construction.
  - If there is a canonical transaction-cost or slippage model in the project, reuse it; otherwise:
    - Implement a minimal cost model consistent with project conventions (e.g., a fixed bps per trade).
- Ensure:
  - All returns used are in the **future** relative to the decision bar and consistent with the target definition.
  - No future-day information is used to choose or size the trade.

### 3.3. Define and evaluate trade selection policies

Define a small set of **trade selection policies** such as:

1. **Top-K per day policy:**
   - For each trading day across the universe:
     - Rank all bars by `trade_score` (or `trade_prob`).
     - Select top K trades per day for K in {3, 4, 5}.
   - Execute these trades with fixed position size (consistent with current backtest conventions).

2. **Threshold-based policy:**
   - For thresholds θ in a grid (e.g., 0.6, 0.7, 0.8):
     - Trade whenever `trade_prob >= θ` and `trade_prob >= 2 * max(other_class_probs)` (to avoid indecisive cases).
   - If needed, cap at a maximum number of trades per day (e.g., 5).

For each policy, on **test** and **oos** separately, compute:

- **Per-trade metrics:**
  - Number of trades.
  - Hit rate (directional accuracy).
  - Mean and median return per trade.
  - Distribution summary (quartiles).

- **Time-series metrics:**
  - Daily PnL series (based on trade PnL aggregated by day).
  - Total PnL over the evaluation horizon.
  - Annualized Sharpe ratio (using daily returns, 252 days/year convention).
  - Sortino ratio (using downside deviation).
  - Max drawdown.
  - Calmar or similar drawdown-related ratio (if helpful).

These metrics are the **primary** evaluation criteria from this step on.

### 3.4. Interpretation

In your output, provide a section that answers explicitly:

- For which policies (top-K, thresholds) do we see:
  - Sharpe and Sortino meaningfully above 1 on test / oos?
  - Acceptable max drawdown relative to PnL?
- Is there **stable, positive expectancy** in the **top 3–5 trades per day**?
- Are results materially weaker / unstable on oos vs test (overfitting risk)?

---

## Step 4: Propose and implement model / label / CV changes, driven by PnL

Now propose **concrete changes** to the system, but always use **PnL, Sharpe, Sortino, and drawdown** for decisions. Logloss and classification scores are secondary diagnostics only.

### 4.1. Label design for truly “big moves”

- Inspect `targets_loose.yaml` to see the existing thresholds.
- If the current ±1 labels capture too many moderate moves:
  - Propose a new target config (e.g., `targets_bigmove.yaml`) where:
    - Thresholds are adjusted so that ±1 represent genuinely large moves that are worth trading.
    - There are still enough ±1 samples to train a usable model.
- The goal:
  - Labels -1/+1 correspond to moves that would be **profitable net of costs**, when sized reasonably.

Do **not** overwrite `targets_loose.yaml`; add a new config and wire it into a parallel experiment.

### 4.2. Model and class weighting adjustments

- Given the heavy class-0 dominance and the focus on ±1:
  - Add or tune `class_weight` (or equivalent) in `model_lgbm.yaml` to upweight ±1 classes.
  - Optionally, consider other LightGBM parameters that help separate tails (e.g. higher regularization with stronger emphasis on robust patterns).
- Re-train the model using the new target config and adjusted class weights.
- Re-run the **trading evaluation** from Step 3 (test-only first, then oos) to see impact on:
  - PnL
  - Sharpe
  - Sortino
  - Max drawdown

The decision whether the change is “good” should be based on these **trading metrics**, not on logloss.

### 4.3. Cross-validation & tuning without leakage

- Inspect `configs/extensions/intraday_ml/cv/phaseA.yaml` and its implementation.
- Ensure CV is:
  - Time-based.
  - Purged / embargoed.
  - Uses strictly past data for training and later data for validation.
- Fix any anomalies (e.g. “fold 3/2” logging, incorrect fold boundaries).
- Use CV and a **tuning loop** where:
  - You explore a small grid of:
    - Model hyperparameters (e.g. learning rate, num_leaves, regularization)
    - Class weights
    - Trade policy parameters (thresholds, top-K per day cap).
  - For each candidate, you compute **validation trading metrics** (PnL/Sharpe/Sortino/Drawdown) in a **validation period only** (no OOS involvement).
- Select model + policy parameters that maximize **risk-adjusted trading performance** (e.g. Sharpe / Sortino) with acceptable max drawdown, not those that minimize logloss.

The OOS period remains untouched until the final evaluation.

### 4.4. Dedicated evaluation module for PnL metrics

Implement or extend a dedicated evaluation script, e.g.:

- `extensions/intraday_ml/eval/eval_trading_performance.py`

This should:

- Load model predictions and realized returns for test and oos.
- Implement the trade selection policies (top-K and threshold-based).
- Compute and output:
  - Per-trade stats.
  - Daily PnL.
  - Sharpe, Sortino, max drawdown.
- Optionally write these metrics to JSON / CSV artefacts for later analysis.

This module is now the **primary performance assessment tool**.

---

## Step 5: Sprint plan (PnL-first)

Create a sprint plan for ~1–2 weeks of work, assuming a single developer. The plan must explicitly center **PnL and risk-adjusted returns** as the goal.

Example structure (you can refine it based on repo realities):

### Sprint 1: Understand & instrument trading performance

- **Task 1.1:** Confirm label distributions and target definitions from `targets_loose.yaml`.
- **Task 1.2:** Implement or refine prediction loading to derive `trade_prob`, `trade_direction`, and `trade_score`.
- **Task 1.3:** Implement `eval_trading_performance.py` to compute:
  - Per-trade metrics
  - Daily PnL
  - Sharpe, Sortino, max drawdown
  for test and oos periods under several trade policies.

### Sprint 2: Redefine labels and model for big-move profitability

- **Task 2.1:** Design `targets_bigmove.yaml` to better capture high-value trades.
- **Task 2.2:** Adjust `model_lgbm.yaml` with appropriate class weights and any other relevant hyperparameters.
- **Task 2.3:** Retrain the model and re-run trading evaluation on test and oos.
- **Task 2.4:** Compare:
  - Old vs new labels / model in terms of PnL/Sharpe/Sortino/Drawdown, not logloss.

### Sprint 3: Robustness and tuning under PnL metrics

- **Task 3.1:** Fix / verify CV configuration with time-based, purged folds.
- **Task 3.2:** Implement a small hyperparameter + policy grid search that:
  - Uses **validation trading metrics** (PnL, Sharpe, Sortino) as the optimization objective.
- **Task 3.3:** Lock in a final model + policy.
- **Task 3.4:** Run final evaluation on **untouched oos** and produce a concise report summarizing:
  - Trade frequency
  - PnL
  - Sharpe, Sortino
  - Max drawdown

Emit the sprint plan in Markdown format in your final output.

---

## Step 6: Output expectations

In your final output, provide:

1. A short textual summary (1–3 paragraphs) of:
   - The current system.
   - Key weaknesses relative to the goal of “3–5 high-conviction trades per day.”

2. A **diagnostics section** with:
   - Label distributions (by split, by symbol).
   - Baseline vs model logloss (diagnostic only).
   - Per-class metrics.

3. A **trading performance section** with:
   - Trade selection policies evaluated.
   - PnL, Sharpe, Sortino, and max drawdown for test and oos.
   - Discussion of where the model is and is not profitable.

4. A **proposed changes section** summarizing:
   - New label config(s).
   - Model and class-weight changes.
   - CV and tuning changes.
   - Any new evaluation tools.

5. The **sprint plan** as described above.

Throughout all steps:
- Never introduce synthetic data (beyond trivial unit-test stubs).
- Never introduce look-ahead bias or data leakage.
- Use PnL and risk-adjusted trading metrics as the **primary optimization criteria**, with logloss and other ML metrics serving only as secondary diagnostics.
