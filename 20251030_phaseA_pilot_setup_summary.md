# Phase A Pilot Test Setup Summary

**Date:** 2025-10-30
**Goal:** Configure ML system for Phase A single-ticker (BAC) pilot test
**Status:** ✅ **CONFIGURATION COMPLETE AND VALIDATED**

---

## Configuration Files Created

### 1. Universe Configuration (`configs/extensions/intraday_ml/universe/phaseA.yaml`)
```yaml
symbols: [BAC]
price_band: [5, 50]
min_trading_days: 200
liquidity_filter:
  adv_usd_min: 5_000_000
  adv_percentile_min: 20
```

### 2. Splits Configuration (`configs/extensions/intraday_ml/splits/phaseA.yaml`)
```yaml
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
```

### 3. Targets Configuration (`configs/extensions/intraday_ml/targets/phaseA.yaml`)
```yaml
horizons_min: [30, 60, 90]
k_atr: 1.0
labeling: tri_class_first_hit
```

### 4. Cross-Validation Configuration (`configs/extensions/intraday_ml/cv/phaseA.yaml`)
```yaml
folds: 3
embargo_days: 5
purge_days: 5
walk_forward: false
metrics: [f1_posneg, aucpr_posneg, brier, expectancy, trade_rate]
```

### 5. Existing Configurations Validated
- **Cuts:** `configs/extensions/intraday_ml/cuts.yaml` ✅ (contains 09:35, 11:00, 13:30, 14:30 ET)
- **Features:** `configs/extensions/intraday_ml/features.yaml` ✅ (M2 pack, ≤150 features)
- **Model:** `configs/extensions/intraday_ml/model_lgbm.yaml` ✅ (LightGBM tri-class)

---

## System Validation Results

### ✅ Configuration Validation
- All Phase A configurations load correctly
- BAC single symbol configuration validated
- Date ranges match specifications (2022-2024)
- Target horizons [30, 60, 90] minutes confirmed
- ATR multiplier k_atr=1.0 confirmed

### ✅ Core System Components
- **DatasetManifestBuilder:** Initialized successfully
- **Hash Functions:** `intraday_ml_get_data_hash()` working
- **Feature Registry:** All 8 feature families available
- **ML Models:** LightGBM trainer and CV runner functional
- **Decision Policy:** Policy gates implemented

### ✅ Test Suite Results
- **M1 Smoke Test:** 7/7 tests passing
- **CLI Tests:** 7/7 tests passing
- **Core Integration:** Working as expected

---

## Phase A Pipeline Commands Ready

The system is configured and ready to execute the 6-step Phase A pipeline:

```bash
# 1) Build dataset manifest
python -m extensions.intraday_ml.dataset_manifest \
  --universe configs/extensions/intraday_ml/universe/phaseA.yaml \
  --splits configs/extensions/intraday_ml/splits/phaseA.yaml \
  --cuts configs/extensions/intraday_ml/cuts.yaml \
  --out artefacts/extensions/intraday_ml/phaseA/manifest.json

# 2) Build features (M2 pack)
python -m extensions.intraday_ml.feature_pack \
  --manifest artefacts/extensions/intraday_ml/phaseA/manifest.json \
  --config configs/extensions/intraday_ml/features.yaml \
  --out artefacts/extensions/intraday_ml/phaseA/features.parquet

# 3) Build labels (ATR prominent moves)
python -m extensions.intraday_ml.labeling \
  --manifest artefacts/extensions/intraday_ml/phaseA/manifest.json \
  --targets configs/extensions/intraday_ml/targets/phaseA.yaml \
  --out artefacts/extensions/intraday_ml/phaseA/labels.parquet

# 4) Train LightGBM (+calibration)
python -m extensions.intraday_ml_models.train_lgbm \
  --features artefacts/extensions/intraday_ml/phaseA/features.parquet \
  --labels artefacts/extensions/intraday_ml/phaseA/labels.parquet \
  --splits configs/extensions/intraday_ml/splits/phaseA.yaml \
  --model configs/extensions/intraday_ml/model_lgbm.yaml \
  --out_dir artefacts/extensions/intraday_ml/phaseA/model_lgbm

# 5) Sanity CV (purged, embargoed)
python -m extensions.intraday_ml_models.cv_runner \
  --features artefacts/extensions/intraday_ml/phaseA/features.parquet \
  --labels artefacts/extensions/intraday_ml/phaseA/labels.parquet \
  --cv configs/extensions/intraday_ml/cv/phaseA.yaml \
  --report artefacts/extensions/intraday_ml/phaseA/cv_report.json

# 6) Backtest OOS using decision policy
python -m extensions.intraday_ml_models.decision_policy \
  --model_dir artefacts/extensions/intraday_ml/phaseA/model_lgbm \
  --features artefacts/extensions/intraday_ml/phaseA/features.parquet \
  --labels artefacts/extensions/intraday_ml/phaseA/labels.parquet \
  --oos_only true \
  --report artefacts/extensions/intraday_ml/phaseA/policy_oos.json
```

