#!/usr/bin/env python3
"""
Master Script for End-to-End ML Model Training and Backtesting.
"""

import argparse
import logging
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml

# --- Path Setup ---
sys.path.insert(0, str(Path(__file__).parent / "qx-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-data" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-features" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-backtest" / "src"))

# --- Module Imports ---
from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.order import Order, OrderSide, OrderType
from qx_core.regime.detector import RegimeDetectorRules
from qx_core.schemas import RegimeType
from qx_data.gold_loader import load_bars
from qx_data.resample import resample_data

from extensions.intraday_ml.data_prep import (
    create_feature_set,
    create_training_dataset,
)
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer
from extensions.intraday_ml_policies.decision_policy import DecisionPolicy

try:
    from qx_report.performance import display_performance_summary
except ImportError:
    display_performance_summary = None

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def add_regime_feature(data: pd.DataFrame) -> pd.DataFrame:
    """Adds a market regime feature to the dataset."""
    logger.info("Adding regime feature...")
    if data.empty:
        return data

    detector = RegimeDetectorRules()
    regime_map = {}
    regime_to_int = {
        RegimeType.BULL.value: 1,
        RegimeType.BEAR.value: -1,
        RegimeType.SIDEWAYS.value: 2,
        RegimeType.STRESS.value: 3,
        RegimeType.OFF.value: 0,
    }

    for ts_int, group in data.groupby("ts"):
        group_dt = group.copy()
        group_dt["ts"] = pd.to_datetime(group_dt["ts"])
        regime_signal = detector.evaluate(group_dt, ts_int)
        regime_map[ts_int] = regime_to_int.get(regime_signal.regime.value, 0)

    data["f__regime__state"] = data["ts"].map(regime_map)
    data["f__regime__state"] = data["f__regime__state"].fillna(0).astype(int)
    logger.info(
        f"Regime feature added. Distribution:\n{data['f__regime__state'].value_counts()}"
    )
    return data


