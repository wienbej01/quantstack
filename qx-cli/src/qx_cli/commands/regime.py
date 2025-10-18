"""Regime detection commands for CLI."""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import typer
import yaml

# Add parent directories to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.order import OrderSide, OrderType
from qx_core.regime.detector import create_regime_detector
from qx_core.regime_config import RegimeConfig, validate_regime_config
from qx_core.schemas import RegimeSignal, RegimeType
from qx_data.gold_loader import load_bars
from qx_features.registry import apply

# Create regime app
app = typer.Typer(help="Regime detection and analysis commands")


@app.command()
def backtest(
    config_path: str = typer.Argument(..., help="Path to regime configuration file"),
    output_dir: str = typer.Option("runs", help="Output directory for results"),
    start_date: str = typer.Option(None, help="Start date (YYYY-MM-DD)"),
    end_date: str = typer.Option(None, help="End date (YYYY-MM-DD)"),
    symbols: str = typer.Option(None, help="Comma-separated list of symbols"),
    verbose: bool = typer.Option(False, help="Verbose output"),
):
    """Run regime-aware backtest."""

    # Load configuration
    full_config = _load_full_config(config_path)
    config = _load_regime_config(config_path)
    if not config:
        typer.echo(f"Error: Could not load configuration from {config_path}", err=True)
        raise typer.Exit(1)

    if verbose:
        typer.echo(f"Loaded regime configuration: {config.enabled}")
        if config.enabled:
            typer.echo(f"Model: {config.model}")
            typer.echo(f"Persistence bars: {config.persistence_bars}")
            typer.echo(f"Strategy map: {config.strategy_map}")

    # Set up symbols
    if symbols:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        symbol_list = full_config.get(
            "symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
        )

    if verbose:
        typer.echo(f"Symbols: {symbol_list}")

    # Set up dates
    if not start_date:
        start_date = full_config.get("start_date", "2024-01-02")
    if not end_date:
        end_date = full_config.get("end_date", "2024-01-31")

    if verbose:
        typer.echo(f"Date range: {start_date} to {end_date}")

    # Load data
    gold_root = full_config.get("gold_root", "/home/jacobw/gcs-mount")
    family = full_config.get("family", "bars_1m")

    # Determine date partitions for loading
    daily_dates = _generate_date_range(start_date, end_date)
    if family == "bars_1m":
        load_dates = sorted({d[:7] for d in daily_dates})  # YYYY-MM
    else:
        load_dates = daily_dates

    try:
        data = load_bars(
            root=gold_root,
            family=family,
            symbols=symbol_list,
            dates=load_dates,
        )
        typer.echo(f"Loaded {len(data)} bars for {len(symbol_list)} symbols")
        data = data.sort_values(["symbol", "ts"]).reset_index(drop=True)
    except Exception as e:
        typer.echo(f"Error loading data: {e}", err=True)
        raise typer.Exit(1)

    # Apply features
    try:
        features_config = _normalize_feature_config(
            full_config.get(
                "features",
                [
                    {"type": "regime_basics", "params": {}},
                    {"type": "core_basics", "params": {}},
                ],
            )
        )
        data_with_features = apply(data, features_config)
        data_with_features = data_with_features.sort_values(["ts", "symbol"]).reset_index(drop=True)
        typer.echo("Applied regime and core features")
    except Exception as e:
        typer.echo(f"Error applying features: {e}", err=True)
        raise typer.Exit(1)

    # Create backtest engine with regime configuration
    try:
        backtest_config = BacktestConfig(
            initial_cash=1_000_000.0,
            regime_config=config.dict(),
            strategy_map=config.strategy_map,
        )

        engine = BacktestEngine(backtest_config)

        if verbose and config.enabled:
            typer.echo("Regime detection enabled in backtest engine")

    except Exception as e:
        typer.echo(f"Error creating backtest engine: {e}", err=True)
        raise typer.Exit(1)

    # Define simple strategy function that respects regime gating
    def regime_aware_strategy(engine: BacktestEngine, bar: dict[str, Any]) -> None:
        """Simple strategy that respects regime gating."""
        # Check if strategy is allowed in current regime
        strategy_name = "simple_test"
        if not engine.is_strategy_allowed(strategy_name):
            return  # Skip trading in disallowed regimes

        # Simple VWAP reversion logic
        symbol = bar["symbol"]
        close = bar["close"]

        # Get features from engine (simplified - in real implementation
        # features would be passed separately)
        vwap_signal = bar.get("f__ta__vwap_30", close)

        # Generate signal
        if close < vwap_signal * 0.995:  # 0.5% below VWAP
            # Buy signal
            if engine.get_position(symbol) is None:
                qty = 100  # Simple fixed quantity
                order = engine.order_factory.create_order(
                    symbol=symbol, side=OrderSide.BUY, order_type=OrderType.MARKET,
                    quantity=qty, price=close, tags={"tag": "regime_test"}
                )
                engine.submit_order(order)

        elif close > vwap_signal * 1.005:  # 0.5% above VWAP
            # Sell signal
            position = engine.get_position(symbol)
            if position and position.quantity > 0:
                order = engine.order_factory.create_market_order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=position.quantity,
                    tags={"policy": "regime_test"},
                )
                engine.submit_order(order)

    # Run backtest
    try:
        result = engine.run(data_with_features, regime_aware_strategy)
        typer.echo("Backtest completed successfully")

        # Get regime statistics
        regime_stats = engine.get_regime_statistics()
        typer.echo(f"Regime statistics: {regime_stats}")

        # Save results
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save results
        results_file = (
            output_path
            / f"regime_backtest_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        results_data = {
            "performance": result.to_dict()["performance"],
            "trading": result.to_dict()["trading"],
            "regime_statistics": regime_stats,
            "configuration": config.dict(),
        }

        with open(results_file, "w") as f:
            json.dump(results_data, f, indent=2, default=str)

        typer.echo(f"Results saved to {results_file}")

        # Print summary
        typer.echo("\n=== Backtest Summary ===")
        typer.echo(f"Total return: {result.total_return:.2%}")
        typer.echo(f"Sharpe ratio: {result.sharpe_ratio:.2f}")
        typer.echo(f"Max drawdown: {result.max_drawdown:.2%}")
        typer.echo(f"Win rate: {result.win_rate:.2%}")
        typer.echo(f"Total trades: {result.total_trades}")

        if regime_stats.get("regime_detection_enabled"):
            typer.echo(f"Current regime: {regime_stats.get('current_regime')}")
            if "regime_distribution" in regime_stats:
                typer.echo("Regime distribution:")
                for regime, count in regime_stats["regime_distribution"].items():
                    typer.echo(f"  {regime}: {count}")

    except Exception as e:
        typer.echo(f"Error running backtest: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def analyze(
    data_path: str = typer.Argument(..., help="Path to CSV data with regime features"),
    output_path: str = typer.Option(
        "regime_analysis.json", help="Output file for analysis results"
    ),
    detector_config: str = typer.Option(
        None, help="Path to detector configuration file"
    ),
):
    """Analyze regime detection on historical data."""

    # Load data
    try:
        data = pd.read_csv(data_path)
        typer.echo(f"Loaded {len(data)} rows from {data_path}")
    except Exception as e:
        typer.echo(f"Error loading data: {e}", err=True)
        raise typer.Exit(1)

    # Create detector
    try:
        if detector_config:
            with open(detector_config, "r") as f:
                config_dict = json.load(f)
            detector = create_regime_detector(config_dict.get("detector_params", {}))
        else:
            detector = create_regime_detector()

        typer.echo("Created regime detector")
    except Exception as e:
        typer.echo(f"Error creating detector: {e}", err=True)
        raise typer.Exit(1)

    # Run analysis
    try:
        results = []

        # Group by timestamp and evaluate regimes
        for ts, group in data.groupby("ts"):
            if "f__regime__warmup_ok" in group.columns:
                warm_data = group[group["f__regime__warmup_ok"]]
            else:
                warm_data = group

            if not warm_data.empty:
                signal = detector.evaluate(warm_data, ts)
                results.append(signal)

        typer.echo(f"Analyzed {len(results)} timestamps")

        # Generate statistics
        regime_counts = {}
        confidence_by_regime = {}

        for signal in results:
            regime = signal.regime.value
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

            if regime not in confidence_by_regime:
                confidence_by_regime[regime] = []
            confidence_by_regime[regime].append(signal.confidence)

        # Calculate average confidence by regime
        avg_confidence = {}
        for regime, confidences in confidence_by_regime.items():
            avg_confidence[regime] = sum(confidences) / len(confidences)

        # Get detector statistics
        detector_stats = detector.get_statistics()

        # Prepare results
        analysis_results = {
            "data_file": data_path,
            "total_timestamps": len(results),
            "regime_distribution": regime_counts,
            "average_confidence": avg_confidence,
            "detector_statistics": detector_stats,
            "regime_history": [
                {
                    "ts": signal.ts,
                    "regime": signal.regime.value,
                    "confidence": signal.confidence,
                    "persistence_count": signal.persistence_count,
                }
                for signal in results
            ],
        }

        # Save results
        with open(output_path, "w") as f:
            json.dump(analysis_results, f, indent=2, default=str)

        typer.echo(f"Analysis saved to {output_path}")

        # Print summary
        typer.echo("\n=== Regime Analysis Summary ===")
        typer.echo(f"Total timestamps analyzed: {len(results)}")
        typer.echo("Regime distribution:")
        for regime, count in regime_counts.items():
            percentage = (count / len(results)) * 100
            typer.echo(f"  {regime}: {count} ({percentage:.1f}%)")

        typer.echo("Average confidence by regime:")
        for regime, avg_conf in avg_confidence.items():
            typer.echo(f"  {regime}: {avg_conf:.3f}")

        typer.echo(f"Detector change rate: {detector_stats['change_rate']:.3f}")
        typer.echo(f"Average persistence: {detector_stats['avg_persistence']:.1f} bars")

    except Exception as e:
        typer.echo(f"Error during analysis: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def validate_config(
    config_path: str = typer.Argument(..., help="Path to regime configuration file")
):
    """Validate regime configuration file."""

    try:
        config_dict = _read_regime_section(config_path)
        if not config_dict:
            raise ValueError("No regime configuration found")

        # Validate configuration
        config = validate_regime_config(config_dict)

        typer.echo(f"✓ Configuration {config_path} is valid")
        typer.echo(f"  Enabled: {config.enabled}")
        typer.echo(f"  Model: {config.model}")
        typer.echo(f"  Persistence bars: {config.persistence_bars}")
        typer.echo(f"  Cooldown minutes: {config.cooldown_minutes}")

        typer.echo("  Strategy mapping:")
        for regime, strategies in config.strategy_map.items():
            typer.echo(f"    {regime}: {strategies}")

        typer.echo("  Feature configuration:")
        for key, value in config.features.items():
            typer.echo(f"    {key}: {value}")

        if config.detector_params:
            typer.echo("  Detector parameters:")
            for key, value in config.detector_params.items():
                typer.echo(f"    {key}: {value}")

    except Exception as e:
        typer.echo(f"✗ Configuration validation failed: {e}", err=True)
        raise typer.Exit(1)


