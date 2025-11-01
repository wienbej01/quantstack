#!/usr/bin/env python3
"""
Phase A Complete Pipeline Runner
Executes all 6 steps for BAC single-ticker pilot test
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

from extensions.intraday_ml.data_prep import create_training_dataset

# Import ML modules
from extensions.intraday_ml.dataset_manifest import DatasetManifestBuilder
from extensions.intraday_ml_models.cv_runner import TimeSeriesCVRunner
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer


def main():
    """Run complete Phase A pipeline."""
    parser = argparse.ArgumentParser(description="Run complete Phase A pipeline.")
    parser.add_argument('--config', type=str, help='Path to master YAML config file.')
    parser.add_argument('--symbol', type=str, help='Override symbol to run for.')
    args = parser.parse_args()

    print("🚀 Intraday ML Pipeline")
    print("=" * 60)

    # Load master config if provided
    master_config = {}
    if args.config:
        with open(args.config) as f:
            master_config = yaml.safe_load(f)

    # Setup paths
    artifact_dir = Path(master_config.get('artifacts', 'artefacts/extensions/intraday_ml/phaseA'))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    print(f"   Artifacts will be saved to: {artifact_dir}")

    try:
        # Load all configurations
        print("📋 Loading configurations...")
        configs = {}
        if args.config:
            print(f"   Master config: {args.config}")
            for name, path in master_config.get('includes', {}).items():
                with open(path) as f:
                    configs[name] = yaml.safe_load(f)
                print(f"✅ {name}: {path}")
        else:
            # Fallback to default hardcoded configs if --config is not provided
            print("   Using default hardcoded configs.")
            config_files = {
                'universe': 'configs/extensions/intraday_ml/universe_single.yaml',
                'splits': 'configs/extensions/intraday_ml/splits_pilot.yaml',
                'cuts': 'configs/extensions/intraday_ml/cuts_10m.yaml',
                'features': 'configs/extensions/intraday_ml/features_10m.yaml',
                'targets': 'configs/extensions/intraday_ml/targets_loose.yaml',
                'model': 'configs/extensions/intraday_ml/model_lgbm_loose.yaml',
                'cv': 'configs/extensions/intraday_ml/cv/phaseA.yaml'
            }
            for name, path in config_files.items():
                with open(path) as f:
                    configs[name] = yaml.safe_load(f)
                print(f"✅ {name}: {path}")
        
        # Symbol override
        if args.symbol:
            print(f"   Symbol override: {args.symbol}")
            configs['universe']['symbols'] = [args.symbol]

        # Data loader config
        data_loader_config = master_config.get('data', {})
        data_loader_config.setdefault('root', '/home/jacobw/gcs-mount/gold')
        data_loader_config.setdefault('validate', True)
        data_loader_config.setdefault('sort', True)


        # Step 1: Build Dataset Manifest
        print("\n🔧 Step 1: Building dataset manifest...")
        
        # Ensure dates are strings
        for split in configs['splits']:
            if 'start' in configs['splits'][split]:
                configs['splits'][split]['start'] = str(configs['splits'][split]['start'])
            if 'end' in configs['splits'][split]:
                configs['splits'][split]['end'] = str(configs['splits'][split]['end'])
        
        print(f"   Splits config after conversion: {configs['splits']}")

        builder = DatasetManifestBuilder(
            gold_root='/home/jacobw/gcs-mount/gold',
            universe_config=configs['universe'],
            cuts_config=configs['cuts'],
            splits_config=configs['splits']
        )
        manifest_path = artifact_dir / 'manifest.json'
        manifest = builder.build_manifest(
            candidate_symbols=configs['universe'].get('symbols', ['BAC']),
            output_path=manifest_path
        )
        print(f"✅ Manifest created: {manifest_path}")
        print(f"   Symbols: {manifest.symbols}")
        print(f"   Total days: {manifest.total_days}")

        # Step 2: Data Preparation (Features + Labels using sliding window)
        print("\n🔧 Step 2: Data preparation with aligned features and labels...")

        # Generate date list from splits config for training data
        from datetime import datetime, timedelta
        train_dates = configs['splits']['train']
        start_date = datetime.strptime(train_dates['start'], '%Y-%m-%d')
        end_date = datetime.strptime(train_dates['end'], '%Y-%m-%d')

        # We need additional future data for label computation
        # Add buffer period after training end for labeling horizons
        label_buffer_days = 7  # Add 7 days for label horizons
        extended_end_date = end_date + timedelta(days=label_buffer_days)

        # Create training dataset using the new sliding window approach
        training_data_path = artifact_dir / 'training_data.parquet'

        training_data = create_training_dataset(
            symbols=manifest.symbols,
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=extended_end_date.strftime('%Y-%m-%d'),
            features_config=configs['features'],
            targets_config=configs['targets'],
            data_loader_config=data_loader_config
        )

        # Check if we got any data
        if training_data.empty:
            print("❌ No training data generated. Check data availability and configurations.")
            return 1

        # Filter to training period only (exclude label buffer period)
        if 'ts' in training_data.columns:
            training_data = training_data[training_data['ts'] <= pd.Timestamp(end_date)]
        else:
            print(f"❌ Training data missing 'ts' column. Columns: {list(training_data.columns)}")
            return 1

        # Save the aligned training data
        training_data.to_parquet(training_data_path)
        print(f"✅ Aligned training data created: {training_data_path}")
        print(f"   Shape: {training_data.shape}")
        print(f"   Features: {len([col for col in training_data.columns if col.startswith('f__')])}")
        print(f"   Label distribution: {training_data['label'].value_counts().to_dict()}")

        # Step 3: Train LightGBM Model
        print("\n🔧 Step 3: Training LightGBM model...")
        trainer = LightGBMTrainer(configs['model'])
        model_dir = artifact_dir / 'model_lgbm'
        model_dir.mkdir(parents=True, exist_ok=True)

        # Separate features and labels from the aligned training data
        feature_columns = [col for col in training_data.columns if col.startswith('f__')]
        features_df = training_data[feature_columns]
        labels_series = training_data['label']

        # For now, use all data for training (no validation split)
        # Generate simple hashes for reproducibility
        features_hash = hash(str(features_df.shape))
        targets_hash = hash(str(labels_series.value_counts().to_dict()))

        result = trainer.train_model(
            features=features_df,
            labels=labels_series,
            features_hash=str(features_hash),
            targets_hash=str(targets_hash)
        )

        # Save model
        import joblib
        joblib.dump(result.model, model_dir / 'model.pkl')
        print(f"✅ Model trained: {model_dir}")

        # Step 4: Cross-Validation
        if master_config.get("run_cv", True):
            print("\n🔧 Step 4: Running cross-validation...")
            cv_runner = TimeSeriesCVRunner(configs['cv'])
            cv_report_path = artifact_dir / 'cv_report.json'
            
            # Load training data for CV
            training_data_for_cv = pd.read_parquet(training_data_path)
            training_data_for_cv = training_data_for_cv.set_index(['symbol', 'ts'])
            features_for_cv = training_data_for_cv[[col for col in training_data_for_cv.columns if col.startswith('f__')]]
            labels_for_cv = training_data_for_cv['label']

            cv_result = cv_runner.run_cv(
                features=features_for_cv,
                labels=labels_for_cv,
                model_trainer=trainer,
                model_config=configs['model']
            )
            cv_runner.save_cv_results(cv_result, cv_report_path)
            print(f"✅ Cross-validation completed: {cv_report_path}")
        else:
            print("\nSkipping cross-validation.")

        # Step 5: Generate and persist OOS feature set
        print("\n🔧 Step 5: Generating OOS feature set...")
        oos_dates = configs['splits']['oos']
        oos_start_date = datetime.strptime(oos_dates['start'], '%Y-%m-%d')
        oos_end_date = datetime.strptime(oos_dates['end'], '%Y-%m-%d')

        oos_data = create_training_dataset(
            symbols=manifest.symbols,
            start_date=oos_start_date.strftime('%Y-%m-%d'),
            end_date=oos_end_date.strftime('%Y-%m-%d'),
            features_config=configs['features'],
            targets_config=configs['targets'],
            data_loader_config=data_loader_config,
            include_ohlcv=True
        )

        if oos_data.empty:
            print("❌ No OOS data generated. Check data availability and configurations.")
            return 1

        oos_feature_path = artifact_dir / 'oos_features.parquet'
        oos_data.to_parquet(oos_feature_path)
        print(f"✅ OOS features created: {oos_feature_path}")
        print(f"   Shape: {oos_data.shape}")

        # Step 6: Generate OOS predictions
        print("\n🔧 Step 6: Generating OOS predictions...")
        import joblib
        model = joblib.load(model_dir / 'model.pkl')

        oos_feature_columns = [col for col in oos_data.columns if col.startswith('f__')]
        oos_features = oos_data[oos_feature_columns]

        oos_predictions = model.predict_proba(oos_features)
        oos_predictions_df = pd.DataFrame(oos_predictions, columns=[f'prob_c{i}' for i in range(oos_predictions.shape[1])])
        oos_predictions_df['ts'] = oos_data['ts']
        oos_predictions_df['symbol'] = oos_data['symbol']

        oos_predictions_path = artifact_dir / 'oos_predictions.parquet'
        oos_predictions_df.to_parquet(oos_predictions_path)
        print(f"✅ OOS predictions created: {oos_predictions_path}")
        print(f"   Shape: {oos_predictions_df.shape}")

        # Print OOS data columns for debugging
        print(f"   OOS data columns: {list(oos_data.columns)}")

        # Step 7: Generate Orders from OOS Predictions
        print("\n🔧 Step 7: Generating orders from OOS predictions...")
        from extensions.intraday_ml_policies.intraday_ml_decision_policy import (
            IntradayMLDecisionPolicy,
        )

        # Define policy config
        policy_config = {
            "prob_threshold_long": master_config.get("policy", {}).get("prob_threshold_long", 0.55),
            "prob_threshold_short": master_config.get("policy", {}).get("prob_threshold_short", 0.55),
            "cooldown_minutes": master_config.get("policy", {}).get("cooldown_minutes", 30),
            "min_time": master_config.get("policy", {}).get("min_time", "09:45:00"),
            "max_time": master_config.get("policy", {}).get("max_time", "15:45:00"),
            "stop_loss_pct": master_config.get("policy", {}).get("stop_loss_pct", 0.01),
            "take_profit_pct": master_config.get("policy", {}).get("take_profit_pct", 0.015),
            "order_qty": master_config.get("policy", {}).get("order_qty", 1),
        }
        
        policy = IntradayMLDecisionPolicy(policy_config)

        # Rename prediction columns for policy
        oos_predictions_df = oos_predictions_df.rename(columns={'prob_c0': 'prob_short', 'prob_c2': 'prob_long'})

        # Process signals
        orders_df, rejections_df = policy.process_signals(oos_predictions_df)

        # Save orders and rejections
        orders_path = artifact_dir / 'oos_orders.parquet'
        rejections_path = artifact_dir / 'oos_rejections.parquet'
        orders_df.to_parquet(orders_path)
        rejections_df.to_parquet(rejections_path)

        print(f"✅ Orders generated: {orders_path}")
        print(f"   Total orders: {len(orders_df)}")
        print(f"✅ Rejections logged: {rejections_path}")
        print(f"   Total rejections: {len(rejections_df)}")

        # Save policy config for reproducibility
        policy_config_path = artifact_dir / 'policy_config.json'
        with open(policy_config_path, 'w') as f:
            json.dump(policy_config, f, indent=2)
        print(f"✅ Policy config saved: {policy_config_path}")

        # Step 8: Run Backtest
        print("\n🔧 Step 8: Running backtest...")
        from extensions.intraday_ml.backtest import intraday_ml_run_backtest
        
        backtest_config = master_config.get("backtest", {})
        backtest_config["artifacts_path"] = str(artifact_dir)
        backtest_artifacts = intraday_ml_run_backtest(
            bars=oos_data,
            orders=orders_df,
            cfg=backtest_config
        )
        
        print("✅ Backtest completed.")
        if "metrics" in backtest_artifacts:
            print("   Metrics:")
            for k, v in backtest_artifacts["metrics"].items():
                print(f"     - {k}: {v}")


        # Summary
        print("\n🎉 Phase A Pipeline Completed Successfully!")
        print("=" * 60)
        print("📊 Generated Artifacts:")
        for artifact in artifact_dir.glob("*"):
            size_mb = artifact.stat().st_size / (1024*1024) if artifact.is_file() else 0
            print(f"   - {artifact.name} ({size_mb:.1f} MB)")

        print("\n📋 Phase A Summary:")
        print("   - Ticker: BAC")
        print(f"   - Train: {train_dates['start']} to {train_dates['end']}")
        print("   - Validation: 2024-01-01 to 2024-01-31")
        print("   - OOS: 2024-02-01 to 2024-02-29")
        print("   - Data: Aligned features+labels via sliding window")
        print("   - Model: LightGBM tri-class + calibration")
        print("   - CV: 3-fold purged/embargoed")

        return 0

    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())