def run_workflow(
    train_start, train_end, test_start, test_end, benchmark_symbol: str = "SPY"
):
    """Executes the full train-and-backtest workflow."""

    # --- Configuration ---
    SYMBOLS = ["BAC"]
    TIMEFRAME = "10min"
    ARTIFACT_DIR = Path("artefacts/extensions/intraday_ml/full_run")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_PATH = ARTIFACT_DIR / f"model_{train_start}_to_{train_end}_{TIMEFRAME}.pkl"

    with open("configs/extensions/intraday_ml/features.yaml") as f:
        features_config = yaml.safe_load(f)
    with open("configs/extensions/intraday_ml/targets.yaml") as f:
        targets_config = yaml.safe_load(f)
    with open("configs/extensions/intraday_ml/model_lgbm.yaml") as f:
        model_config = yaml.safe_load(f)

    # ##################################################################
    #                           TRAINING PHASE
    # ##################################################################
    logger.info("============== STARTING TRAINING PHASE ==============")
    logger.info(f"Training Period: {train_start} to {train_end} on {TIMEFRAME} bars")

    # 1. Load and Resample Training Data
    train_end_dt_buffer = datetime.strptime(train_end, "%Y-%m-%d") + timedelta(days=2)
    train_dates = [
        d.strftime("%Y-%m-%d") for d in pd.date_range(train_start, train_end_dt_buffer)
    ]
    training_bars_1m = load_bars(
        root="/home/jacobw/gcs-mount",
        family="bars_1m",
        symbols=SYMBOLS,
        dates=train_dates,
    )
    training_bars_resampled = resample_data(training_bars_1m, TIMEFRAME)

    # 2. Create Training Dataset
    training_data = create_training_dataset(
        data_window=training_bars_resampled,
        features_config=features_config,
        targets_config=targets_config,
    )
    training_data = training_data[
        training_data["ts"] <= pd.Timestamp(train_end).timestamp() * 1e9
    ]

    if training_data.empty or len(training_data["label"].unique()) <= 1:
        logger.error("Could not generate a valid training dataset. Exiting.")
        return

    # 3. Add Regime Feature
    training_data = add_regime_feature(training_data)

    # 4. Train Model
    logger.info(f"Training model on {len(training_data)} samples...")
    trainer = LightGBMTrainer(model_config)
    feature_columns = [col for col in training_data.columns if col.startswith("f__")]
    features_df = training_data[feature_columns]
    labels_series = training_data["label"]
    result = trainer.train_model(
        features=features_df,
        labels=labels_series,
        features_hash="not_used",
        targets_hash="not_used",
    )
    logger.info(
        f"Model training complete. Accuracy: {result.metrics.get('accuracy', 0):.2%}"
    )

    # 5. Save Model
    joblib.dump(result.model, MODEL_PATH)

    # ##################################################################
    #                         BACKTESTING PHASE
    # ##################################################################
    logger.info("\n============== STARTING BACKTESTING PHASE ==============")
    logger.info(f"Backtest Period: {test_start} to {test_end} on {TIMEFRAME} bars")

    # 1. Load Model
    model = joblib.load(MODEL_PATH)

    # 2. Load, Resample, and Create OOS Features
    test_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(test_start, test_end)]
    oos_bars_1m = load_bars(
        root="/home/jacobw/gcs-mount",
        family="bars_1m",
        symbols=SYMBOLS,
        dates=test_dates,
    )
    oos_bars_resampled = resample_data(oos_bars_1m, TIMEFRAME)

    oos_features = create_feature_set(
        data_window=oos_bars_resampled,
        features_config=features_config,
    )
    if oos_features.empty:
        logger.error("Could not generate features for the backtest period. Exiting.")
        return
    oos_features = add_regime_feature(oos_features)

    # 3. Generate Predictions
    probabilities = model.predict_proba(oos_features[feature_columns])
    oos_features["probability"] = np.max(probabilities, axis=1)
    oos_features["signal"] = model.classes_[np.argmax(probabilities, axis=1)]
    trade_signals = oos_features[oos_features["signal"] != 0].copy()

    # 4. Setup Policy and Strategy
    policy = DecisionPolicy({"probability_threshold": 0.65, "cooldown_minutes": 15})
    signal_map = {
        (row.ts, row.symbol): (row.signal, row.probability)
        for row in trade_signals.itertuples()
    }
    EOD_EXIT_TIME = time(15, 55)

    def strategy_func(engine, bar_event):
        symbol, timestamp = bar_event["symbol"], bar_event["ts"]
        bar_time = pd.to_datetime(timestamp).time()

        if bar_time >= EOD_EXIT_TIME:
            current_position = engine.get_position(symbol)
            if current_position and current_position.quantity != 0:
                logger.info(f"EOD EXIT: Closing position for {symbol} at {bar_time}")
                side = OrderSide.SELL if current_position.quantity > 0 else OrderSide.BUY
                engine.submit_order(
                    Order(
                        order_id=uuid.uuid4().hex,
                        symbol=symbol,
                        order_type=OrderType.MARKET,
                        side=side,
                        quantity=abs(current_position.quantity),
                    )
                )
            return

        signal_data = signal_map.get((timestamp, symbol))
        if signal_data:
            signal, probability = signal_data
            if policy.should_trade(symbol, probability, timestamp):
                side = OrderSide.BUY if signal == 1 else OrderSide.SELL
                engine.submit_order(
                    Order(
                        order_id=uuid.uuid4().hex,
                        symbol=symbol,
                        order_type=OrderType.MARKET,
                        side=side,
                        quantity=100,
                    )
                )
                policy.record_trade(symbol, timestamp)

    # 5. Run Backtest
    backtest_config = BacktestConfig(
        initial_cash=100_000,
        start_date=test_start,
        end_date=test_end,
        benchmark=benchmark_symbol,
    )
    engine = BacktestEngine(backtest_config)
    result = engine.run(oos_bars_resampled, strategy_func)

    # 6. Report Results
    logger.info("Backtest complete. Final performance:")
    if display_performance_summary:
        display_performance_summary(result)
    else:
        print(result.to_dict())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run a full ML training and backtesting workflow."
    )
    parser.add_argument(
        "--train-start", required=True, help="Training start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--train-end", required=True, help="Training end date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--test-start", required=True, help="Backtest start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--test-end", required=True, help="Backtest end date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default="SPY",
        help="Benchmark symbol for backtest (default: SPY)",
    )
    args = parser.parse_args()
    run_workflow(
        args.train_start,
        args.train_end,
        args.test_start,
        args.test_end,
        args.benchmark,
    )
