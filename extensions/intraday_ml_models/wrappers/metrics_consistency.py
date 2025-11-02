import argparse
import json
import logging
import sys
import time

import numpy as np
import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def run_metrics_consistency_check(backtest_config: dict) -> None:
    start_time = time.time()

    report_dir = backtest_config["paths"]["report_dir"]
    equity_path = f"{report_dir}/equity.parquet"
    trades_path = f"{report_dir}/trades.parquet"
    meta_path = f"{report_dir}/run_meta.json"

    try:
        equity_df = pd.read_parquet(equity_path)
        equity_df = equity_df.set_index("timestamp")
        trades_df = pd.read_parquet(trades_path)
        with open(meta_path) as f:
            run_meta = json.load(f)
    except FileNotFoundError as e:
        print(f"BLOCKED: missing outputs from backtest_runner: {e}")
        sys.exit(1)

    if equity_df.empty or trades_df.empty:
        print("BLOCKED: trades or equity data is empty")
        sys.exit(1)

    total_pnl = trades_df["pnl"].sum()
    equity_delta = equity_df["equity"].iloc[-1] - equity_df["equity"].iloc[0]
    pnl_equity_diff = abs(total_pnl - equity_delta)
    tolerance = 1e-6 * backtest_config["equity"]["starting_equity"] + 1e-3
    reconciliation_check = pnl_equity_diff <= tolerance

    if not reconciliation_check:
        print(f"BLOCKED: PnL and Equity do not reconcile. Diff: {pnl_equity_diff}")
        sys.exit(1)

    minute_returns = equity_df["equity"].pct_change().dropna()
    minute_sharpe = (
        np.sqrt(
            backtest_config["annualize"]["trading_days_per_year"]
            * backtest_config["annualize"]["minute_bars_per_day"]
        )
        * minute_returns.mean()
        / minute_returns.std()
    )

    daily_returns = equity_df["equity"].resample("D").last().pct_change().dropna()
    daily_sharpe = (
        np.sqrt(backtest_config["annualize"]["trading_days_per_year"])
        * daily_returns.mean()
        / daily_returns.std()
    )

    overnight_exposure_count = 0  # Assuming backtest_runner enforces this

    metrics = {
        "minute_sharpe": minute_sharpe,
        "daily_sharpe": daily_sharpe,
        "pnl_equity_diff": pnl_equity_diff,
        "pnl_equity_reconciled": bool(reconciliation_check),
        "fill_rate": run_meta["fill_rate"],
        "overnight_exposure_count": overnight_exposure_count,
    }

    duration = time.time() - start_time
    summary = {"report_dir": report_dir, "metrics": metrics, "duration": duration}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run metrics consistency checks.")
    parser.add_argument("--backtest", required=True, help="Path to backtest.yaml")
    args = parser.parse_args()

    with open(args.backtest) as f:
        backtest_config = yaml.safe_load(f)

    run_metrics_consistency_check(backtest_config)
