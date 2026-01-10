# Intraday ML Upgrade: Sprint Plan (Items 1–4)
**Repo:** `/quantstack`  
**Scope:** Implement the first four priorities required to turn the current rule-based pilot into a real machine‑learning pipeline:  
1) Expand training **data & universe** (pilot‑ready, scalable).  
2) Build a richer **feature pack** (≤150 features, leakage‑proof).  
3) Implement a production‑grade **ML model** (start with LightGBM classifier).  
4) Add **time‑aware CV & hyperparameter tuning** (with trade‑rate shaping to avoid micro‑trades).

> This plan assumes the current pilot runs via `python run_ml_portfolio_test.py` but **does not** rely on it for ML. We will add the ML path under the **extensions** namespaces only, per policy.

---

## 0) Guardrails, Context, and Non‑Negotiables

### Modification Policy
- **NEVER edit existing core modules** (`qx-core`, `qx-data`, `qx-features`, `qx-backtest`, `qx-cli`).  
- **ONLY add new files** under:
  - `extensions/intraday_ml/**`
  - `extensions/intraday_ml_models/**`
  - `extensions/intraday_ml_policies/**`
  - `configs/extensions/intraday_ml/**`
  - `docs/extensions/intraday_ml/**`
  - `tests/extensions/intraday_ml/**`
- If a core change seems required, create `docs/PROPOSED_CHANGES/CHANGE_REQUEST.md` and stop.

### Trading Rules (hard constraints)
- **No forward look / no data spill.** Features/labels must depend on data `≤ ts_cut`; labels’ windows start at `ts_cut + 1m`.
- **Execution discipline.** Signal bar ≠ fill bar; fills occur on the first full bar **after** signal.
- **Flat EOD.** No overnight positions; flat by `15:59:59 ET`.
- **Config, not code.** All thresholds, cut times, filters live in YAML under `configs/extensions/intraday_ml/`.

### Coder Rules (enforced by tests/hooks)
- Use existing loaders (`qx_data.gold_loader.load_bars`), feature primitives/registry (`qx_features`), and backtest engine.
- Public APIs in new code must start with `intraday_ml_*`.
- No vendor SDKs, network calls, or file‑IO shortcuts in features/labels/policy.
- Reproducibility: integrate `intraday_ml_get_*_hash` to stamp data, features, risk, backtest artefacts.

---

## Milestone Overview
- **M1 (Item 1):** Data & universe expansion (pilot‑scale, repeatable)  
- **M2 (Item 2):** Intraday feature pack (≤150 features; registry + docs + tests)  
- **M3 (Item 3):** ML classifier (LightGBM first) + probability calibration + decision policy  
- **M4 (Item 4):** Time‑aware CV & tuning + *trade‑rate shaping* to avoid micro‑trades

Each milestone is one sprint (5–8 focused days). Sprints include purpose, deliverables, substeps, explicit tests, and KPIs.

---

## Sprint M1 — Data & Universe (Item 1)

### Purpose
Provide a scalable, deterministic pipeline to build **Train/Val/OOS** datasets from Gold bars with a pilot universe, ready to grow to 100–300 symbols.

### Deliverables
- `configs/extensions/intraday_ml/universe.yaml`  
  - Price band `[5, 50]`, ADV percentile filters, min trading days.
- `configs/extensions/intraday_ml/cuts.yaml`  
  - Intraday decisions at `09:35, 11:00, 13:30, 14:30` ET.
- `configs/extensions/intraday_ml/splits.yaml`  
  - Train `T` months, Val `V` months, OOS `O` months; purged CV with embargo (e.g., 5 trading days).
- `extensions/intraday_ml/universe_adapter.py`  
  - Thin adapter that calls existing screener/universe utilities, no duplication.
- `extensions/intraday_ml/dataset_manifest.py`  
  - Emits a manifest with data hash, symbol list, date ranges, cut times.

