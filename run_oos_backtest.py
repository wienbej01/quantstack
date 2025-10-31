#!/usr/bin/env python3
"""
Out-of-Sample (OOS) Trading Backtest for Phase A Model

Integrates a Decision Policy to filter trades based on model confidence
and a cooldown period.
"""
import argparse
import logging
import joblib
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import yaml
import uuid
from datetime import datetime, timedelta

# Add project paths
sys.path.insert(0, str(Path(__file__).parent / "qx-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-data" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-features" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-backtest" / "src"))

from extensions.intraday_ml.data_prep import create_feature_set
from extensions.intraday_ml_policies.decision_policy import DecisionPolicy
from qx_backtest.engine import BacktestEngine, BacktestConfig
from qx_backtest.order import Order, OrderSide, OrderType
from qx_data.gold_loader import load_bars

# Try to import the performance summary display, handle if not available
try:
    from qx_report.performance import display_performance_summary
except ImportError:
    display_performance_summary = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

def run_backtest(start_date: str, end_date: str):
    """Runs the backtest for a given period."""
    logger.info(f"🚀 Starting OOS Backtest for period {start_date} to {end_date}...")

    # --- 1. Configuration ---
    SYMBOLS = ["BAC"]
    MODEL_PATH = "artefacts/extensions/intraday_ml/phaseA/model_lgbm/model.pkl"
    FEATURES_CONFIG_PATH = "configs/extensions/intraday_ml/features.yaml"
    INITIAL_CASH = 100_000
    ORDER_SIZE = 100

    policy_config = {
        "probability_threshold": 0.65,  # Only trade if confidence is > 65%
        "cooldown_minutes": 15,         # Wait 15 mins after a trade
    }
    policy = DecisionPolicy(policy_config)

    with open(FEATURES_CONFIG_PATH, "r") as f:
        features_config = yaml.safe_load(f)

    # --- 2. Load Trained Model ---
    logger.info(f"Loading model from {MODEL_PATH}")
    model = joblib.load(MODEL_PATH)

    # --- 3. Prepare OOS Feature Data ---
    logger.info(f"Preparing OOS feature data from {start_date} to {end_date}")
    oos_features = create_feature_set(
        symbols=SYMBOLS,
        start_date=start_date,
        end_date=end_date,
        features_config=features_config,
        data_loader_config={
            "root": "/home/jacobw/gcs-mount",
            "family": "bars_1m",
        },
    )
    
    if oos_features.empty:
        logger.warning("No feature data generated for the specified period. Exiting.")
        return

    logger.info(f"Generated {len(oos_features.columns)} features for {len(oos_features)} OOS bars")

    # --- 4. Generate Predictions with Probabilities ---
    logger.info("Generating trading signals and probabilities from model...")
    feature_columns = [col for col in oos_features.columns if col.startswith("f__")]
    
    probabilities = model.predict_proba(oos_features[feature_columns])
    
    oos_features['probability'] = np.max(probabilities, axis=1)
    oos_features['signal'] = model.classes_[np.argmax(probabilities, axis=1)]
    
    trade_signals = oos_features[oos_features['signal'] != 0].copy()
    logger.info(f"Generated {len(trade_signals)} non-neutral trade signals before policy filtering.")

    # --- 5. Prepare Bar Data for Backtest Engine ---
    logger.info(f"Preparing bar data for backtest engine...")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    current = start_dt
    while current <= end_dt:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    oos_bars = load_bars(
        root="/home/jacobw/gcs-mount",
        family="bars_1m",
        symbols=SYMBOLS,
        dates=dates,
    )

    if oos_bars.empty:
        logger.warning("No bar data found for the specified period. Exiting.")
        return

    # --- 6. Define the Trading Strategy and Run Backtest ---
    logger.info("Configuring and running the qx-backtest engine with Decision Policy...")
    signal_map = {
        (row.ts, row.symbol): (row.signal, row.probability)
        for row in trade_signals.itertuples()
    }

    def strategy_func(engine, bar_event):
        lookup_key = (bar_event['ts'], bar_event['symbol'])
        signal_data = signal_map.get(lookup_key)

        if signal_data:
            signal, probability = signal_data
            symbol = bar_event['symbol']
            timestamp = bar_event['ts']

            if policy.should_trade(symbol, probability, timestamp):
                side = OrderSide.BUY if signal == 1 else OrderSide.SELL
                
                current_position = engine.get_position(symbol)
                if current_position and current_position.quantity != 0:
                    if (current_position.quantity > 0 and side == OrderSide.SELL) or \
                       (current_position.quantity < 0 and side == OrderSide.BUY):
                        engine.submit_order(Order(
                            order_id=f"ml_close_{timestamp}_{uuid.uuid4().hex[:8]}",
                            symbol=symbol,
                            order_type=OrderType.MARKET,
                            side=OrderSide.SELL if current_position.quantity > 0 else OrderSide.BUY,
                            quantity=abs(current_position.quantity)
                        ))
                
                engine.submit_order(Order(
                    order_id=f"ml_order_{timestamp}_{uuid.uuid4().hex[:8]}",
                    symbol=symbol,
                    order_type=OrderType.MARKET,
                    side=side,
                    quantity=ORDER_SIZE
                ))
                
                policy.record_trade(symbol, timestamp)

    backtest_config = BacktestConfig(
        initial_cash=INITIAL_CASH,
        start_date=start_date,
        end_date=end_date,
    )
    engine = BacktestEngine(backtest_config)
    result = engine.run(oos_bars, strategy_func)

    # --- 7. Analyze Results ---
    logger.info("Backtest complete. Generating performance summary...")
    if display_performance_summary:
        display_performance_summary(result)
    else:
        logger.warning("Could not import display_performance_summary. Printing raw results.")
        print(result.to_dict())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run OOS backtest for the Phase A model.")
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="Start date for the backtest in YYYY-MM-DD format."
    )
    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="End date for the backtest in YYYY-MM-DD format."
    )
    args = parser.parse_args()

    run_backtest(args.start_date, args.end_date)
