# Intraday ML Pipeline

This document describes the new, streamlined pipeline for intraday ML experiments.

## Overview

The new pipeline is designed to be a single, production-grade pipeline that operates entirely within the `extensions/intraday_ml*` namespace. It is a config-driven pipeline that can be run with a single command.

## Canonical Command

The pipeline is run using the `run_phaseA_pipeline.py` script:

```bash
python run_phaseA_pipeline.py --config /path/to/your/master_config.yaml --symbol YOUR_SYMBOL
```

- `--config`: Path to the master YAML config file.
- `--symbol`: (Optional) Override the symbol to run for.

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

## Reproducibility

The pipeline is designed to be reproducible. The artifacts directory contains all the information needed to reproduce an experiment, including the configuration files, the model, and the data.
