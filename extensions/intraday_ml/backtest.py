"""Intraday ML backtest engine adapter.

This module wraps existing qx-backtest functionality to provide the Sprint 6 interface
while maintaining strict separation from core modules.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from qx_core.hashers import hash_dataframe


def intraday_ml_run_backtest(
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    cfg: dict[str, Any],
    config_path: str | None = None,
    enforce_intraday_compliance: bool = True,
) -> dict[str, Any]:
    """Run backtest using existing qx-backtest with intraday compliance.

    Args:
        bars: DataFrame with OHLCV data
        orders: DataFrame with sized orders
        cfg: Backtest configuration
        config_path: Path to configuration file
        enforce_intraday_compliance: Whether to enforce intraday trading rules

    Returns:
        Dictionary with Sprint 6 artifacts
    """
    # Load existing qx-backtest engine
    from qx_backtest.engine import BacktestEngine, BacktestConfig
    from qx_backtest.fill import DefaultFiller

    # Load and merge configuration
    config = _load_and_merge_config(cfg, config_path)

    # Validate inputs
    _validate_inputs(bars, orders)

    # Apply intraday preprocessing if required
    if enforce_intraday_compliance:
        processed_bars, processed_orders = _apply_intraday_constraints(bars, orders, config)
    else:
        processed_bars, processed_orders = bars, orders

    # Configure engine with existing interfaces
    engine_config = BacktestConfig(
        initial_cash=config["initial_cash"],
        start_date=config.get("start_date"),
        end_date=config.get("end_date"),
        benchmark=config.get("benchmark", "SPY"),
        risk_free_rate=config.get("risk_free_rate", 0.02),
    )

    # Create engine
    engine = BacktestEngine(engine_config)

    # Configure filler with intraday costs
    costs = config["costs"]
    filler = DefaultFiller(
        bps=costs["bps"],
        per_share=costs["per_share"],
        slippage_ticks=costs["slippage_ticks"],
        tick_size=costs["tick_size"],
    )
    engine.filler = filler

    # Create strategy wrapper for our orders
    strategy = _create_strategy_wrapper(processed_orders)

    # Run backtest using existing engine
    result = engine.run(processed_bars, strategy)

    # Convert result to Sprint 6 artifacts format
    artifacts = _convert_result_to_artifacts(result, config)

    # Write artifacts if configured
    if config.get("write_artifacts", True):
        _write_artifacts(artifacts, config)

    return artifacts


def intraday_ml_get_backtest_hash(
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    cfg: dict[str, Any],
    config_path: str | None = None,
) -> str:
    """Get deterministic hash of backtest inputs and configuration."""
    config = _load_and_merge_config(cfg, config_path)

    # Create hash from inputs and configuration
    input_data = {
        "bars_hash": hash_dataframe(bars),
        "orders_hash": hash_dataframe(orders),
        "config_hash": hash_dataframe(pd.DataFrame([config])),
    }

    return hash_dict(input_data)


def _load_and_merge_config(cfg: dict[str, Any], config_path: str | None) -> dict[str, Any]:
    """Load configuration from file and merge with input."""
    # Default configuration
    default_config = {
        "initial_cash": 1_000_000.0,
        "write_artifacts": True,
        "artifacts_dir": "artifacts/intraday_ml",
        "costs": {
            "bps": 0.001,
            "per_share": 0.003,
            "slippage_ticks": 1,
            "tick_size": 0.01,
        },
        "intraday_constraints": {
            "next_bar_execution": True,
            "flat_eod_time": "15:59:59",
            "no_overnight_positions": True,
            "eod_buffer_minutes": 5,
        },
    }

    # Load from file if provided
    if config_path:
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file, 'r') as f:
                file_config = yaml.safe_load(f)
            default_config.update(file_config)

    # Merge with input configuration
    for key, value in cfg.items():
        if key in ["costs", "intraday_constraints"] and isinstance(value, dict):
            # Deep merge for nested dictionaries
            if key in default_config and isinstance(default_config[key], dict):
                default_config[key].update(value)
            else:
                default_config[key] = value.copy()
        else:
            default_config[key] = value

    return default_config


def _validate_inputs(bars: pd.DataFrame, orders: pd.DataFrame) -> None:
    """Validate input DataFrames."""
    if bars.empty:
        raise ValueError("Bars DataFrame cannot be empty")

    required_bar_cols = ["ts", "symbol", "open", "high", "low", "close", "volume"]
    missing_bars = [col for col in required_bar_cols if col not in bars.columns]
    if missing_bars:
        raise ValueError(f"Missing required bar columns: {missing_bars}")

    if not orders.empty:
        required_order_cols = ["ts", "symbol", "side", "qty"]
        missing_orders = [col for col in required_order_cols if col not in orders.columns]
        if missing_orders:
            raise ValueError(f"Missing required order columns: {missing_orders}")


def _apply_intraday_constraints(
    bars: pd.DataFrame, orders: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply intray trading constraints."""
    constraints = config["intraday_constraints"]

    # Apply next bar execution
    if not orders.empty and constraints["next_bar_execution"]:
        orders = _shift_to_next_bar(orders, bars)

    # Apply EOD flat constraint
    if not orders.empty and constraints["no_overnight_positions"]:
        orders = _filter_eod_violations(orders, bars, constraints)

    return bars, orders


