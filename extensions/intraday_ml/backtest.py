"""Intraday ML backtest engine adapter.

This module wraps existing qx-backtest functionality to provide the Sprint 6 interface
while maintaining strict separation from core modules.
"""

import json
from collections import defaultdict
from numbers import Integral
from pathlib import Path
from typing import Any

import numpy as np
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
    from qx_backtest.engine import BacktestConfig, BacktestEngine
    from qx_backtest.fill import DefaultFiller

    # Load and merge configuration
    config = _load_and_merge_config(cfg, config_path)
    if "artifacts_path" not in config:
        config["artifacts_path"] = config.get("artifacts_dir", "artifacts/intraday_ml")

    # Validate inputs
    _validate_inputs(bars, orders)

    # Apply intraday preprocessing if required
    if enforce_intraday_compliance:
        processed_bars, processed_orders = _apply_intraday_constraints(
            bars, orders, config
        )
    else:
        processed_bars, processed_orders = bars.copy(), orders.copy()

    # Ensure data is properly sorted by timestamp (required by engine)
    processed_bars = processed_bars.sort_values(["ts", "symbol"]).reset_index(drop=True)

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
    costs = config.get("costs", {})
    filler = DefaultFiller(
        commission_per_share=costs.get("per_share", 0.0035),
        commission_min=costs.get("commission_min", 0.35),
        slippage_bps=costs.get("bps", 5),
        partial_fill_probability=costs.get("partial_fill_probability", 0.3),
        max_partial_fill_ratio=costs.get("max_partial_fill_ratio", 0.5),
        fill_probability=costs.get("fill_probability", 0.95),
    )
    engine.filler = filler

    # Create strategy wrapper for our orders
    strategy = _create_strategy_wrapper(
        processed_orders, config.get("intraday_constraints", {})
    )

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


def _load_and_merge_config(
    cfg: dict[str, Any], config_path: str | None
) -> dict[str, Any]:
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
            with open(config_file) as f:
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
        missing_orders = [
            col for col in required_order_cols if col not in orders.columns
        ]
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


def _to_ns_timestamp(value: Any) -> int:
    """Convert assorted timestamp representations into UTC nanoseconds."""
    if isinstance(value, Integral):
        return int(value)

    if isinstance(value, pd.Timestamp):
        ts = value
    elif isinstance(value, np.datetime64):
        ts = pd.Timestamp(value)
    else:
        ts = pd.to_datetime(value, errors="raise", utc=True)

    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.value)


