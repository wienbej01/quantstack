import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# --- Assume these are existing, stable core modules ---
# from extensions.intraday_ml_models.model_io import load_model
# from qx_backtest.adapter import BacktestAdapter
# from qx_features.policy import decision_policy

# For development, let's create dummy placeholders for these imports.
def load_model(model_dir: str) -> Any:
    class DummyModel:
        def predict_proba(self, df: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame({'prob_30': 0.6, 'prob_60': 0.65, 'prob_90': 0.55}, index=df.index)
    return DummyModel()

class BacktestAdapter:
    def __init__(self, config):
        self.starting_equity = config.get('equity', {}).get('starting_equity', 100000.0)

    def run(self, orders):
        # Return a dummy trade and equity curve to satisfy the contract
        trades = pd.DataFrame({
            'entry_ts': [pd.Timestamp.now(tz='UTC')],
            'exit_ts': [pd.Timestamp.now(tz='UTC') + pd.Timedelta(minutes=5)],
            'pnl': [100.0]
        })
        equity = pd.DataFrame({
            'timestamp': [pd.Timestamp.now(tz='UTC'), pd.Timestamp.now(tz='UTC') + pd.Timedelta(minutes=5)],
            'equity': [self.starting_equity, self.starting_equity + 100.0]
        })
        return {
            "trades": trades,
            "equity": equity,
        }

def decision_policy(features, probabilities, **kwargs):
    signals = features.copy()
    # Apply the probability threshold
    if 'probability_threshold' in kwargs:
        # Assuming single horizon for simplicity
        signals['signal'] = (probabilities['prob_30'] >= kwargs['probability_threshold']).astype(int)
    else:
        signals['signal'] = 1
    signals['expected_value'] = 0.1 # Dummy expected value
    return signals

# --- End of placeholder imports ---

from extensions.intraday_ml_models.wrappers.order_sizer_fixed1 import get_sizer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run(policy_config_path: str, backtest_config: dict) -> None:
    start_time = time.time()

    with open(policy_config_path) as f:
        policy_config = yaml.safe_load(f)

    paths = backtest_config['paths']
    report_dir = Path(paths['report_dir'])
    report_dir.mkdir(parents=True, exist_ok=True)

    model = load_model(paths['model_dir'])
    features = pd.read_parquet(paths['features'])
    if not isinstance(features.index, pd.DatetimeIndex):
        features.index = pd.to_datetime(features.index)

    probabilities = model.predict_proba(features)
    signals = decision_policy(
        features, probabilities, **policy_config
    )

    # Horizon compaction
    signals = signals.loc[signals.groupby(signals.index)['expected_value'].idxmax()]

    order_sizer = get_sizer(position_size=backtest_config['position_size'])
    orders = []
    late_dropped = 0
    no_next_bar_dropped = 0

    for timestamp, signal_row in signals.iterrows():
        if signal_row['signal'] != 0:
            entry_timestamp = timestamp + pd.Timedelta(minutes=1)
            eod_time = pd.to_datetime(timestamp.date().strftime('%Y-%m-%d') + ' ' + backtest_config['timing']['eod_liquidation_time'])
            if entry_timestamp >= eod_time or entry_timestamp.time() >= pd.to_datetime(policy_config['block_new_entries_after_et']).time():
                late_dropped += 1
                continue

            orders.append({
                "timestamp": entry_timestamp,
                "symbol": "AAPL",
                "quantity": order_sizer(signal_row.to_dict()),
                "side": "BUY" if signal_row['signal'] == 1 else "SELL",
            })

    if not orders:
        print("BLOCKED: no orders after policy")
        sys.exit(1)

    backtest_adapter = BacktestAdapter(backtest_config)
    backtest_results = backtest_adapter.run(orders)

    trades_df = backtest_results['trades']
    equity_df = backtest_results['equity']

    if trades_df.empty or equity_df.empty:
        print("BLOCKED: no trades or equity produced by backtest")
        sys.exit(1)

    fill_rate = len(trades_df) / len(orders) if orders else 0

    run_meta = {
        "orders_submitted": len(orders),
        "orders_executed": len(trades_df),
        "late_dropped": late_dropped,
        "no_next_bar_dropped": no_next_bar_dropped,
        "fill_rate": fill_rate,
    }

    trades_df.to_parquet(report_dir / "trades.parquet")
    equity_df.to_parquet(report_dir / "equity.parquet")
    with open(report_dir / "run_meta.json", "w") as f:
        json.dump(run_meta, f)

    duration = time.time() - start_time
    summary = {"report_dir": str(report_dir), "counts": run_meta, "duration": duration}
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run intraday ML backtest.")
    parser.add_argument("--policy", required=True, help="Path to policy_overrides.yaml")
    parser.add_argument("--backtest", required=True, help="Path to backtest.yaml")
    args = parser.parse_args()

    with open(args.backtest) as f:
        backtest_config = yaml.safe_load(f)

    run(args.policy, backtest_config)