def _shift_to_next_bar(orders: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Shift order execution to next bar after signal."""
    # Build next bar mapping
    bars_sorted = bars.sort_values(["symbol", "ts"])
    next_bar = {}

    for symbol, group in bars_sorted.groupby("symbol"):
        timestamps = group["ts"].values
        for i in range(len(timestamps) - 1):
            next_bar[(symbol, timestamps[i])] = timestamps[i + 1]

    # Apply next bar execution
    shifted_orders = []
    for _, order in orders.iterrows():
        key = (order["symbol"], order["ts"])
        if key in next_bar:
            shifted_order = order.copy()
            shifted_order["ts"] = next_bar[key]
            shifted_order["original_signal_ts"] = order["ts"]
            shifted_orders.append(shifted_order)

    return pd.DataFrame(shifted_orders) if shifted_orders else pd.DataFrame()


def _filter_eod_violations(
    orders: pd.DataFrame, bars: pd.DataFrame, constraints: dict[str, Any]
) -> pd.DataFrame:
    """Filter orders that would violate EOD flat constraint."""
    from datetime import time, datetime, timedelta

    eod_time = time(15, 59, 59)
    buffer_minutes = constraints["eod_buffer_minutes"]
    eod_cutoff = timedelta(minutes=buffer_minutes)

    # Convert bars to ET for EOD calculation
    bars_et = bars.copy()
    bars_et["datetime"] = pd.to_datetime(bars_et["ts"], unit="ns", utc=True)
    bars_et["datetime_et"] = bars_et["datetime"].dt.tz_convert("America/New_York")
    bars_et["time"] = bars_et["datetime_et"].dt.time
    bars_et["date"] = bars_et["datetime_et"].dt.date

    # Find EOD cutoff times per symbol per day
    last_bars = bars_et.loc[bars_et.groupby(["symbol", "date"])["ts"].idxmax()]
    cutoff_times = set()

    for _, last_bar in last_bars.iterrows():
        if last_bar["time"] >= eod_time:
            eod_datetime = datetime.combine(last_bar["date"], eod_time)
            eod_datetime = eod_datetime.replace(tzinfo=last_bar["datetime_et"].tzinfo)
            cutoff = eod_datetime - eod_cutoff
            cutoff_times.add((last_bar["symbol"], cutoff.timestamp() * 1_000_000))  # Convert to ns

    # Filter orders
    valid_orders = []
    for _, order in orders.iterrows():
        if (order["symbol"], order["ts"]) not in cutoff_times:
            valid_orders.append(order)

    return pd.DataFrame(valid_orders) if valid_orders else pd.DataFrame()


def _create_strategy_wrapper(orders: pd.DataFrame):
    """Create strategy function wrapper for pre-sized orders."""
    def strategy(bars: pd.DataFrame) -> pd.DataFrame:
        if orders.empty:
            return pd.DataFrame()

        # Return orders matching available bar timestamps
        available_timestamps = set(bars["ts"])
        matching_orders = orders[orders["ts"].isin(available_timestamps)]
        return matching_orders.copy()

    return strategy


def _convert_result_to_artifacts(result: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Convert engine result to Sprint 6 artifacts format."""
    artifacts = {}

    # Extract data based on result type
    if hasattr(result, '__dict__'):
        # Object with attributes
        artifacts = {
            "metrics": getattr(result, 'metrics', {}),
            "equity": getattr(result, 'equity_curve', pd.DataFrame()),
            "positions": getattr(result, 'positions', pd.DataFrame()),
            "trades": getattr(result, 'trades', pd.DataFrame()),
            "orders": getattr(result, 'orders', pd.DataFrame()),
            "fills": getattr(result, 'fills', pd.DataFrame()),
        }
    elif isinstance(result, dict):
        artifacts = result.copy()
    else:
        # Unknown result format
        artifacts = {}

    # Ensure all required artifacts exist
    required_artifacts = [
        "signals", "orders", "fills", "positions", "equity",
        "trades", "risk_rejects", "allocation_log"
    ]

    for artifact_name in required_artifacts:
        if artifact_name not in artifacts:
            artifacts[artifact_name] = pd.DataFrame()

    # Ensure metrics exist
    if "metrics" not in artifacts:
        artifacts["metrics"] = _calculate_metrics(artifacts)

    # Add Sprint 6 required columns to trades
    if "trades" in artifacts and not artifacts["trades"].empty:
        trades_df = artifacts["trades"]
        required_columns = ["stop_dist_ps", "fees", "slippage_est", "r_multiple"]
        for col in required_columns:
            if col not in trades_df.columns:
                trades_df[col] = 0.0
        artifacts["trades"] = trades_df

    return artifacts


def _calculate_metrics(artifacts: dict[str, Any]) -> dict[str, Any]:
    """Calculate basic metrics from artifacts."""
    metrics = {
        "trades": 0,
        "avg_R": 0.0,
        "fees_total": 0.0,
        "total_pnl": 0.0,
        "win_rate": 0.0,
    }

    # Calculate from trades if available
    if "trades" in artifacts and not artifacts["trades"].empty:
        trades_df = artifacts["trades"]
        metrics["trades"] = len(trades_df)

        if "pnl" in trades_df.columns:
            metrics["total_pnl"] = trades_df["pnl"].sum()
            metrics["avg_R"] = trades_df["pnl"].mean()
            metrics["win_rate"] = (trades_df["pnl"] > 0).sum() / len(trades_df)

    # Calculate fees from fills if available
    if "fills" in artifacts and not artifacts["fills"].empty:
        fills_df = artifacts["fills"]
        if "fees" in fills_df.columns:
            metrics["fees_total"] = fills_df["fees"].sum()

    return metrics


def _write_artifacts(artifacts: dict[str, Any], config: dict[str, Any]) -> None:
    """Write artifacts to files."""
    artifacts_dir = Path(config["artifacts_dir"])
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Write parquet files
    for name, df in artifacts.items():
        if isinstance(df, pd.DataFrame) and not df.empty:
            df.to_parquet(artifacts_dir / f"{name}.parquet", index=False)

    # Write metrics as JSON
    if "metrics" in artifacts:
        with open(artifacts_dir / "metrics.json", 'w') as f:
            json.dump(artifacts["metrics"], f, indent=2, default=str)


# Import hash function
from qx_core.hashers import hash_dict