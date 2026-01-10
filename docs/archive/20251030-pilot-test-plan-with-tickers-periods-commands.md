# Pilot Test Plan: Exact Tickers, Periods, and Commands
**Repo:** `/quantstack`  
**Context:** You currently have **S&P 500, 5‑year, 1‑minute OHLCV enriched data**. This pilot validates the new intraday ML pipeline end‑to‑end in three phases: single‑ticker smoke, expanded pilot, and full‑scale training. All steps are configuration‑first and MUST NOT modify core qx‑* modules.

> All commands assume virtualenv is activated, working directory is repo root, and the extension CLIs created in the sprints are available as Python modules. If any CLI wrapper is missing, import the module and call the function from a small shim under `extensions/intraday_ml/cli/` without changing upstream/downstream code.

---

## Phase A — Single‑Ticker Functionality Smoke

**Goal:** Prove E2E path (universe → features → labels → LightGBM train+calibration → policy → CV sanity) on **one ticker** over modest periods.

### Exact Selection
- **Ticker:** `BAC`  (liquid, usually within the 5–50 USD band over the last years)
- **Train:** `2022‑01‑01` → `2023‑12‑31`
- **Validation:** `2024‑01‑01` → `2024‑01‑31`
- **OOS (smoke):** `2024‑02‑01` → `2024‑02‑29`
- **Decision cuts (ET):** `09:35`, `11:00`, `13:30`, `14:30`
- **Targets:** horizons `[30, 60, 90]` minutes; `k_ATR = 1.0`

### Create/Update Configs
```bash
# Universe (Phase A)
mkdir -p configs/extensions/intraday_ml/universe phases/phaseA && cat > configs/extensions/intraday_ml/universe/phaseA.yaml <<'YAML'
symbols: [BAC]
price_band: [5, 50]
min_trading_days: 200
liquidity_filter:
  adv_usd_min: 5_000_000
  adv_percentile_min: 20
YAML

# Splits (Phase A)
mkdir -p configs/extensions/intraday_ml/splits && cat > configs/extensions/intraday_ml/splits/phaseA.yaml <<'YAML'
train:
  start: "2022-01-01"
  end:   "2023-12-31"
val:
  start: "2024-01-01"
  end:   "2024-01-31"
oos:
  start: "2024-02-01"
  end:   "2024-02-29"
embargo_days: 5
purge_days: 5
YAML

# Decision cuts (global OK)
mkdir -p configs/extensions/intraday_ml && cat > configs/extensions/intraday_ml/cuts.yaml <<'YAML'
cuts_et: ["09:35", "11:00", "13:30", "14:30"]
YAML

# Features (use your M2 pack)
cat > configs/extensions/intraday_ml/features.yaml <<'YAML'
families:
  returns_trend:    {enabled: true}
  volatility_range: {enabled: true}
  volume_flow:      {enabled: true}
  vwap_distance:    {enabled: true}
  time_seasonality: {enabled: true}
  cross_section:    {enabled: true}
  price_momentum:   {enabled: true}
  microstructure:   {enabled: true}
max_features: 150
null_ratio_min: 0.90
YAML

# Targets (Phase A)
mkdir -p configs/extensions/intraday_ml/targets && cat > configs/extensions/intraday_ml/targets/phaseA.yaml <<'YAML'
horizons_min: [30, 60, 90]
k_atr: 1.0
labeling: tri_class_first_hit
YAML

# Model (LightGBM)
cat > configs/extensions/intraday_ml/model_lgbm.yaml <<'YAML'
objective: multiclass
num_class: 3
learning_rate: 0.05
num_leaves: 63
max_depth: -1
min_data_in_leaf: 200
feature_fraction: 0.6
bagging_fraction: 0.6
bagging_freq: 5
class_weights: {neg: 1.0, neu: 0.5, pos: 1.0}
calibration: isotonic
seed: 42
YAML

# CV (Phase A)
mkdir -p configs/extensions/intraday_ml/cv && cat > configs/extensions/intraday_ml/cv/phaseA.yaml <<'YAML'
folds: 3
embargo_days: 5
purge_days: 5
walk_forward: false
metrics: [f1_posneg, aucpr_posneg, brier, expectancy, trade_rate]
YAML
```