def _shift_to_next_bar(orders: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Shift order execution to next bar after signal."""
    # Build next bar mapping
    bars_sorted = bars.sort_values(["symbol", "ts"]).copy()
    bars_sorted["ts_ns"] = bars_sorted["ts"].apply(_to_ns_timestamp)
    next_bar = {}

    for symbol, group in bars_sorted.groupby("symbol"):
        timestamps = group["ts_ns"].values
        for i in range(len(timestamps) - 1):
            next_bar[(symbol, timestamps[i])] = timestamps[i + 1]

    # Apply next bar execution
    shifted_orders = []
    for _, order in orders.iterrows():
        original_ts_ns = _to_ns_timestamp(order["ts"])
        key = (order["symbol"], original_ts_ns)
        if key in next_bar:
            shifted_order = order.copy()
            next_ts = next_bar[key]
            shifted_order["original_signal_ts"] = original_ts_ns
            shifted_order["ts"] = next_ts
            if "timestamp" in shifted_order:
                shifted_order["timestamp"] = pd.to_datetime(next_ts, unit="ns", utc=True)
            shifted_orders.append(shifted_order)

    return pd.DataFrame(shifted_orders) if shifted_orders else pd.DataFrame()


def _filter_eod_violations(
    orders: pd.DataFrame, bars: pd.DataFrame, constraints: dict[str, Any]
) -> pd.DataFrame:
    """Filter orders that would violate EOD flat constraint."""
    from datetime import datetime, time, timedelta

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
            cutoff_times.add(
                (last_bar["symbol"], cutoff.timestamp() * 1_000_000)
            )  # Convert to ns

    # Filter orders
    valid_orders = []
    for _, order in orders.iterrows():
        if (order["symbol"], order["ts"]) not in cutoff_times:
            valid_orders.append(order)

    return pd.DataFrame(valid_orders) if valid_orders else pd.DataFrame()


def _create_strategy_wrapper(
    orders: pd.DataFrame, intraday_constraints: dict[str, Any]
):
    """Create strategy function wrapper for pre-sized orders with position management."""

    def _coerce_to_utc_timestamp(value: Any) -> tuple[int, pd.Timestamp]:
        """Return nanosecond integer and UTC timestamp for the provided value."""
        if isinstance(value, pd.Timestamp):
            ts = value
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            return int(ts.value), ts

        if isinstance(value, Integral):
            ts = pd.to_datetime(int(value), utc=True, unit="ns")
            return int(ts.value), ts

        try:
            ts = pd.to_datetime(value, utc=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unsupported timestamp value: {value!r}") from exc

        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return int(ts.value), ts

    if orders is None:
        orders = pd.DataFrame()

    if not orders.empty:
        orders = orders.copy()
        orders["ts"] = orders["ts"].apply(
            lambda value: _coerce_to_utc_timestamp(value)[0]
        )

    session_timezone = intraday_constraints.get("session_timezone", "America/New_York")
    flat_time_str = intraday_constraints.get("flat_eod_time", "15:59:59")
    flat_time = pd.to_datetime(flat_time_str).time()
    forced_flat_tracker: dict[str, set[str]] = defaultdict(set)

    def strategy(engine, bar_dict: dict) -> None:
        """Strategy function with proper LONG/SHORT handling and position management."""
        # Get current bar timestamp and symbol
        current_ts = bar_dict.get("ts")
        symbol = bar_dict.get("symbol")
        if current_ts is None or symbol is None:
            return

        ts_value, ts_utc = _coerce_to_utc_timestamp(current_ts)
        ts_et = ts_utc.tz_convert(session_timezone)
        date_key = ts_et.date().isoformat()

        from qx_backtest.order import Order, OrderSide, OrderType

        position = engine.get_position(symbol)
        current_qty = 0
        if position:
            qty_value = getattr(position, "quantity", 0)
            try:
                current_qty = int(qty_value)
            except (TypeError, ValueError):
                current_qty = 0

        # Force flat at configured cutoff time
        if (
            position
            and ts_et.time() >= flat_time
            and date_key not in forced_flat_tracker[symbol]
        ):
            forced_flat_tracker[symbol].add(date_key)
            exit_side = OrderSide.SELL if position.is_long else OrderSide.BUY
            order_id = f"ml_force_flat_{ts_value}"
            if abs(current_qty) > 0:
                forced_order = Order(
                    order_id=order_id,
                    symbol=symbol,
                    side=exit_side,
                    quantity=abs(current_qty),
                    order_type=OrderType.MARKET,
                    timestamp=ts_value,
                )
                forced_order.tags = {"exit_reason": "force_flat"}
                engine.submit_order(forced_order)
            return

        if orders.empty:
            return

        # Find orders matching current timestamp and symbol
        matching_orders = orders[
            (orders["ts"] == ts_value) & (orders["symbol"] == symbol)
        ]

        for idx, (_, order) in enumerate(matching_orders.iterrows()):
            # Convert order to engine format and submit
            order_id = f"ml_order_{ts_value}_{idx}"

            # Determine order side - handle both LONG and SHORT
            side = OrderSide.BUY if order["side"].lower() == "long" else OrderSide.SELL

            # Respect single-position rule while allowing flattening trades
            if current_qty > 0 and side == OrderSide.BUY:
                continue  # would add to existing long
            if current_qty < 0 and side == OrderSide.SELL:
                continue  # would add to existing short

            # Create order with proper risk management
            order_obj = Order(
                order_id=order_id,
                symbol=order["symbol"],
                side=side,
                quantity=int(order["qty"]),
                order_type=OrderType.MARKET,
                timestamp=current_ts,
            )

            # Get current close price from bar_dict
            current_close = bar_dict.get("close")
            if current_close is None:
                continue  # Should not happen if bar_dict is valid

            # Add stop-loss and take-profit if available
            if "stop_loss_pct" in order and pd.notna(order["stop_loss_pct"]):
                # Calculate stop loss price based on order side
                if side == OrderSide.BUY:  # LONG position
                    stop_loss_price = current_close * (1 - order["stop_loss_pct"])
                else:  # SHORT position
                    stop_loss_price = current_close * (1 + order["stop_loss_pct"])
                order_obj.stop_loss = stop_loss_price

            if "take_profit_pct" in order and pd.notna(order["take_profit_pct"]):
                # Calculate take profit price based on order side
                if side == OrderSide.BUY:  # LONG position
                    take_profit_price = current_close * (1 + order["take_profit_pct"])
                else:  # SHORT position
                    take_profit_price = current_close * (1 - order["take_profit_pct"])
                order_obj.take_profit = take_profit_price

            engine.submit_order(order_obj)

            # Update local estimate assuming order reduces exposure
            qty_delta = int(order["qty"])
            if side == OrderSide.BUY:
                current_qty += qty_delta
            else:
                current_qty -= qty_delta

    return strategy


def _convert_result_to_artifacts(result: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Convert engine result to Sprint 6 artifacts format."""
    artifacts = {}

    # Extract data based on result type
    if hasattr(result, "__dict__"):
        # Object with attributes (BacktestResult)
        # Convert lists to DataFrames where needed
        trades_history = getattr(result, "trades_history", [])
        orders_history = getattr(result, "orders_history", [])
        positions_history = getattr(result, "positions_history", [])

        # Create proper trades DataFrame from unique trades only
        unique_trades = (
            _deduplicate_trades(trades_history) if trades_history else pd.DataFrame()
        )

        # Create fills DataFrame from unique fills (subset of trades)
        unique_fills = (
            _create_fills_from_trades(unique_trades)
            if not unique_trades.empty
            else pd.DataFrame()
        )

        # First create artifacts without metrics
        temp_artifacts = {
            "equity": getattr(result, "equity_curve", pd.DataFrame()),
            "positions": (
                pd.DataFrame(positions_history) if positions_history else pd.DataFrame()
            ),
            "trades": unique_trades,
            "orders": (
                pd.DataFrame(orders_history) if orders_history else pd.DataFrame()
            ),
            "fills": unique_fills,
        }

        artifacts = {
            "metrics": _extract_metrics_from_result(result, temp_artifacts),
            **temp_artifacts,
        }
    elif isinstance(result, dict):
        artifacts = result.copy()
    else:
        # Unknown result format
        artifacts = {}

    # Ensure all required artifacts exist
    required_artifacts = [
        "signals",
        "orders",
        "fills",
        "positions",
        "equity",
        "trades",
        "risk_rejects",
        "allocation_log",
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


def _deduplicate_trades(trades_history: list[dict[str, Any]]) -> pd.DataFrame:
    """Remove duplicate trade entries caused by forward-filling in backtest engine."""
    if not trades_history:
        return pd.DataFrame()

    # Convert to DataFrame
    trades_df = pd.DataFrame(trades_history)

    # Group by unique trade identifier (order_id + symbol + entry_timestamp)
    # and take only the first occurrence (actual trade execution)
    if "order_id" in trades_df.columns and "timestamp" in trades_df.columns:
        # Sort by timestamp to ensure first occurrence is the actual trade
        trades_df = trades_df.sort_values(["order_id", "timestamp", "symbol"])
        # Drop duplicates keeping the first (actual) trade
        unique_trades = trades_df.drop_duplicates(
            subset=["order_id", "symbol"], keep="first"
        )
    else:
        # Fallback: drop exact duplicates
        unique_trades = trades_df.drop_duplicates()

    return unique_trades.reset_index(drop=True)


def _create_fills_from_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Create fills DataFrame from trades (subset of trade data)."""
    if trades_df.empty:
        return pd.DataFrame()

    # Fills are a subset of trade data with fill-specific columns
    fill_columns = [
        "timestamp",
        "symbol",
        "side",
        "quantity",
        "price",
        "commission",
        "total_cost",
        "order_id",
    ]
    available_columns = [col for col in fill_columns if col in trades_df.columns]

    return trades_df[available_columns].copy()


def _extract_metrics_from_result(
    result: Any, artifacts: dict[str, Any] = None
) -> dict[str, Any]:
    """Extract metrics from BacktestResult object, but prioritize calculated metrics."""
    metrics = {}

    # Include any metrics dict provided by the engine result first
    if hasattr(result, "metrics") and isinstance(getattr(result, "metrics"), dict):
        metrics.update(result.metrics)

    # Extract performance metrics from BacktestResult (excluding trade counts)
    metric_fields = [
        "total_return",
        "annualized_return",
        "volatility",
        "sharpe_ratio",
        "max_drawdown",
        "max_drawdown_duration",
        "total_commissions",
        "total_slippage",
        "fill_rate",
    ]

    for field in metric_fields:
        if hasattr(result, field):
            metrics[field] = getattr(result, field)

    # Override trade-related metrics with our calculations from artifacts
    if artifacts and "trades" in artifacts and not artifacts["trades"].empty:
        calculated_metrics = _calculate_metrics(artifacts)
        trade_fields = [
            "total_trades",
            "trades",
            "win_rate",
            "avg_R",
            "total_pnl",
            "fees_total",
        ]
        for field in trade_fields:
            if field in calculated_metrics:
                calculated_value = calculated_metrics[field]
                existing_value = metrics.get(field)
                if existing_value and not calculated_value:
                    continue
                metrics[field] = calculated_value
    else:
        # Fallback to BacktestResult trade metrics (but they're usually 0)
        trade_fields = [
            "total_trades",
            "win_rate",
            "profit_factor",
            "winning_trades",
            "losing_trades",
        ]
        for field in trade_fields:
            if hasattr(result, field):
                metrics[field] = getattr(result, field)

    return metrics


def _calculate_metrics(artifacts: dict[str, Any]) -> dict[str, Any]:
    """Calculate basic metrics from artifacts."""
    metrics = {
        "total_trades": 0,
        "avg_R": 0.0,
        "fees_total": 0.0,
        "total_pnl": 0.0,
        "win_rate": 0.0,
        "trades": 0,  # For backward compatibility
        "trades_per_day": 0.0,
        "avg_trade_duration_minutes": 0.0,
    }

    fills_df = artifacts.get("fills")
    if fills_df is not None and not fills_df.empty:
        fills_df = fills_df.copy()
        if (
            "timestamp" in fills_df.columns
            and not pd.api.types.is_datetime64_any_dtype(fills_df["timestamp"])
        ):
            fills_df["timestamp"] = pd.to_datetime(
                fills_df["timestamp"], utc=True, errors="coerce"
            )

        fills_df = fills_df.sort_values("timestamp").reset_index(drop=True)
        gross_pnl = 0.0
        wins = 0
        trade_count = 0
        durations: list[float] = []

        # Track fees directly from fills
        if "commission" in fills_df.columns:
            metrics["fees_total"] = fills_df["commission"].sum()

        i = 0
        while i + 1 < len(fills_df):
            entry = fills_df.iloc[i]
            exit_fill = fills_df.iloc[i + 1]

            if entry["side"] == exit_fill["side"]:
                i += 1
                continue

            qty = min(entry["quantity"], exit_fill["quantity"])
            if qty <= 0:
                i += 2
                continue

            entry_price = entry["price"]
            exit_price = exit_fill["price"]

            if entry["side"] == "SELL":
                pnl = (entry_price - exit_price) * qty
            else:
                pnl = (exit_price - entry_price) * qty

            gross_pnl += pnl
            trade_count += 1
            if pnl > 0:
                wins += 1

            if isinstance(entry["timestamp"], pd.Timestamp) and isinstance(
                exit_fill["timestamp"], pd.Timestamp
            ):
                durations.append(
                    (exit_fill["timestamp"] - entry["timestamp"]).total_seconds() / 60.0
                )

            i += 2

        metrics["total_trades"] = trade_count
        metrics["trades"] = trade_count
        net_pnl = gross_pnl - metrics["fees_total"]
        metrics["total_pnl"] = net_pnl
        metrics["win_rate"] = wins / trade_count if trade_count else 0.0
        if trade_count:
            metrics["avg_R"] = net_pnl / trade_count

        unique_days = fills_df["timestamp"].dt.date.nunique()
        if unique_days:
            metrics["trades_per_day"] = trade_count / unique_days
        if durations:
            metrics["avg_trade_duration_minutes"] = sum(durations) / len(durations)

    # Calculate fees from fills if available
    if "fills" in artifacts and not artifacts["fills"].empty:
        fills_df = artifacts["fills"]
        if "commission" in fills_df.columns:
            metrics["fees_total"] = fills_df["commission"].sum()

    return metrics


def _write_artifacts(artifacts: dict[str, Any], config: dict[str, Any]):
    """Write backtest artifacts to disk."""
    artifacts_dir = Path(config["artifacts_path"])
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for name, df in artifacts.items():
        if isinstance(df, pd.DataFrame):
            if not df.empty:
                if "tags" in df.columns:
                    df["tags"] = df["tags"].astype(str)
                df.to_parquet(artifacts_dir / f"{name}.parquet", index=False)
        elif isinstance(df, dict):
            with open(artifacts_dir / f"{name}.json", "w") as f:
                json.dump(_json_safe(df), f, indent=4)


# Import hash function
from qx_core.hashers import hash_dict


def _json_safe(value: Any) -> Any:
    """Convert nested structures to JSON-serializable types."""

    if value.__class__.__module__ == "unittest.mock":  # pragma: no cover - test doubles
        return str(value)

    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.total_seconds()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            item_value = value.item()
        except Exception:  # pragma: no cover - fallback for unusual scalars
            return str(value)
        if item_value is value:
            return str(value)
        return _json_safe(item_value)
    if isinstance(value, (float, int, str, bool)) or value is None:
        return value
    return str(value)
