Here’s what you asked for.

---

## 1. Sprint plan (Markdown content)

This is the exact content of `20251113_model_enhancement3.md` that I just created:

````markdown
# Intraday ML – Model Enhancement Sprint 3  
_Date: 2025-11-13_  
_File: `20251113_model_enhancement3.md`  
_Target repo: `wienbej01/quantstack` (local clone on dev machine)

---

## 0. Context & goals

This sprint upgrades the **intraday ML Phase A big-move classifier** used by:

```bash
python run_phaseA_pipeline.py --config configs/extensions/intraday_ml/phaseA_sip_full.yaml
````

The trading design intent:

* Train and deploy on **SIP-filtered** tickers, ultimately in the **USD 5–50** price band.
* Generate **3–5 high-probability, high-R trades per NY session** across all tickers.
* Use **ATR-based risk** with **1.5R+ RR** at entry and trade durations in the **15–240 minute** range.
* Maintain **roughly symmetric long/short** exposure over time.
* Work with **OHLCV-only** raw data, with ICT/VPA-inspired features where feasible.

The current Phase A run shows **worse-than-baseline multi-logloss** on a **tri-class ATR threshold label** with very sparse directional events. This sprint adjusts:

1. **Universe & SIP integration** → focus on liquid, volatile 5–50 USD names (R2000 + SIP).
2. **Labels & thresholds** → drop the hard 1.5% absolute move; rely on ATR/volatility-scaled big-move detection.
3. **Feature pack** → enrich with VWAP distance, simple cross-sectional ranks, and slightly longer momentum horizons.
4. **Model training** → simplify imbalance handling (remove focal loss & double-validation), rely on purged CV and trading metrics.
5. **CV & trading evaluation** → align label horizons with trading horizon and top-k selection for 3–5 trades/day.

All work must **avoid look-ahead / data leakage**, **not use mock/synthetic data** except trivial smoke checks, and **not modify frozen core infrastructure** (`qx_core`, `qx_data`, `qx_backtest`, `qx_risk`) beyond what’s explicitly requested.

---

## 1. High-level objectives

* [ ] O1. Replace the 1.5% absolute move filter with **pure ATR/volatility-based big-move thresholds** in `targets_bigmove.yaml`.
* [ ] O2. Relax label balance/guard thresholds to increase **event density** while preserving economic meaning.
* [ ] O3. Enrich **Phase A 10-minute feature set** with VWAP distance, cross-sectional context, and slightly longer horizons.
* [ ] O4. Simplify **LightGBM tri-class training** (no focal loss, no internal random val split; rely on purged CV).
* [ ] O5. Align **label horizons** and **trading evaluation horizon** and keep trade density ≈ 3–5 trades/day.
* [ ] O6. Introduce a **universe builder for SIP+USD 5–50** tickers, wired into Phase A via config.
* [ ] O7. Run **smoke + full Phase A** experiments and record before/after metrics.
* [ ] O8. Keep this sprint file updated as a **living checklist** (check items as they are completed).

---

## 2. Files in scope

Config level:

* `configs/extensions/intraday_ml/targets_bigmove.yaml`
* `configs/extensions/intraday_ml/features_10m.yaml`
* `configs/extensions/intraday_ml/model_lgbm.yaml`
* `configs/extensions/intraday_ml/cv/phaseA.yaml`
* `configs/extensions/intraday_ml/universe_gold_full.yaml` (reference)
* New: `configs/extensions/intraday_ml/universe_intraday_sip_5_50.yaml` (to be created)

Artifacts / diagnostics (read-only):

* `artefacts/extensions/intraday_ml/phaseA_full_sip/manifest.json`
* `artefacts/extensions/intraday_ml/phaseA_full_sip/label_guard_report.json`

Universe / SIP helpers (to be located & then possibly extended):

* Any SIP generation scripts / configs mentioned in `SYSTEM_TECH_DOC.md` (e.g., HMM SIP pipeline).
* Any existing universe builder scripts under `qx_data`, `tools`, or `scripts`.

Core infra (`qx_*`) is **read-only** except where explicitly instructed.

---

## 3. Checklist – execution order

### 3.1. Environment & safety checks

* [x] **E1. Confirm working tree is clean.**

  * Run: `git status`
  * If there are uncommitted changes unrelated to this sprint, either commit them on a separate branch or stash them.

* [x] **E2. Create a dedicated sprint branch.**

  * Suggested name: `feature/intraday_ml_model_enhancement3_20251113`
  * Command:

    ```bash
    git checkout -b feature/intraday_ml_model_enhancement3_20251113
    ```

* [ ] **E3. Run a baseline Phase A smoke/backtest to have a “before” reference.**

  * Command (if feasible):

    ```bash
    python run_phaseA_pipeline.py \
      --config configs/extensions/intraday_ml/phaseA_sip_full.yaml
    ```
  * Archive key outputs (copy or note paths):

    * Old `artefacts/.../phaseA_full_sip/label_guard_report.json`
    * Old `artefacts/.../phaseA_full_sip/manifest.json`
    * Any metrics JSON / run logs associated with this config.

Update this file under a new heading “Baseline metrics” with whatever high-level stats you have (logloss, Sharpe, win-rate, trade density).

### Baseline metrics
- Existing `artefacts/extensions/intraday_ml/phaseA_full_sip/metrics.json` (2025-11-12 11:06 UTC): `sharpe_ratio` -100.95, `win_rate` 33%, `total_trades` 3, average R -0.763, total PnL -2.29; manifest symbol count 142, price range [10.6, 3783.5].
- Attempted to rerun Phase A (command per E3) but the scripts were timed out/aborted after ~10m per the latest instruction to avoid running the full production pipeline; no new metrics captured yet.

---

### 3.2. Universe & SIP integration (USD 5–50 band)

Goal: introduce a universe pipeline that either (a) directly filters by SIP + USD 5–50, or (b) builds a static YAML of relevant tickers from existing SIP outputs and gold data. For now, we implement **a script that builds a YAML universe** based on existing data, while keeping the SIP layer pluggable.

#### 3.2.1. Inspect current universe + manifest

* [x] **U1. Open the current intraday universe config and manifest.**

  * Files:

    * `configs/extensions/intraday_ml/universe_gold_full.yaml` (if present)
    * `artefacts/extensions/intraday_ml/phaseA_full_sip/manifest.json`
  * Confirm:

    * Current `universe_config.symbols`, `min_price`, `max_price`, `min_avg_daily_volume`, etc.
    * Universe currently includes large caps outside the 5–50 USD band.

  * Note: manifest reports price range ~10.6–3783.5 USD and 142 symbols after SIP filtering, so the current universe spans mega caps well above the targeted 5–50 band.

Add a short note in this sprint file summarising current price range and symbol count.

#### 3.2.2. Locate SIP outputs

* [x] **U2. Discover existing SIP/HMM outputs.**

  * Use `rg` or `find` to locate SIP pipelines:

    ```bash
    rg "SIP" -n . || true
    rg "HMM_SIP" -n . || true
    find . -iname "*sip*"
    ```
  * Identify:

    * The script(s) that produce daily or historical SIP scores/universes.
    * Any existing “SIP universe” or “SIP score” data products (CSV/Parquet).

  * Note: SIP helpers live under `qx-screener/src/qx_screener/` (e.g., `hmm_sip.py`, `daily_hmm_sip.py`, `sip.py`); the Phase A configs now point to `/home/jacobw/quantstack/run/sip_membership`.

Document the key script and data paths in this file (e.g., “SIP scores at `.../sip_scores.parquet`”).

#### 3.2.3. Implement universe builder for SIP + 5–50 band

* [x] **U3. Create a universe builder script.**

  * New file (example path, adjust if there is an existing helper location):

    * `scripts/build_intraday_universe_sip_5_50.py`
  * Requirements for the script:

    1. Read a **universe-level metadata/data source** from gold (or from an existing universe builder). If there is already a helper in `qx_data` or `tools` that summarises price/dollar volume, reuse it instead of reinventing it.
    2. For each candidate symbol, compute:

       * Median or typical price over the training window.
       * Average daily **dollar volume** over the training window.
    3. Filter to symbols where:

       * `5.0 <= median_price <= 50.0`
       * `avg_daily_dollar_volume >= LIQUIDITY_FLOOR` (start with **10M USD**; expose as a constant / CLI arg).
    4. If SIP scores are available:

       * Option A (strict): restrict to symbols that meet a **minimum SIP activity** criterion over the training window (e.g. in SIP top-N at least K days).
       * Option B (loose): build two lists, `all_5_50_liquid` and `sip_5_50_liquid` (union/ intersection of filters), and output both.
    5. Write a YAML file compatible with existing universe configs, e.g.:

       ```yaml
       max_universe_size: 600
       min_price: 5.0
       max_price: 50.0
       min_avg_daily_volume: 0        # already enforced via dollar volume
       min_relative_volume: 0.0
       symbols:  # list produced by this script
         - ABC
         - XYZ
         ...
       ```
    6. Support a CLI interface:

       ```bash
       python scripts/build_intraday_universe_sip_5_50.py \
         --output configs/extensions/intraday_ml/universe_intraday_sip_5_50.yaml \
         --min-price 5.0 \
         --max-price 50.0 \
         --min-dollar-vol 10000000
       ```

* [ ] **U4. Run the universe builder.**

  * Execute the script over the data currently available in the gold store.
  * Inspect the resulting YAML to confirm:

    * Symbols are mostly in the 5–50 USD band.
    * Universe size is reasonable (dozens to a few hundred symbols).
  * Command (run locally when convenient):

    ```bash
    python scripts/build_intraday_universe_sip_5_50.py \
      --output configs/extensions/intraday_ml/universe_intraday_sip_5_50.yaml \
      --min-price 5.0 \
      --max-price 50.0 \
      --min-dollar-vol 10000000
    ```

* [x] **U5. Wire Phase A to use the new universe.**

  * In `configs/extensions/intraday_ml/phaseA_sip_full.yaml` (or equivalent Phase A master config):

    * Replace the reference to `universe_gold_full.yaml` with `universe_intraday_sip_5_50.yaml`.
  * Ensure that `run_phaseA_pipeline.py` picks up the new universe via the config.

---

### 3.3. Label configuration – drop absolute 1.5% move, keep ATR-based big moves

Goal: rely on **ATR multipliers and volatility scaling** to define “big move” events, without imposing a hard 1.5% absolute return floor.

#### 3.3.1. Adjust `targets_bigmove.yaml`

* [x] **L1. Open `configs/extensions/intraday_ml/targets_bigmove.yaml`.**

Make the following changes:

* [x] **L2. Relax ATR multipliers slightly to broaden the event set.**

  * Existing:

    ```yaml
    atr_multiplier: 1.35
    atr_multiplier_long: 1.42
    atr_multiplier_short: 1.55
    ```
  * Change to (example starting point; keep symmetric but slightly lower):

    ```yaml
    atr_multiplier: 1.20
    atr_multiplier_long: 1.25
    atr_multiplier_short: 1.30
    ```

* [x] **L3. Remove the hard 1.5% realised move floor.**

  * Existing:

    ```yaml
    min_realized_return_pct: 0.015
    ```
  * Change to:

    ```yaml
    min_realized_return_pct: 0.0
    ```
  * Rely on ATR thresholds and `risk_reward` to enforce economic significance.

* [x] **L4. Soften ATR floor and flat-period exclusion (if too restrictive).**

  * Existing:

    ```yaml
    require_min_atr: 0.015
    exclude_flat_periods: true
    ```
  * Change to:

    ```yaml
    require_min_atr: 0.005
    exclude_flat_periods: true  # keep, but rely more on ATR multipliers
    ```

* [x] **L5. Relax directional balance settings.**

  * Existing:

    ```yaml
    directional_balance:
      enabled: true
      target_ratio: 1.0
      tolerance: 0.15
      max_iterations: 10
      adjust_step: 0.08
      growth_factor: 0.65
      min_directional: 25
      multiplier_bounds:
        min: 0.01
        max: 0.13
    ```
  * Change to (less aggressive balancing, lower min directional):

    ```yaml
    directional_balance:
      enabled: true
      target_ratio: 1.0
      tolerance: 0.25
      max_iterations: 10
      adjust_step: 0.06
      growth_factor: 0.65
      min_directional: 15
      multiplier_bounds:
        min: 0.01
        max: 0.13
    ```

* [x] **L6. Update horizons to align with trading evaluation.**

  * Existing:

    ```yaml
    horizons:
      - 45
      - 75
      - 120
    ```
  * Change to:

    ```yaml
    horizons:
      - 30
      - 60
      - 120
    ```

Leave `risk_reward` block enabled and unchanged for now; it already enforces `min_r_multiple: 1.5` and ATR-scaled stops/targets.

#### 3.3.2. Regenerate labels and inspect label guard

* [ ] **L7. Run Phase A up to dataset/label creation (no training required yet if there is a switch to stop early).**

  * Command (full run if there is no early-stop option):

    ```bash
    python run_phaseA_pipeline.py \
      --config configs/extensions/intraday_ml/phaseA_sip_full.yaml
    ```

  * **Note:** deferred for now to respect the request to avoid another long Phase A production run; please rerun once the new universe file exists.

* [ ] **L8. Inspect `label_guard_report.json`.**

  * Confirm that:

    * More symbols have non-zero directional labels.
    * Previously dropped symbols like AAPL/AMZN now have reasonable counts.
  * If still too sparse:

    * Consider lowering `min_directional` further (e.g., to 10) and/or further reducing ATR multipliers.

  * **Note:** will review once the next Phase A run completes; no new label guard output yet.

Document the new label counts for a few representative tickers in this sprint file.

---

### 3.4. Feature configuration – enrich Phase A 10-minute feature pack

Goal: keep within ~100 features while adding **VWAP distance**, **cross-sectional context**, and **slightly longer momentum horizons**.

* [x] **F1. Open `configs/extensions/intraday_ml/features_10m.yaml`.**

Make the following changes:

* [x] **F2. Enable VWAP distance.**

  * Change:

    ```yaml
    vwap_distance:
      enabled: false
    ```
  * To:

    ```yaml
    vwap_distance:
      enabled: true
    ```

* [x] **F3. Enable basic cross-sectional features.**

  * Change:

    ```yaml
    cross_section:
      enabled: false
    ```
  * To:

    ```yaml
    cross_section:
      enabled: true
    ```
  * Do **not** add complex sub-config unless a schema already exists; rely on defaults provided by the feature registry.

* [x] **F4. Extend momentum/returns windows modestly.**

  * In `returns_trend`:

    * Existing:

      ```yaml
      windows: [1, 2, 3]
      ```
    * Change to:

      ```yaml
      windows: [1, 2, 3, 6, 12]
      ```
  * In `price_momentum`:

    * Existing:

      ```yaml
      roc_windows: [1, 2, 3]
      rsi_windows: [6]
      ma_windows: [3, 6]
      ```
    * Change to:

      ```yaml
      roc_windows: [1, 2, 3, 6, 12]
      rsi_windows: [6, 12]
      ma_windows: [3, 6, 12]
      ```

* [x] **F5. Keep feature limits and leakage checks.**

  * Ensure:

    ```yaml
    max_total_features: 100
    leakage_check: true
    min_non_null_ratio: 0.9
    max_feature_correlation: 0.95
    ```

    remain unchanged.

* [ ] **F6. Regenerate features for a small smoke sample to confirm no schema breakage.**

  * If there is a smoke pipeline (per `SYSTEM_TECH_DOC.md`), run it, e.g.:

    ```bash
    python check_gold_and_make_smoke_sample.py  # or the documented command
    ```
  * Then run Phase A on smoke or a reduced config if available.

Document any feature validation warnings/errors in this sprint file and resolve before proceeding.

  * **Note:** Postponed pending a safe, low-cost smoke run; no additional feature generation was executed yet.

---

### 3.5. Model configuration – simplify imbalance handling

Goal: keep tri-class LightGBM, but remove **stacked imbalance tricks** (focal loss + auto-balance + internal random val) so training is more stable and interpretable. We will still use class weights and purged CV.

* [x] **M1. Open `configs/extensions/intraday_ml/model_lgbm.yaml`.**

Apply the following edits:

* [x] **M2. Disable focal loss.**

  * Change:

    ```yaml
    loss_tuning:
      focal_loss:
        enabled: true
        gamma: 1.4
        alpha:
          -1: 1.0
          0: 0.4
          1: 1.0
    ```
  * To:

    ```yaml
    loss_tuning:
      focal_loss:
        enabled: false
        gamma: 1.4
        alpha:
          -1: 1.0
          0: 0.4
          1: 1.0
    ```
  * (Keep parameters for possible future re-activation.)

* [x] **M3. Simplify class weighting.**

  * In `class_weights`:

    * Keep the `base` weights as is:

      ```yaml
      base:
        -1: 2.4
        0: 1.0
        1: 2.4
      ```
    * Disable automatic balancing:

      ```yaml
      auto_balance:
        enabled: false
      ```

      and remove or ignore the rest of the `auto_balance` keys.

* [x] **M4. Disable internal random validation split and shuffling.**

  * Change:

    ```yaml
    training:
      early_stopping_rounds: 75
      eval_metric: "multi_logloss"
      validation_split: 0.25
      shuffle: true
      stratify_by_class: true
      ...
    ```
  * To:

    ```yaml
    training:
      early_stopping_rounds: 75
      eval_metric: "multi_logloss"
      validation_split: 0.0
      shuffle: false
      stratify_by_class: false
      ...
    ```
  * We will rely on **purged CV** defined in `phaseA.yaml` for validation.

* [x] **M5. Keep top-k objective and abstention guard for now.**

  * Do not change:

    * `training.topk_objective`
    * `training.abstention_guard`
  * We will evaluate their behaviour after we see new label/feature distribution.

* [x] **M6. Save and ensure YAML remains valid.**

---

### 3.6. CV & trading evaluation – align horizons

Goal: ensure that label horizons and trading evaluation horizon are consistent with the trade design (15–240 minutes) and that model selection prioritises **economic metrics**.

* [x] **C1. Open `configs/extensions/intraday_ml/cv/phaseA.yaml`.**

Apply the following adjustments:

* [x] **C2. Align trading horizon with label horizons.**

  * Change:

    ```yaml
    trading_evaluation:
      enabled: true
      horizon_minutes: 30
      transaction_cost_bps: 12
      ...
    ```
  * To:

    ```yaml
    trading_evaluation:
      enabled: true
      horizon_minutes: 60
      transaction_cost_bps: 12
      ...
    ```
  * This uses 60 minutes as the main evaluation horizon, consistent with the updated label horizons `[30, 60, 120]`.

* [x] **C3. Emphasise economic metrics for model selection (conceptual, config-driven).**

  * Ensure `metrics` retains both prediction and economic metrics:

    ```yaml
    metrics:
      primary_metrics:
        - accuracy
        - f1_macro
        - brier_score
      economic_metrics:
        - expectancy
        - sharpe_ratio
        - win_rate
      trade_density:
        - trades_per_ticker_day
        - abstention_rate
    ```
  * The experiment harness should **rank models primarily by Sharpe/expectancy under `trading_evaluation`**, not raw logloss. If there is an experiment runner config that controls metric weighting, update it accordingly in a later step.

---

### 3.7. Re-run Phase A – diagnostics

* [ ] **R1. Run a full Phase A pipeline with the updated configs.**

  * Command:

    ```bash
    python run_phaseA_pipeline.py \
    --config configs/extensions/intraday_ml/phaseA_sip_full.yaml
  ```

  * **Note:** Deferred alongside other heavy Phase A runs; rerun once the universe builder output exists and we can afford the runtime.

* [ ] **R2. Inspect the new `manifest.json` and `label_guard_report.json`.**

  * Confirm:

    * Larger number of symbols retained.
    * More balanced directional label counts per symbol.
    * Reasonable label distribution for updated horizons (30/60/120).

  * **Note:** Waiting on R1 completion before reviewing new artefacts; no new manifest/label guard data yet.

* [ ] **R3. Capture model training metrics.**

  * Collect (from logs or metrics files):

    * Validation multi-logloss vs frequency baseline.
    * Accuracy / F1 / Brier score.
    * Economic metrics under `trading_evaluation` (expectancy, Sharpe, win-rate, trade density).

  * **Note:** Metrics capture pending the next Phase A run; slot this in once R1/R2 execute.

Record “before vs after” comparisons in this sprint file under a new heading.

---

### 3.8. Optional: add a regression-on-R model variant

If time permits during this sprint, add a **secondary model config** to experiment with regressing on realised R instead of pure classification. This is optional for now; do not start it unless all objectives O1–O7 are satisfied.

* [ ] **X1. Create `configs/extensions/intraday_ml/model_lgbm_R.yaml`** with a LightGBM regression objective (e.g., `objective: regression_l2`) targeting realised R.
* [ ] **X2. Add it as a separate experiment entry so it can be evaluated side-by-side with the tri-class classifier using the same trading evaluation block.

---

### 3.9. Finalisation

* [ ] **FNL1. Review code changes.**

  * Run `git diff` and ensure only intended files are modified.

* [ ] **FNL2. Run tests / basic lint if available.**

  * Example:

    ```bash
    pytest -q  # if the project has tests
    ```

    or any documented quick test commands.

* [ ] **FNL3. Update this sprint file.**

  * Check off completed items and add a short “Outcome” section summarising:

    * Key config changes (labels, features, model, CV, universe).
    * Before/after highlights on Sharpe, win-rate, trades/day.

* [ ] **FNL4. Commit and push.**

  * Example:

    ```bash
    git add 20251113_model_enhancement3.md \
            configs/extensions/intraday_ml/targets_bigmove.yaml \
            configs/extensions/intraday_ml/features_10m.yaml \
            configs/extensions/intraday_ml/model_lgbm.yaml \
            configs/extensions/intraday_ml/cv/phaseA.yaml \
            configs/extensions/intraday_ml/universe_intraday_sip_5_50.yaml \
            scripts/build_intraday_universe_sip_5_50.py
    git commit -m "Intraday ML: Model Enhancement Sprint 3 – labels, features, LGBM, universe"
    git push -u origin feature/intraday_ml_model_enhancement3_20251113
    ```

* [ ] **FNL5. Tag or annotate the best model run.**

  * Use whatever experiment tracking exists (e.g., `qx-report` or a runs directory) to mark the run that best meets the objectives:

    * Positive Sharpe, win-rate ≥ ~60%, 3–5 trades/day, controlled drawdowns.

---

## 4. Notes / scratchpad

Use this section during the sprint for ad-hoc notes, metric snapshots, and TODOs that arise as you iterate.

- **E1/E2:** Verified clean tree, created `feature/intraday_ml_model_enhancement3_20251113`, and documented branch status above.
- **Baseline run:** Launched `python run_phaseA_pipeline.py --config configs/extensions/intraday_ml/phaseA_sip_full.yaml` twice but both invocations timed out/aborted; per latest instruction the full production run will be skipped for now (TODO: rerun once allowed to capture true baseline metrics and label guard snapshots).
- **Universe builder:** Created `scripts/build_intraday_universe_sip_5_50.py`; command to generate the 5–50 USD YAML is documented above. A partial run was aborted for time, so please rerun that command and verify `configs/extensions/intraday_ml/universe_intraday_sip_5_50.yaml` before U4 can be checked off.
- **Universe stub:** Added `configs/extensions/intraday_ml/universe_intraday_sip_5_50.yaml` with the default schema so Phase A can reference it ahead of the script output; the builder will overwrite the symbol list once executed.
- **Builder fix:** Adjusted the script to let `qx_data.gold_loader.load_bars` pull the default column set (injecting `symbol` when absent) to avoid `FieldRef.Name(symbol)` errors from PyArrow when the raw parquet lacks that column.