### Run Commands
```bash
# 1) Build dataset manifest (hashes + availability)
python -m extensions.intraday_ml.dataset_manifest   --universe configs/extensions/intraday_ml/universe/phaseA.yaml   --splits   configs/extensions/intraday_ml/splits/phaseA.yaml   --cuts     configs/extensions/intraday_ml/cuts.yaml   --out      artefacts/extensions/intraday_ml/phaseA/manifest.json

# 2) Build features (M2 pack)
python -m extensions.intraday_ml.feature_pack   --manifest artefacts/extensions/intraday_ml/phaseA/manifest.json   --config   configs/extensions/intraday_ml/features.yaml   --out      artefacts/extensions/intraday_ml/phaseA/features.parquet

# 3) Build labels (ATR prominent moves, no‑peek)
python -m extensions.intraday_ml.labeling   --manifest artefacts/extensions/intraday_ml/phaseA/manifest.json   --targets  configs/extensions/intraday_ml/targets/phaseA.yaml   --out      artefacts/extensions/intraday_ml/phaseA/labels.parquet

# 4) Train LightGBM (+calibration) on Train+Val, save model card
python -m extensions.intraday_ml_models.train_lgbm   --features artefacts/extensions/intraday_ml/phaseA/features.parquet   --labels   artefacts/extensions/intraday_ml/phaseA/labels.parquet   --splits   configs/extensions/intraday_ml/splits/phaseA.yaml   --model    configs/extensions/intraday_ml/model_lgbm.yaml   --out_dir  artefacts/extensions/intraday_ml/phaseA/model_lgbm

# 5) Sanity CV (purged, embargoed)
python -m extensions.intraday_ml_models.cv_runner   --features artefacts/extensions/intraday_ml/phaseA/features.parquet   --labels   artefacts/extensions/intraday_ml/phaseA/labels.parquet   --cv       configs/extensions/intraday_ml/cv/phaseA.yaml   --report   artefacts/extensions/intraday_ml/phaseA/cv_report.json

# 6) Backtest OOS using decision policy gates (no daily hard cap)
python -m extensions.intraday_ml_models.decision_policy   --model_dir artefacts/extensions/intraday_ml/phaseA/model_lgbm   --features  artefacts/extensions/intraday_ml/phaseA/features.parquet   --labels    artefacts/extensions/intraday_ml/phaseA/labels.parquet   --oos_only  true   --report    artefacts/extensions/intraday_ml/phaseA/policy_oos.json
```

**Exit Criteria (Phase A):**
- Pipeline runs E2E without touching core modules.
- CV report produced; hashes present; leakage tests pass.
- Trade‑rate reasonable for single ticker (median 0.5–3/day) with gates.

---

## Phase B — Expanded Pilot (8 Tickers, 12–18 Months)

**Goal:** Validate generalization, stability and trade‑rate shaping across tickers and a longer window.

### Exact Selection (diversified SP500 set)
- **Tickers (8):** `BAC, T, PFE, WBA, KHC, CMCSA, F, C`
- **Train:** `2022‑01‑01` → `2023‑12‑31`
- **Validation:** `2024‑01‑01` → `2024‑03‑31`
- **OOS:** `2024‑04‑01` → `2024‑04‑30`

### Configs
```bash
# Universe (Phase B)
cat > configs/extensions/intraday_ml/universe/phaseB.yaml <<'YAML'
symbols: [BAC, T, PFE, WBA, KHC, CMCSA, F, C]
price_band: [5, 50]
min_trading_days: 200
liquidity_filter:
  adv_usd_min: 5_000_000
  adv_percentile_min: 20
YAML

# Splits (Phase B)
cat > configs/extensions/intraday_ml/splits/phaseB.yaml <<'YAML'
train:
  start: "2022-01-01"
  end:   "2023-12-31"
val:
  start: "2024-01-01"
  end:   "2024-03-31"
oos:
  start: "2024-04-01"
  end:   "2024-04-30"
embargo_days: 5
purge_days: 5
YAML

# CV (Phase B) — stricter
cat > configs/extensions/intraday_ml/cv/phaseB.yaml <<'YAML'
folds: 5
embargo_days: 5
purge_days: 5
walk_forward: true
metrics: [f1_posneg, aucpr_posneg, brier, expectancy, trade_rate]
YAML

# Targets can reuse Phase A targets (or set k_atr=1.2 if too many trades)
cp configs/extensions/intraday_ml/targets/phaseA.yaml configs/extensions/intraday_ml/targets/phaseB.yaml
```

