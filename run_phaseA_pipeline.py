#!/usr/bin/env python3
"""
Phase A Complete Pipeline Runner
Executes all 6 steps for BAC single-ticker pilot test
"""

import argparse
import json
import sys
from pathlib import Path

from datetime import datetime, timezone

import pandas as pd
import yaml

from extensions.intraday_ml.data_prep import create_training_dataset

# Import ML modules
from extensions.intraday_ml.dataset_manifest import DatasetManifestBuilder
from extensions.intraday_ml_models.cv_runner import TimeSeriesCVRunner
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer
from extensions.intraday_ml_policies.calibration import compute_policy_calibration_stats
from typing import Any
from extensions.intraday_ml.reporting import (
    build_run_summary,
    summarize_round_trip_trades,
    write_run_summary,
    write_trade_report,
)
from extensions.intraday_ml.sip_membership import get_phase_symbols_with_sip


def _summarize_feature_coverage(
    training_df: pd.DataFrame,
    oos_df: pd.DataFrame,
    feature_columns: list[str],
    artifact_dir: Path,
) -> Path | None:
    """Compute simple feature coverage stats for train vs OOS datasets."""

    if training_df.empty or oos_df.empty:
        return None

    available_columns = [
        col for col in feature_columns if col in training_df.columns and col in oos_df.columns
    ]
    if not available_columns:
        return None

    coverage_records = []
    for col in available_columns:
        train_non_null = 1.0 - training_df[col].isna().mean()
        oos_non_null = 1.0 - oos_df[col].isna().mean()
        coverage_records.append(
            {
                "feature": col,
                "train_non_null": float(train_non_null),
                "oos_non_null": float(oos_non_null),
                "abs_gap": float(abs(train_non_null - oos_non_null)),
            }
        )

    coverage_df = pd.DataFrame(coverage_records).sort_values("oos_non_null")
    coverage_path = artifact_dir / "feature_coverage.csv"
    coverage_df.to_csv(coverage_path, index=False)

    low_coverage = coverage_df.nsmallest(5, "oos_non_null")
    if not low_coverage.empty:
        print("   Feature coverage (lowest OOS non-null ratios):")
        for _, row in low_coverage.iterrows():
            print(
                f"     - {row['feature']}: train={row['train_non_null']:.3f}, "
                f"oos={row['oos_non_null']:.3f}"
            )

    return coverage_path