### Substeps
1) **Universe selection:** apply existing screener on Gold bars; restrict to `[5, 50]` USD and liquidity filters.  
2) **Time splits:** compute contiguous Train/Val/OOS ranges from config; store in manifest.  
3) **Manifest & hashes:** compute and save `intraday_ml_get_data_hash` keyed by symbols, dates, vendor provenance.  
4) **Smoke build:** load 2–5 pilot symbols (e.g., AAPL, MSFT, two R2000 names) for 12 months Train, 1 month Val, 1 month OOS.

### Tests
- **Universe correctness:** price band, ADV thresholds enforced; no delisted/suspended days in OOS.
- **Split integrity:** no overlap; embargo respected.
- **Hash stability:** re-run yields identical `data_hash` and symbol lists.

### KPIs
- **Coverage:** ≥ 95% of minutes present for selected symbols.
- **Universe size (pilot):** 4–12 symbols.
- **Load time:** p95 < 90s for pilot.

---

## Sprint M2 — Feature Pack (Item 2)

### Purpose
Create a **leakage‑proof** intraday feature pack (≤150 columns) registered under `intraday_ml` with strict schemas and docs.

### Deliverables
- `extensions/intraday_ml/feature_pack.py`  
  - Features grouped: returns & trend, volatility & ranges, volume/flow, VWAP distance & z‑scores, time‑of‑day seasonality, cross‑section signals.
- `extensions/intraday_ml/feature_registry.py`  
  - Registry that enumerates features, windows, dependencies, dtypes, null policies.
- `docs/extensions/intraday_ml/FEATURE_CATALOG.md`  
  - Human‑readable definitions, formulas, windows.
- `configs/extensions/intraday_ml/features.yaml`  
  - Which families to compute; per‑family parameters.
- **No duplication:** always import primitives from `qx_features` first; thin adapters otherwise.
- Hashing: `intraday_ml_get_features_hash` written into the manifest.

### Substeps
1) **Design catalog:** pick ≤150 features with explicit windows.  
2) **Implement adapters:** for gaps in `qx_features` primitives, write thin wrappers only.  
3) **Time discipline:** all features must stop at `ts_cut` exactly.  
4) **Registry & validation:** schema checker that compares produced columns vs registry.

### Tests
- **Unit:** deterministic outputs on golden subset; dtype & null-policy checks.  
- **Property:** for random 1k cuts, `max_dep_ts ≤ ts_cut`.  
- **Registry exactness:** columns match registry; no rogue names.  
- **Performance smoke:** compute pack for 4–12 symbols within budget (p95 < 120s).

### KPIs
- **Leakage violations:** 0.  
- **Reproducibility:** `features_hash` stable across runs.  
- **Runtime (pilot):** p95 < 120s for pack computation.

---

## Sprint M3 — ML Model (Item 3)

### Purpose
Train a **LightGBM** tri‑class classifier to predict ATR‑thresholded “prominent moves” over horizons {30, 60, 90} minutes, with **probability calibration** and a **decision policy** that favours **fewer, larger trades** (no hard daily caps).

> Start with **LightGBM** only. N‑HiTS or other forecasters can be compared later.

### Labels
- `y_class ∈ {-1, 0, +1}` based on first‑hit logic:  
  - +1 if `max(fwd_return) ≥ +k*ATR` before `min(fwd_return) ≤ -k*ATR`  
  - −1 if `min(fwd_return) ≤ -k*ATR` before `max(fwd_return) ≥ +k*ATR`  
  - 0 otherwise  
- Horizons: 30/60/90 minutes from `ts_cut`.  
- ATR: 14‑period on 1‑min regular bars, computed ≤ `ts_cut`.

### Deliverables
- `extensions/intraday_ml/labeling.py` (no peek; horizon windows start at `ts_cut+1m`).  
- `extensions/intraday_ml_models/train_lgbm.py` (dataset load, class weights, calibration).  
- `extensions/intraday_ml_models/model_io.py` (versioned save/load; model card).  
- `configs/extensions/intraday_ml/targets.yaml` (horizons, k_ATR).  
- `configs/extensions/intraday_ml/model_lgbm.yaml` (grid, class_weights, calibration).  
- Hashing: embed `features_hash` + `targets_hash` into model artefact metadata.