### Run Commands
```bash
# 1) Manifest
python -m extensions.intraday_ml.dataset_manifest   --universe configs/extensions/intraday_ml/universe/phaseB.yaml   --splits   configs/extensions/intraday_ml/splits/phaseB.yaml   --cuts     configs/extensions/intraday_ml/cuts.yaml   --out      artefacts/extensions/intraday_ml/phaseB/manifest.json

# 2) Features
python -m extensions.intraday_ml.feature_pack   --manifest artefacts/extensions/intraday_ml/phaseB/manifest.json   --config   configs/extensions/intraday_ml/features.yaml   --out      artefacts/extensions/intraday_ml/phaseB/features.parquet

# 3) Labels
python -m extensions.intraday_ml.labeling   --manifest artefacts/extensions/intraday_ml/phaseB/manifest.json   --targets  configs/extensions/intraday_ml/targets/phaseB.yaml   --out      artefacts/extensions/intraday_ml/phaseB/labels.parquet

# 4) Train + calibrate
python -m extensions.intraday_ml_models.train_lgbm   --features artefacts/extensions/intraday_ml/phaseB/features.parquet   --labels   artefacts/extensions/intraday_ml/phaseB/labels.parquet   --splits   configs/extensions/intraday_ml/splits/phaseB.yaml   --model    configs/extensions/intraday_ml/model_lgbm.yaml   --out_dir  artefacts/extensions/intraday_ml/phaseB/model_lgbm

# 5) CV + tuning
python -m extensions.intraday_ml_models.cv_runner   --features artefacts/extensions/intraday_ml/phaseB/features.parquet   --labels   artefacts/extensions/intraday_ml/phaseB/labels.parquet   --cv       configs/extensions/intraday_ml/cv/phaseB.yaml   --report   artefacts/extensions/intraday_ml/phaseB/cv_report.json

python -m extensions/intraday_ml_models.tune_lgbm   --features artefacts/extensions/intraday_ml/phaseB/features.parquet   --labels   artefacts/extensions/intraday_ml/phaseB/labels.parquet   --cv       configs/extensions/intraday_ml/cv/phaseB.yaml   --base_model_cfg configs/extensions/intraday_ml/model_lgbm.yaml   --out_dir  artefacts/extensions/intraday_ml/phaseB/tuning
```

**Exit Criteria (Phase B):**
- CV stability: coefficient of variation for F1, AUC‑PR, expectancy < 0.25.
- Trade‑rate (OOS): median in **0.5–3.0 trades/ticker/day** without hard caps.
- Calibration improved vs. uncalibrated (Brier ↓ ≥10%).

---

## Phase C — Full‑Scale SP500 (5 Years)

**Goal:** Train on the full available S&P 500 dataset, preserve reproducibility and performance constraints, and produce deployment‑ready artefacts.

### Exact Selection
- **Universe:** all SP500 symbols present in your Gold data universe file  
  (generate from SIP/HMM screener or simply list all SP500 symbols available)
- **Train:** `2020‑01‑01` → `2024‑12‑31` (or earliest → latest 5 years you have)
- **Validation:** last 2–3 months before final OOS
- **Final OOS:** most recent full month available