def main():
    """Run complete Phase A pipeline."""
    parser = argparse.ArgumentParser(description="Run complete Phase A pipeline.")
    parser.add_argument("--config", type=str, help="Path to master YAML config file.")
    parser.add_argument("--symbol", type=str, help="Override symbol to run for.")
    args = parser.parse_args()

    print("🚀 Intraday ML Pipeline")
    print("=" * 60)

    # Load master config if provided
    master_config = {}
    if args.config:
        with open(args.config) as f:
            master_config = yaml.safe_load(f)

    # Setup paths
    artifact_dir = Path(master_config.get("artifacts", "artefacts/extensions/intraday_ml/phaseA"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    print(f"   Artifacts will be saved to: {artifact_dir}")

    try:
        # Load all configurations
        print("📋 Loading configurations...")
        configs = {}
        if args.config:
            print(f"   Master config: {args.config}")
            for name, path in master_config.get("includes", {}).items():
                with open(path) as f:
                    configs[name] = yaml.safe_load(f)
                print(f"✅ {name}: {path}")
        else:
            # Fallback to default hardcoded configs if --config is not provided
            print("   Using default hardcoded configs.")
            config_files = {
                "universe": "configs/extensions/intraday_ml/universe_single.yaml",
                "splits": "configs/extensions/intraday_ml/splits_pilot.yaml",
                "cuts": "configs/extensions/intraday_ml/cuts_10m.yaml",
                "features": "configs/extensions/intraday_ml/features_10m.yaml",
                "targets": "configs/extensions/intraday_ml/targets_loose.yaml",
                "model": "configs/extensions/intraday_ml/model_lgbm_loose.yaml",
                "cv": "configs/extensions/intraday_ml/cv/phaseA.yaml",
            }
            for name, path in config_files.items():
                with open(path) as f:
                    configs[name] = yaml.safe_load(f)
                print(f"✅ {name}: {path}")

        # Symbol override
        if args.symbol:
            print(f"   Symbol override: {args.symbol}")
            configs["universe"]["symbols"] = [args.symbol]

        policy_section = master_config.get("policy", {})
        session_timezone = policy_section.get("session_timezone", "America/New_York")
        policy_calibration_cfg = dict(policy_section.get("calibration", {}))
        calibration_stats_path: Path | None = None

        # Data loader config
        data_loader_config = master_config.get("data", {})
        data_loader_config.setdefault("root", "/home/jacobw/gcs-mount/gold")
        data_loader_config.setdefault("validate", True)
        data_loader_config.setdefault("sort", True)
        
        # SIP filter config
        sip_config = master_config.get("sip_filter", {"enabled": False})


        # Step 1: Build Dataset Manifest
        print("\n🔧 Step 1: Building dataset manifest...")

        # Ensure dates are strings
        for split in configs["splits"]:
            if "start" in configs["splits"][split]:
                configs["splits"][split]["start"] = str(configs["splits"][split]["start"])
            if "end" in configs["splits"][split]:
                configs["splits"][split]["end"] = str(configs["splits"][split]["end"])

        print(f"   Splits config after conversion: {configs['splits']}")

        builder = DatasetManifestBuilder(
            gold_root="/home/jacobw/gcs-mount/gold",
            universe_config=configs["universe"],
            cuts_config=configs["cuts"],
            splits_config=configs["splits"],
        )
        manifest_path = artifact_dir / "manifest.json"
        candidate_symbols = configs["universe"].get("symbols", ["BAC"])
        manifest = builder.build_manifest(
            candidate_symbols=candidate_symbols,
            output_path=manifest_path,
        )
        print(f"✅ Manifest created: {manifest_path}")
        print(f"   Symbols: {manifest.symbols}")
        print(f"   Total days: {manifest.total_days}")

        available_symbols = sorted({str(symbol).upper() for symbol in manifest.symbols})

        def _normalize_symbols(symbols: list[str]) -> list[str]:
            return sorted({str(symbol).upper() for symbol in symbols})

        training_symbols_cfg = master_config.get("training_symbols")
        deployment_symbols_cfg = master_config.get("deployment_symbols")

        if training_symbols_cfg:
            training_symbols = _normalize_symbols(training_symbols_cfg)
        else:
            training_symbols = available_symbols.copy()

        if deployment_symbols_cfg:
            deployment_symbols = _normalize_symbols(deployment_symbols_cfg)
        else:
            deployment_symbols = available_symbols.copy()

        if args.symbol:
            override_symbol = str(args.symbol).upper()
            training_symbols = [override_symbol]
            deployment_symbols = [override_symbol]

        missing_training = sorted(set(training_symbols) - set(available_symbols))
        missing_deployment = sorted(set(deployment_symbols) - set(available_symbols))
        if missing_training:
            raise RuntimeError(
                "Training symbols missing from manifest: "
                + ", ".join(missing_training)
                + ". Check universe configuration."
            )
        if missing_deployment:
            raise RuntimeError(
                "Deployment symbols missing from manifest: "
                + ", ".join(missing_deployment)
                + ". Check universe configuration."
            )

        print(f"   Initial training symbols: {training_symbols}")
        print(f"   Initial deployment symbols: {deployment_symbols}")

        # Apply SIP filtering if enabled
        sip_log = lambda message: print(f"   {message}")
        training_symbols = get_phase_symbols_with_sip(
            splits_config=configs["splits"],
            sip_config=sip_config,
            candidate_symbols=training_symbols,
            phase="train",
            log_fn=sip_log,
        )
        deployment_symbols = get_phase_symbols_with_sip(
            splits_config=configs["splits"],
            sip_config=sip_config,
            candidate_symbols=deployment_symbols,
            phase="oos",
            log_fn=sip_log,
        )

        print(f"   Final training symbols: {training_symbols}")
        print(f"   Final deployment symbols: {deployment_symbols}")


        # Step 2: Data Preparation (Features + Labels using sliding window)
        print("\n🔧 Step 2: Data preparation with aligned features and labels...")

        # Generate date list from splits config for training data
        from datetime import datetime, timedelta

        train_dates = configs["splits"]["train"]
        start_date = datetime.strptime(train_dates["start"], "%Y-%m-%d")
        end_date = datetime.strptime(train_dates["end"], "%Y-%m-%d")

        # We need additional future data for label computation
        # Add buffer period after training end for labeling horizons
        label_buffer_days = 7  # Add 7 days for label horizons
        extended_end_date = end_date + timedelta(days=label_buffer_days)

        # Create training dataset using the new sliding window approach
        training_data_path = artifact_dir / "training_data.parquet"

        training_data = create_training_dataset(
            symbols=training_symbols,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=extended_end_date.strftime("%Y-%m-%d"),
            features_config=configs["features"],
            targets_config=configs["targets"],
            data_loader_config=data_loader_config,
            include_ohlcv=True,
        )

        # Check if we got any data
        if training_data.empty:
            print("❌ No training data generated. Check data availability and configurations.")
            return 1

        # Filter to training period only (exclude label buffer period)
        if "ts" in training_data.columns:
            training_data = training_data[training_data["ts"] <= pd.Timestamp(end_date)]
        else:
            print(f"❌ Training data missing 'ts' column. Columns: {list(training_data.columns)}")
            return 1

        # Save the aligned training data
        training_data.to_parquet(training_data_path)
        print(f"✅ Aligned training data created: {training_data_path}")
        print(f"   Shape: {training_data.shape}")
        print(
            f"   Features: {len([col for col in training_data.columns if col.startswith('f__')])}"
        )
        print(f"   Label distribution: {training_data['label'].value_counts().to_dict()}")

        # Step 3: Train LightGBM Model
        print("\n🔧 Step 3: Training LightGBM model...")
        trainer = LightGBMTrainer(configs["model"])
        model_dir = artifact_dir / "model_lgbm"
        model_dir.mkdir(parents=True, exist_ok=True)

        # Separate features and labels from the aligned training data
        feature_columns = [col for col in training_data.columns if col.startswith("f__")]
        features_df = training_data[feature_columns]
        labels_series = training_data["label"]

        # For now, use all data for training (no validation split)
        # Generate simple hashes for reproducibility
        features_hash = hash(str(features_df.shape))
        targets_hash = hash(str(labels_series.value_counts().to_dict()))

        result = trainer.train_model(
            features=features_df,
            labels=labels_series,
            features_hash=str(features_hash),
            targets_hash=str(targets_hash),
        )

        if policy_calibration_cfg.get("enabled", True):
            calibration_stats = compute_policy_calibration_stats(
                model=result.model,
                data=training_data,
                feature_columns=feature_columns,
                calibration_config=policy_calibration_cfg,
            )
            stats_filename = policy_calibration_cfg.get("stats_filename", "policy_calibration.json")
            calibration_stats_path = artifact_dir / stats_filename
            with open(calibration_stats_path, "w") as f:
                json.dump(calibration_stats, f, indent=2)
            print(f"✅ Policy calibration stats saved: {calibration_stats_path}")

        # Save model
        import joblib

        joblib.dump(result.model, model_dir / "model.pkl")
        print(f"✅ Model trained: {model_dir}")

        # Step 4: Cross-Validation
        if master_config.get("run_cv", True):
            print("\n🔧 Step 4: Running cross-validation...")
            cv_runner = TimeSeriesCVRunner(configs["cv"])
            cv_report_path = artifact_dir / "cv_report.json"

            # Load training data for CV
            training_data_for_cv = pd.read_parquet(training_data_path)
            training_data_for_cv = training_data_for_cv.set_index(["symbol", "ts"])
            features_for_cv = training_data_for_cv[
                [col for col in training_data_for_cv.columns if col.startswith("f__")]
            ]
            labels_for_cv = training_data_for_cv["label"]
            context_columns_for_cv = [
                column
                for column in ["open", "high", "low", "close", "volume"]
                if column in training_data_for_cv.columns
            ]
            context_data_for_cv = (
                training_data_for_cv[context_columns_for_cv]
                if context_columns_for_cv
                else None
            )

            cv_result = cv_runner.run_cv(
                features=features_for_cv,
                labels=labels_for_cv,
                model_trainer=trainer,
                model_config=configs["model"],
                context_data=context_data_for_cv,
            )
            cv_runner.save_cv_results(cv_result, cv_report_path)
            print(f"✅ Cross-validation completed: {cv_report_path}")
        else:
            print("\nSkipping cross-validation.")

        # Step 5: Generate and persist OOS feature set
        print("\n🔧 Step 5: Generating OOS feature set...")
        feature_coverage_path: Path | None = None
        oos_dates = configs["splits"]["oos"]
        oos_start_date = datetime.strptime(oos_dates["start"], "%Y-%m-%d")
        oos_end_date = datetime.strptime(oos_dates["end"], "%Y-%m-%d")

        oos_data = create_training_dataset(
            symbols=deployment_symbols,
            start_date=oos_start_date.strftime("%Y-%m-%d"),
            end_date=oos_end_date.strftime("%Y-%m-%d"),
            features_config=configs["features"],
            targets_config=configs["targets"],
            data_loader_config=data_loader_config,
            include_ohlcv=True,
        )

        if oos_data.empty:
            print("❌ No OOS data generated. Check data availability and configurations.")
            return 1

        # Normalize timestamps to UTC for downstream policy/backtest steps
        oos_data["ts"] = pd.to_datetime(oos_data["ts"], errors="raise")
        if oos_data["ts"].dt.tz is None:
            oos_data["ts"] = oos_data["ts"].dt.tz_localize(session_timezone)
        oos_data["ts"] = oos_data["ts"].dt.tz_convert("UTC")

        oos_feature_path = artifact_dir / "oos_features.parquet"
        oos_data.to_parquet(oos_feature_path)
        print(f"✅ OOS features created: {oos_feature_path}")
        print(f"   Shape: {oos_data.shape}")

        # Step 6: Generate OOS predictions
        print("\n🔧 Step 6: Generating OOS predictions...")
        import joblib

        model = joblib.load(model_dir / "model.pkl")

        oos_feature_columns = [col for col in oos_data.columns if col.startswith("f__")]
        oos_features = oos_data[oos_feature_columns]

        feature_coverage_path = _summarize_feature_coverage(
            training_data, oos_data, oos_feature_columns, artifact_dir
        )

        oos_predictions = model.predict_proba(oos_features)
        oos_predictions_df = pd.DataFrame(
            oos_predictions,
            columns=[f"prob_c{i}" for i in range(oos_predictions.shape[1])],
        )
        oos_predictions_df["ts"] = oos_data["ts"]
        oos_predictions_df["symbol"] = oos_data["symbol"]

        oos_predictions_path = artifact_dir / "oos_predictions.parquet"
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
            "prob_threshold_long": policy_section.get("prob_threshold_long", 0.55),
            "prob_threshold_short": policy_section.get("prob_threshold_short", 0.55),
            "cooldown_minutes": policy_section.get("cooldown_minutes", 30),
            "min_time": policy_section.get("min_time", "09:45:00"),
            "max_time": policy_section.get("max_time", "15:45:00"),
            "stop_loss_pct": policy_section.get("stop_loss_pct", 0.01),
            "take_profit_pct": policy_section.get("take_profit_pct", 0.015),
            "order_qty": policy_section.get("order_qty", 1),
            "exit_threshold_long": policy_section.get(
                "exit_threshold_long", policy_section.get("prob_threshold_long", 0.55)
            ),
            "exit_threshold_short": policy_section.get(
                "exit_threshold_short", policy_section.get("prob_threshold_short", 0.55)
            ),
            "max_hold_minutes": policy_section.get("max_hold_minutes", 60),
            "score_margin": policy_section.get("score_margin", 0.05),
            "min_directional_gap": policy_section.get("min_directional_gap", 0.05),
            "min_conviction_score": policy_section.get("min_conviction_score", 0.0),
            "max_entries_per_day": policy_section.get("max_entries_per_day"),
            "gap_exit_delay_minutes": policy_section.get("gap_exit_delay_minutes"),
            "session_timezone": session_timezone,
        }

        if "risk" in policy_section:
            policy_config["risk"] = policy_section["risk"]

        if policy_calibration_cfg:
            calibration_cfg_for_policy = dict(policy_calibration_cfg)
            stats_filename = calibration_cfg_for_policy.pop("stats_filename", None)
            if calibration_stats_path:
                calibration_cfg_for_policy["stats_path"] = str(calibration_stats_path)
            elif stats_filename:
                calibration_cfg_for_policy["stats_path"] = str(artifact_dir / stats_filename)
            if calibration_cfg_for_policy.get("enabled", True):
                policy_config["calibration"] = calibration_cfg_for_policy
        # Remove keys with None to keep config tidy
        policy_config = {k: v for k, v in policy_config.items() if v is not None}

        policy = IntradayMLDecisionPolicy(policy_config)

        # Rename prediction columns for policy
        oos_predictions_df = oos_predictions_df.rename(
            columns={
                "prob_c0": "prob_short",
                "prob_c1": "prob_neutral",
                "prob_c2": "prob_long",
            }
        )

        required_feature_columns = policy.get_required_feature_columns()
        merged_signals = oos_predictions_df
        if required_feature_columns:
            feature_columns = ["ts", "symbol"] + sorted(required_feature_columns)
            available_columns = [col for col in feature_columns if col in oos_data.columns]
            missing_cols = sorted(set(required_feature_columns) - set(oos_data.columns))
            if missing_cols:
                print(
                    "⚠️ Warning: Missing required feature columns for policy checks: "
                    + ", ".join(missing_cols)
                )
            if len(available_columns) >= 2:
                feature_frame = (
                    oos_data[available_columns]
                    .drop_duplicates(subset=["ts", "symbol"])
                    .reset_index(drop=True)
                )
                merged_signals = merged_signals.merge(
                    feature_frame,
                    on=["ts", "symbol"],
                    how="left",
                    validate="one_to_one",
                )

        # Process signals
        orders_df, rejections_df = policy.process_signals(merged_signals)

        # Save orders and rejections
        orders_path = artifact_dir / "oos_orders.parquet"
        rejections_path = artifact_dir / "oos_rejections.parquet"
        orders_df.to_parquet(orders_path)
        rejections_df.to_parquet(rejections_path)

        print(f"✅ Orders generated: {orders_path}")
        print(f"   Total orders: {len(orders_df)}")
        print(f"✅ Rejections logged: {rejections_path}")
        print(f"   Total rejections: {len(rejections_df)}")

        if not orders_df.empty:
            order_reason_counts = orders_df["reason"].value_counts().sort_values(ascending=False)
            print("   Order reasons:")
            for reason, count in order_reason_counts.items():
                print(f"     - {reason}: {count}")

        if not rejections_df.empty:
            rejection_counts = rejections_df["reason"].value_counts().sort_values(ascending=False)
            print("   Rejection reasons:")
            for reason, count in rejection_counts.items():
                print(f"     - {reason}: {count}")
            rejection_summary_path = artifact_dir / "rejection_summary.csv"
            rejection_counts.to_csv(rejection_summary_path, header=["count"])
            print(f"   Rejection summary saved: {rejection_summary_path}")
        else:
            print("   Rejection reasons: none")

        # Save policy config for reproducibility
        policy_config_path = artifact_dir / "policy_config.json"
        with open(policy_config_path, "w") as f:
            json.dump(policy_config, f, indent=2)
        print(f"✅ Policy config saved: {policy_config_path}")

        # Step 8: Run Backtest
        print("\n🔧 Step 8: Running backtest...")
        from extensions.intraday_ml.backtest import intraday_ml_run_backtest

        backtest_config = master_config.get("backtest", {})
        backtest_config["artifacts_path"] = str(artifact_dir)
        intraday_constraints = backtest_config.setdefault("intraday_constraints", {})
        intraday_constraints.setdefault("session_timezone", session_timezone)
        backtest_artifacts = intraday_ml_run_backtest(
            bars=oos_data, orders=orders_df, cfg=backtest_config
        )

        print("✅ Backtest completed.")
        metrics_dict = backtest_artifacts.get("metrics", {})
        if metrics_dict:
            print("   Metrics:")
            for k, v in metrics_dict.items():
                print(f"     - {k}: {v}")

        trade_orders_df = backtest_artifacts.get(
            "policy_orders", backtest_artifacts.get("orders")
        )
        trade_summary_df = summarize_round_trip_trades(
            backtest_artifacts.get("fills"), trade_orders_df
        )
        if not trade_summary_df.empty:
            trade_summary_path = artifact_dir / "trade_summary.parquet"
            trade_summary_df.to_parquet(trade_summary_path, index=False)
            trade_report_path = artifact_dir / "trade_summary.md"
            write_trade_report(trade_summary_df, trade_report_path, max_rows=50)
            print(
                f"   Trade summary saved: {trade_summary_path} "
                f"({len(trade_summary_df)} trades)"
            )
        else:
            print("   Trade summary: no completed trades")

        run_summary = build_run_summary(
            metrics=metrics_dict,
            orders_df=orders_df,
            rejections_df=rejections_df,
            policy_config=policy_config,
            artifacts_dir=artifact_dir,
            feature_coverage_path=feature_coverage_path,
            timestamp=datetime.now(timezone.utc),
        )
        write_run_summary(run_summary, artifact_dir / "pilot_report.json")

        # Summary
        print("\n🎉 Phase A Pipeline Completed Successfully!")
        print("=" * 60)
        print("📊 Generated Artifacts:")
        for artifact in artifact_dir.glob("*"):
            size_mb = artifact.stat().st_size / (1024 * 1024) if artifact.is_file() else 0
            print(f"   - {artifact.name} ({size_mb:.1f} MB)")

        print("\n📋 Phase A Summary:")
        print(f"   - Manifest symbols: {', '.join(available_symbols)}")
        print(f"   - Training symbols: {', '.join(training_symbols)}")
        print(f"   - Deployment symbols: {', '.join(deployment_symbols)}")
        print(f"   - Train: {train_dates['start']} to {train_dates['end']}")
        test_dates = configs["splits"].get("test", {})
        oos_split = configs["splits"].get("oos", {})

        def _format_range(split_cfg: dict[str, str] | None) -> str:
            if not split_cfg:
                return "n/a"
            start = split_cfg.get("start", "n/a")
            end = split_cfg.get("end", "n/a")
            return f"{start} to {end}"

        print(f"   - Validation: {_format_range(test_dates)}")
        print(f"   - OOS: {_format_range(oos_split)}")
        print("   - Data: Aligned features+labels via sliding window")
        print("   - Model: LightGBM tri-class")

        status_path = artifact_dir / "phaseA_status.json"
        phase_status = {
            "phase": "A",
            "manifest_symbols": available_symbols,
            "training_symbols": training_symbols,
            "deployment_symbols": deployment_symbols,
            "train_window": train_dates,
            "test_window": test_dates,
            "oos_window": oos_split,
        }
        with open(status_path, "w") as f:
            json.dump(phase_status, f, indent=2)
        print(f"   - Status file: {status_path}")

        cv_summary = "skipped"
        if master_config.get("run_cv", True):
            if "cv_result" in locals() and cv_result:
                executed_folds = len(cv_result.splits)
                method = cv_runner.validation_method.replace("_", " ")
                cv_summary = f"{executed_folds} fold(s) {method}"
            else:
                cv_summary = "configured but not executed"
        print(f"   - CV: {cv_summary}")

        total_trades = backtest_artifacts.get("metrics", {}).get("total_trades")
        if total_trades is not None:
            print(f"   - OOS trades: {total_trades}")

        return 0

    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