def _load_regime_config(config_path: str) -> RegimeConfig | None:
    """Load regime configuration from file."""
    try:
        config_dict = _read_regime_section(config_path)
        if not config_dict:
            return None
        return validate_regime_config(config_dict)
    except Exception:
        return None


def _load_full_config(config_path: str) -> dict[str, Any]:
    """Load full configuration (YAML/JSON)."""
    return _parse_config_file(config_path)


def _read_regime_section(config_path: str) -> dict[str, Any] | None:
    """Read configuration file and extract the regime section."""
    data = _parse_config_file(config_path)

    if not isinstance(data, dict):
        return None

    # Accept nested regime section or direct configuration
    if "regime" in data and isinstance(data["regime"], dict):
        return data["regime"]

    # Some configs might store under 'regime_config'
    if "regime_config" in data and isinstance(data["regime_config"], dict):
        return data["regime_config"]

    return data


def _parse_config_file(config_path: str) -> dict[str, Any]:
    """Parse a configuration file supporting JSON or YAML formats."""
    with open(config_path, "r") as f:
        raw_text = f.read()

    # Try JSON first for backwards compatibility
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        data = yaml.safe_load(raw_text)

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise ValueError("Configuration must be a JSON or YAML object")

    return data


def _normalize_feature_config(config_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize feature configuration entries for the registry apply helper."""
    normalized: list[dict[str, Any]] = []
    for item in config_items:
        if not isinstance(item, dict):
            continue
        feature_type = item.get("type") or item.get("name")
        if not feature_type:
            continue
        params = item.get("params", {})
        normalized.append({"type": feature_type, "params": params})
    return normalized or [{"type": "regime_basics", "params": {}}, {"type": "core_basics", "params": {}}]


def _generate_date_range(start_date: str, end_date: str) -> list[str]:
    """Generate list of dates between start and end."""
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    dates = []
    current = start
    while current <= end:
        # Skip weekends
        if current.weekday() < 5:
            dates.append(current.strftime("%Y-%m-%d"))
        current += pd.Timedelta(days=1)

    return dates


if __name__ == "__main__":
    app()