### Decision Policy (to reduce micro‑trades)
- **Probability gate:** predict `P(+1)`, `P(−1)`, trade only if `max_prob ≥ θ`, where θ is tuned to reduce trade count while improving expected move quality.  
- **Minimum expected move:** require `E[|move|] ≥ λ*ATR` (estimate via calibrated probs + ATR).  
- **Volatility‑aware cool‑down:** no new entries for `cooldown_mins = f(ATR, time_of_day)` after an entry or exit.  
- **Time‑of‑day filter:** disallow entries in the first 1–3 minutes after open unless confidence ≥ θ_open.

> These soft constraints **shape** trade frequency without hard caps.

### Tests
- **Label no‑peek:** forward window starts strictly at `ts_cut+1m`; ATR ≤ `ts_cut`.  
- **Calibration:** reliability diagram monotonic; Brier score improves post‑calibration.  
- **Policy adherence:** unit tests that block trades when `max_prob < θ`, or `E[|move|] < λ*ATR`, or within cooldown.  
- **Execution discipline:** next‑bar fills only; EOD flatness weekly replay.  

### KPIs
- **Signal quality:** precision@θ on ±1 classes ≥ target; abstain rate tracked.  
- **Trade density:** median trades/ticker/day in [0.5, 3.0] for pilot (no hard limit enforced).  
- **Holding time:** median in [20, 90] minutes; micro‑trades (<5m) < 10% of total.  
- **PnL expectancy:** positive; standard cost/slippage model applied.  
- **Calibration:** Brier score improvement vs. uncalibrated baseline.

---

## Sprint M4 — Time‑Aware CV & Tuning (Item 4)

### Purpose
Add robust validation: **purged, embargoed time‑series CV**, **walk‑forward evaluation**, and **Bayesian hyperparameter tuning** with **trade‑rate shaping** in the objective.

### Deliverables
- `configs/extensions/intraday_ml/cv.yaml` (folds, embargo, WFO schedule).  
- `extensions/intraday_ml_models/cv_runner.py` (purged CV splits, metrics aggregation).  
- `extensions/intraday_ml_models/tune_lgbm.py` (Bayesian tuner; early stopping).  
- **Objective with trade‑rate shaping:** maximize a composite metric such as  
  `score = α·F1(±1) + β·AUCpr(±1) + γ·Expectancy – δ·TradeRate`,  
  where `TradeRate = trades_per_day_per_ticker` measured out‑of‑fold.

### Substeps
1) **Purged CV:** avoid leakage across folds; embargo ≥ 5 trading days.  
2) **Metric suite:** F1 for ±1, abstain rate, Brier score, expectancy, drawdown, **trade rate**.  
3) **Bayesian tuning:** search over thresholds θ, λ, cooldown, LightGBM params (num_leaves, max_depth, min_child_weight, subsampling).  
4) **Walk‑forward:** train on expanding windows; score on next month; log KPIs + trade rate.

### Tests
- **Fold correctness:** no overlap pre/post embargo.  
- **Reproducibility:** same seeds → same tuned params.  
- **Objective shape:** increasing θ reduces trade rate in CV (sanity check).

### KPIs
- **Stability:** coefficient of variation of KPIs across folds < 0.25.  
- **Trade‑rate target:** median trades/ticker/day in [0.5, 3.0] in OOS.  
- **Generalization:** OOS precision@θ within 10% of CV estimate.  
- **Runtime (pilot):** CV+Tuning end‑to‑end < reasonable budget on CPU (documented).

---

## Global Evaluation & Reporting

