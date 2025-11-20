# Intraday ML Pipeline

This document describes the new, streamlined pipeline for intraday ML experiments.

## Overview

The new pipeline is designed to be a single, production-grade pipeline that operates entirely within the `extensions/intraday_ml*` namespace. It is a config-driven pipeline that can be run with a single command.

## Canonical Command

The pipeline is run using the `run_phaseA_pipeline.py` script:

```bash
python run_phaseA_pipeline.py --config /path/to/your/master_config.yaml
```

- `--config`: Path to the master YAML config file (required for anything beyond the single-symbol BAC pilot).
- `--symbol`: (Optional) Force a single-symbol run independent of whatever the master config declares. When provided it overrides both the training and deployment symbol lists described below.

## Configuration

The pipeline is configured using a master YAML file that includes other configuration files for different parts of the pipeline. The master config specifies the paths to the following configuration files:

- `universe`: Defines the symbols to be used in the experiment.
- `splits`: Defines the train, test, and OOS (out-of-sample) date ranges.
- `cuts`: Defines the time-of-day cuts for signal generation.
- `features`: Defines the features to be used for training.
- `targets`: Defines the target variable for the model.
- `model`: Defines the model to be used for training.
- `cv`: Defines the cross-validation strategy.
- `policy`: Defines the decision policy for generating orders.

The policy configuration supports optional strategy-aware gating. Set
`enabled_strategies` to a list containing any of `momentum`, `pullback`,
`value_rotation`, or `sweep_reversion` to require the corresponding
feature-backed checks before an order is submitted. When omitted the
decision policy falls back to probability/conviction gating only, keeping
the ML flow independent from non-ML strategy implementations.

### Training vs Deployment Symbol Lists

The master config can now specify separate symbol cohorts for fitting the
model and for generating OOS orders:

```yaml
training_symbols: ["TTD", "BKR", "BALL", "USB", "GIS"]
deployment_symbols: ["GIS", "LYB", "EXC"]
```

- `training_symbols` controls which symbols are pulled into the aligned training window and calibration stats.
- `deployment_symbols` controls which symbols appear in the OOS feature set and policy/backtest run.

Both lists must remain a subset of the universe emitted by the screener. The pipeline validates this immediately after manifest creation and raises a descriptive error if any requested symbol was screened out (e.g., because of price/volume filters). Omitting either key defaults to using the manifest symbols for that cohort.

> Tip: `configs/extensions/intraday_ml/phaseA_multi_ticker.yaml` showcases a ready-to-run multi-ticker configuration that trains on five names and deploys to three.

### Dynamic Risk and Targets

The policy `risk` block controls per-trade stops and targets. At entry time the
decision policy places the stop below (for longs) or above (for shorts) the
configured support/resistance column and enforces a maximum ATR-based distance.
Take profit is set to at least 1.5R off the computed risk. Example:

```yaml
policy:
  risk:
    atr_feature: "f__vol__atr_6"
    support_feature_long: "low"
    resistance_feature_short: "high"
    max_atr_multiple: 1.25
    support_buffer_atr: 0.1
    target_r_multiple: 1.6
```

If the structural level is missing the policy falls back to the ATR guardrail
when `allow_missing_support` (default true) is enabled; otherwise it rejects the
trade. Metadata such as `risk_stop_price`, `risk_take_profit_price`, and
`risk_r_multiple` are written onto each generated order for downstream analysis.

## Artifacts

The pipeline produces a set of artifacts in the directory specified in the master config (`artifacts_dir`). The artifacts include:

- `manifest.json`: A JSON file containing the manifest for the dataset.
- `training_data.parquet`: A parquet file with the aligned training data.
- `model_lgbm/`: A directory containing the trained LightGBM model.
- `cv_report.json`: A JSON file with the cross-validation report.
- `oos_features.parquet`: A parquet file with the out-of-sample features.
- `oos_predictions.parquet`: A parquet file with the out-of-sample predictions.
- `oos_orders.parquet`: A parquet file with the generated orders.
- `oos_rejections.parquet`: A parquet file with the rejected signals and the reasons for rejection.
- `policy_config.json`: A JSON file with the policy configuration.
- `phaseA_status.json`: Summary of the run, including manifest/training/deployment symbol lists and effective train/validation/OOS ranges. This replaces the legacy BAC-only status stub.

## SIP Preparation Workflow

To run Phase A with the SIP-filtered USD 5–50 universe you must first build the universe YAML and then pre-compute the SIP membership for the covered dates. Follow these steps before every full (`phaseA_sip_full.yaml` or similar) command:

1. **Generate the USD 5–50 universe YAML.** This script inspects the gold store, enforces median price/dollar-v volume requirements, and writes a config that Phase A can consume. Run it from the repo root:

   ```bash
   python scripts/build_intraday_universe_sip_5_50.py \
     --output configs/extensions/intraday_ml/ \
     --min-price 5.0 \
     --max-price 50.0 \
     --min-dollar-vol 10000000
   ```

   The script creates `configs/extensions/intraday/ml/universe_intraday_sip_5_50.yaml` (or overwrites it if it already exists). You can add `--sip-symbols /path/to/list.txt` to restrict to top symbols from another source.

2. **Compute SIP membership.** The membership CLI writes daily parquet partitions under `/home/jacobw/quantstack/run/sip_membership`. Invoke it with the same universe produced above so SIP membership aligns with the target cohort:

   ```bash
   python -m extensions.intraday_ml.cli_build_sip_membership \
     --start-date 2023-10-02 \
     --end-date 2024-05-31 \
     --universe-config configs/extensions/intraday_ml/universe_intraday_sip_5_50.yaml \
     --gold-root /home/jacobw/gcs-mount/gold \
     --top-k 50 \
     --external-premarket-root /home/jacobw/gcs-mount/gold/intraday_ml/sip_universe_pre \
     --output-root /home/jacobw/quantstack/run/sip_membership \
     --mode legacy
   ```

   The `--external-premarket-root` flag points the SIP selector at the Russell 2000 USD 5–50 premarket shortlists; it defaults to the same `/home/jacobw/gcs-mount/gold/intraday_ml/sip_universe_pre` directory when omitted. `--output-root` controls where the membership parquet partitions are written (Phase A defaults to `/home/jacobw/quantstack/run/sip_membership`). Adjust `--top-k` (default 50) and `--mode` (`legacy` today) to match the pipeline’s crown (the Phase A config uses `sip_only` down-stream when filtering symbols). This step must run whenever the universe or gold window changes; the generated membership file is referenced directly by `phaseA_sip_full.yaml`.

3. **Run Phase A.** With the universe and membership in place, execute the pipeline as usual:

   ```bash
   python run_phaseA_pipeline.py --config configs/extensions/intraday_ml/phaseA_sip_full.yaml
   ```

   The master config references both the new universe file and the membership directory, so rerunning the script with any updated universe/membership simply picks up the latest files. Failure to generate the membership file will raise `RuntimeError: No deployment symbols available after applying SIP filtering`.

## Reproducibility

The pipeline is designed to be reproducible. The artifacts directory contains all the information needed to reproduce an experiment, including the configuration files, the model, and the data.