### Configs
```bash
# Universe (Phase C) — placeholder; generate dynamically if you have a “full” list
mkdir -p artefacts/extensions/intraday_ml/phaseC configs/extensions/intraday_ml/universe && cat > configs/extensions/intraday_ml/universe/phaseC.yaml <<'YAML'
symbols_file: "artefacts/extensions/intraday_ml/phaseC/sp500_symbols.txt"
price_band: [5, 50]
min_trading_days: 600
liquidity_filter:
  adv_usd_min: 10_000_000
  adv_percentile_min: 30
YAML

# Splits (Phase C)
cat > configs/extensions/intraday_ml/splits/phaseC.yaml <<'YAML'
train:
  start: "2020-01-01"
  end:   "2024-10-31"
val:
  start: "2024-11-01"
  end:   "2024-12-31"
oos:
  start: "2025-01-01"
  end:   "2025-01-31"
embargo_days: 5
purge_days: 5
YAML

# CV (Phase C)
cat > configs/extensions/intraday_ml/cv/phaseC.yaml <<'YAML'
folds: 5
embargo_days: 5
purge_days: 5
walk_forward: true
metrics: [f1_posneg, aucpr_posneg, brier, expectancy, trade_rate]
YAML
```

### Run Commands
```bash
# 0) Prepare SP500 symbols file (from your Gold store index or screener)
# Write one symbol per line to artefacts/extensions/intraday_ml/phaseC/sp500_symbols.txt

# 1) Manifest
python -m extensions.intraday_ml.dataset_manifest   --universe configs/extensions/intraday_ml/universe/phaseC.yaml   --splits   configs/extensions/intraday_ml/splits/phaseC.yaml   --cuts     configs/extensions/intraday_ml/cuts.yaml   --out      artefacts/extensions/intraday_ml/phaseC/manifest.json

# 2) Features (monitor runtime; batch by sector if needed)
python -m extensions.intraday_ml.feature_pack   --manifest artefacts/extensions/intraday_ml/phaseC/manifest.json   --config   configs/extensions/intraday_ml/features.yaml   --out      artefacts/extensions/intraday_ml/phaseC/features.parquet

# 3) Labels
python -m extensions.intraday_ml.labeling   --manifest artefacts/extensions/intraday_ml/phaseC/manifest.json   --targets  configs/extensions/intraday_ml/targets/phaseA.yaml   --out      artefacts/extensions/intraday_ml/phaseC/labels.parquet

# 4) Train + calibrate (consider CPU‑only; LightGBM scales well)
python -m extensions.intraday_ml_models.train_lgbm   --features artefacts/extensions/intraday_ml/phaseC/features.parquet   --labels   artefacts/extensions/intraday_ml/phaseC/labels.parquet   --splits   configs/extensions/intraday_ml/splits/phaseC.yaml   --model    configs/extensions/intraday_ml/model_lgbm.yaml   --out_dir  artefacts/extensions/intraday_ml/phaseC/model_lgbm

# 5) CV + tuning
python -m extensions.intraday_ml_models.cv_runner   --features artefacts/extensions/intraday_ml/phaseC/features.parquet   --labels   artefacts/extensions/intraday_ml/phaseC/labels.parquet   --cv       configs/extensions/intraday_ml/cv/phaseC.yaml   --report   artefacts/extensions/intraday_ml/phaseC/cv_report.json

python -m extensions/intraday_ml_models.tune_lgbm   --features artefacts/extensions/intraday_ml/phaseC/features.parquet   --labels   artefacts/extensions/intraday_ml/phaseC/labels.parquet   --cv       configs/extensions/intraday_ml/cv/phaseC.yaml   --base_model_cfg configs/extensions/intraday_ml/model_lgbm.yaml   --out_dir  artefacts/extensions/intraday_ml/phaseC/tuning
```

---

## Quick Acceptance Checklist (per phase)
- [ ] Configs written; no hardcoded magic numbers in code.
- [ ] Manifest & hashes generated.
- [ ] Feature pack passes registry & leakage tests.
- [ ] Labels pass no‑peek checks (`ts_cut+1m` forward window).
- [ ] LightGBM model trained and calibrated; model card saved.
- [ ] CV report generated; stability within targets.
- [ ] Decision policy report shows reasonable trade‑rate and holding times.
- [ ] Backtest output respects next‑bar execution and flat‑EOD.