### Core Metrics
- **Directional quality:** precision/recall/F1 on ±1 classes at operating θ.  
- **Probability quality:** Brier score, calibration curve slope.  
- **Economic:** expectancy, win rate, average PnL per trade, max drawdown.  
- **Trade profile:** trades/ticker/day distribution; micro‑trade share; holding‑time distribution.  
- **Latency:** p95 feature+inference runtime per cut.

### Dashboards (generated from artefacts)
- CV fold table, WFO timeline, operating‑point sweep (θ, λ), trade‑rate vs. precision.  
- Per‑ticker stability: KPI variance across tickers and months.  
- Post‑trade outcome histograms by time‑of‑day buckets.

---

## Reproducibility & Hashing

Integrate the hash functions into all artefacts:
- **Data:** `intraday_ml_get_data_hash(symbols, dates, vendor)` in dataset manifests.  
- **Features:** `intraday_ml_get_features_hash(df, pack_config)` stored with feature datasets.  
- **Targets/Labels:** include horizons, k_ATR in a `targets_hash`.  
- **Models:** embed all upstream hashes in model metadata; emit `model_card.json`.  
- **Backtests:** `intraday_ml_get_backtest_hash` included in run manifests for audits.

**Impact if not used:** you lose provenance and can’t prove two runs are comparable; caching is weakened; regression triage becomes guesswork.

---

## Acceptance Checklists

### Per‑Sprint DoD
- New files only under allowed `extensions/**`, `configs/**`, `docs/**`, `tests/**` paths.  
- Unit + property + integration tests pass.  
- Hashes written to artefacts.  
- Docs updated (catalog, labels, model card, CV config).

### Global DoD
- End‑to‑end ML path runs for a pilot universe with CV + tuned thresholds.  
- Trade‑rate shaping produces median trades/ticker/day in [0.5, 3.0] without hard caps.  
- Next‑bar execution and EOD flatness verified in weekly replays.  
- Reproducibility: rerunning the same config yields identical hashes and near‑identical KPIs.

---

## KPIs (Pilot Targets)
- **Precision@θ (±1):** ≥ 0.60 on OOS for at least one horizon.  
- **Abstain rate:** 40–80% (fewer, higher‑quality trades).  
- **Median trades/ticker/day:** 0.5–3.0 without hard caps.  
- **Holding time median:** 20–90 minutes; micro‑trades < 10%.  
- **Expectancy:** positive after fees/slippage; drawdown within risk budget.  
- **Calibration:** Brier score improved vs. uncalibrated baseline by ≥ 10%.

---

## Runbooks (Pilot)

- **Dataset build:** read Gold via `qx_data.gold_loader`, apply universe filters from `universe.yaml`, compute cuts from `cuts.yaml`, write `data_hash` manifest.  
- **Feature build:** run `feature_pack.py` per `features.yaml`, validate registry, write `features_hash`.  
- **Label build:** run `labeling.py` with `targets.yaml`, assert no‑peek, write `targets_hash`.  
- **Training:** run `train_lgbm.py` with `model_lgbm.yaml`, calibrate probs, emit `model_card.json` with upstream hashes.  
- **CV & tuning:** run `cv_runner.py` + `tune_lgbm.py` with `cv.yaml`, output operating thresholds (θ, λ, cooldown).  
- **Policy evaluation:** evaluate decision policy at tuned operating point; verify trade‑rate KPIs.

---

## Notes on Model Choice
- **LightGBM first.** It’s fast on CPU, robust for tabular features, and yields calibrated probabilities for decision policies that shape trade frequency without hard caps.  
- **N‑HiTS later.** Useful to forecast ranges or multi‑horizon paths; integrate once LightGBM baselines are stable.

---

## Risk & Compliance
- Enforce **no forward look** and **next‑bar execution** in unit tests and E2E replays.  
- Ensure **flat EOD** via policy and test assertions.  
- CI: path‑guard, duplicate‑API guard, synthetic‑data guard, IO guard.  
- Logs: structured and minimal; attach hashes to every artefact.