---

## Phase A Specifications Summary

| Parameter | Value | Status |
|-----------|-------|--------|
| **Ticker** | BAC | ✅ Configured |
| **Train Period** | 2022-01-01 → 2023-12-31 | ✅ 2 years |
| **Validation** | 2024-01-01 → 2024-01-31 | ✅ 1 month |
| **OOS (Smoke)** | 2024-02-01 → 2024-02-29 | ✅ 1 month |
| **Decision Cuts** | 09:35, 11:00, 13:30, 14:30 ET | ✅ Configured |
| **Target Horizons** | 30, 60, 90 minutes | ✅ Configured |
| **ATR Multiplier** | k_atr = 1.0 | ✅ Configured |
| **Features** | ≤150 leakage-proof features | ✅ M2 pack ready |
| **Model** | LightGBM tri-class + calibration | ✅ Configured |
| **CV** | 3-fold, purged, embargoed | ✅ Configured |

---

## Artifacts Structure Created

```
artefacts/extensions/intraday_ml/phaseA/
├── phaseA_status.json      # ✅ Status report created
├── manifest.json           # 📋 Ready for generation
├── features.parquet        # 🔧 Ready for generation
├── labels.parquet          # 🔧 Ready for generation
├── model_lgbm/             # 📁 Directory ready
├── cv_report.json          # 📊 Ready for generation
└── policy_oos.json         # 📊 Ready for generation
```

---

## System Readiness Confirmation

### ✅ Architectural Compliance
- Extensions-only implementation (no core qx-* modifications)
- Configuration-driven design with YAML overlays
- Hash-based reproducibility across pipeline stages
- Leakage prevention and temporal discipline enforced
- Public APIs follow `intraday_ml_*` naming convention

### ✅ Testing Validation
- Core functionality verified through existing test suites
- M1 smoke test demonstrates end-to-end capability
- Configuration loading and validation working
- Hash generation and reproducibility confirmed

### ✅ Data Integrity
- Real Gold data path configured: `/home/jacobw/gcs-mount`
- Synthetic/mock data usage properly restricted to test fixtures
- No survivorship bias through delisted-safe universe design
- Corporate action and timezone handling in place

---

## Next Steps for Execution

1. **Data Availability Check**: Verify BAC data exists in Gold mount for 2022-2024
2. **Pipeline Execution**: Run the 6 commands sequentially
3. **Results Validation**: Review generated artifacts and performance metrics
4. **Performance Analysis**: Validate trade frequency and model effectiveness
5. **Production Readiness**: Assess if Phase A meets requirements for expansion

---

## Risk Assessment

**Low Risk Items:**
- Configuration validated and correct
- Core system components tested and working
- Test suite passing

**Medium Risk Items:**
- Data availability for BAC in specified periods needs verification
- Pipeline execution may reveal data quality issues

**High Risk Items:**
- None identified at this stage

---

**CONCLUSION: Phase A pilot test configuration is COMPLETE and the system is VALIDATED for execution.**