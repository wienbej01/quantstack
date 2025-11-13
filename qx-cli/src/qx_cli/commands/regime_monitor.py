"""
Regime monitoring CLI commands for tracking regime behavior and performance.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import click

from qx_cli.main import cli
from qx_core.regime.detector import RegimeDetectorRules
from qx_core.regime.monitoring import RegimeMonitor, RegimeMonitoringMetrics, RegimeType
from qx_data.gold_loader import GoldLoader
from qx_features.core_basics import CoreBasicsFeatures


@cli.group()
def regime_monitor():
    """Regime monitoring and analysis commands."""
    pass


@regime_monitor.command()
@click.option("--symbol", "-s", required=True, help="Symbol to monitor")
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", help="End date (YYYY-MM-DD, default: start-date)")
@click.option("--config", "-c", help="Regime configuration file")
@click.option("--output", "-o", help="Output file for metrics (JSON)")
@click.option("--live", is_flag=True, help="Run in live monitoring mode")
@click.option("--update-interval", default=60, help="Update interval in seconds for live mode")
def monitor(
    symbol: str,
    start_date: str,
    end_date: str | None,
    config: str | None,
    output: str | None,
    live: bool,
    update_interval: int,
):
    """Monitor regime behavior for a symbol."""

    # Parse dates
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date else start_dt

    click.echo(f"Starting regime monitoring for {symbol}")
    click.echo(f"Period: {start_dt.date()} to {end_dt.date()}")

    # Initialize regime detector
    detector = RegimeDetectorRules()
    if config:
        detector.load_config(config)
        click.echo(f"Loaded configuration from {config}")

    # Initialize monitor
    monitor = RegimeMonitor(symbol)

    # Load data
    loader = GoldLoader("/home/jacobw/gcs-mount")
    features = CoreBasicsFeatures()

    try:
        # Process each day
        current_dt = start_dt
        while current_dt <= end_dt:
            click.echo(f"Processing {current_dt.date()}...")

            # Load bars for the day
            bars_df = loader.load_bars(
                symbols=[symbol],
                start_date=current_dt.strftime("%Y-%m-%d"),
                end_date=current_dt.strftime("%Y-%m-%d"),
            )

            if bars_df.empty:
                click.echo(f"No data for {current_dt.date()}, skipping...")
                current_dt += timedelta(days=1)
                continue

            # Calculate features
            feature_df = features.calculate(bars_df)

            # Process each bar
            for _, row in feature_df.iterrows():
                timestamp = row.name.to_pydatetime()

                # Detect regime
                regime_signal = detector.evaluate_single_row(row, symbol)
                regime = regime_signal.regime if regime_signal else RegimeType.OFF
                confidence = regime_signal.confidence if regime_signal else 0.0

                # Update monitor
                monitor.update(timestamp, regime, confidence, row.to_dict())

                if live:
                    # Print real-time status
                    if len(feature_df) % 100 == 0:  # Update every 100 bars
                        monitor.get_real_time_summary()
                        click.echo(
                            f"  {timestamp.strftime('%H:%M:%S')} - "
                            f"Regime: {regime.value} "
                            f"(confidence: {confidence:.2f})"
                        )

            current_dt += timedelta(days=1)

        # Finalize monitoring
        metrics = monitor.finalize()

        # Display results
        display_regime_metrics(metrics)

        # Save results if requested
        if output:
            save_metrics(metrics, output)
            click.echo(f"Metrics saved to {output}")

    except Exception as e:
        click.echo(f"Error during monitoring: {e}", err=True)
        sys.exit(1)


@regime_monitor.command()
@click.option("--metrics-file", "-m", required=True, help="Metrics file (JSON)")
@click.option("--output-dir", "-o", help="Output directory for reports")
def analyze(metrics_file: str, output_dir: str | None):
    """Analyze regime monitoring metrics."""

    # Load metrics
    metrics = load_metrics(metrics_file)
    if not metrics:
        click.echo(f"Could not load metrics from {metrics_file}", err=True)
        sys.exit(1)

    click.echo(f"Analyzing regime metrics for {metrics.symbol}")

    # Generate analysis reports
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save transition matrix
        transition_df = metrics.export_transition_matrix()
        transition_file = output_path / f"{metrics.symbol}_transition_matrix.csv"
        transition_df.to_csv(transition_file)
        click.echo(f"Transition matrix saved to {transition_file}")

        # Save detailed analysis
        analysis_file = output_path / f"{metrics.symbol}_regime_analysis.json"
        with open(analysis_file, "w") as f:
            json.dump(metrics.get_comprehensive_summary(), f, indent=2, default=str)
        click.echo(f"Detailed analysis saved to {analysis_file}")

    # Display analysis
    display_regime_analysis(metrics)


@regime_monitor.command()
@click.option("--symbols", "-s", multiple=True, required=True, help="Symbols to compare")
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", help="End date (YYYY-MM-DD, default: start-date)")
@click.option("--output", "-o", help="Output file for comparison (JSON)")
def compare(symbols: tuple, start_date: str, end_date: str | None, output: str | None):
    """Compare regime behavior across multiple symbols."""

    symbols_list = list(symbols)
    click.echo(f"Comparing regime behavior across {len(symbols_list)} symbols")

    all_metrics = {}

    for symbol in symbols_list:
        click.echo(f"Processing {symbol}...")

        # Run monitoring for this symbol
        monitor = RegimeMonitor(symbol)
        detector = RegimeDetectorRules()
        loader = GoldLoader("/home/jacobw/gcs-mount")
        features = CoreBasicsFeatures()

        # Process data (simplified for comparison)
        try:
            bars_df = loader.load_bars(
                symbols=[symbol], start_date=start_date, end_date=end_date or start_date
            )

            if bars_df.empty:
                click.echo(f"No data for {symbol}, skipping...")
                continue

            feature_df = features.calculate(bars_df)

            for _, row in feature_df.iterrows():
                timestamp = row.name.to_pydatetime()
                regime_signal = detector.evaluate_single_row(row, symbol)
                regime = regime_signal.regime if regime_signal else RegimeType.OFF
                confidence = regime_signal.confidence if regime_signal else 0.0
                monitor.update(timestamp, regime, confidence, row.to_dict())

            all_metrics[symbol] = monitor.finalize()

        except Exception as e:
            click.echo(f"Error processing {symbol}: {e}")
            continue

    # Generate comparison report
    comparison = generate_comparison_report(all_metrics)
    display_comparison_report(comparison)

    # Save comparison if requested
    if output:
        with open(output, "w") as f:
            json.dump(comparison, f, indent=2, default=str)
        click.echo(f"Comparison report saved to {output}")


def display_regime_metrics(metrics: RegimeMonitoringMetrics) -> None:
    """Display regime monitoring metrics."""
    click.echo("\n" + "=" * 60)
    click.echo(f"REGIME MONITORING SUMMARY FOR {metrics.symbol.upper()}")
    click.echo("=" * 60)

    # Overall stats
    click.echo("\nOverall Statistics:")
    click.echo(f"  Total bars monitored: {metrics.total_bars:,}")
    click.echo(f"  Regime changes: {metrics.regime_changes}")
    click.echo(f"  Unique regimes seen: {len(metrics.unique_regimes_seen)}")
    click.echo(f"  Health score: {metrics.get_health_score():.2f}")
    click.echo(f"  Avg detection confidence: {metrics.detection_confidence_avg:.2f}")

    # Regime state metrics
    click.echo("\nRegime State Analysis:")
    for regime, state_metrics in metrics.state_metrics.items():
        if state_metrics.entry_count > 0:
            click.echo(f"  {regime.value}:")
            click.echo(f"    Entries: {state_metrics.entry_count}")
            click.echo(f"    Avg duration: {state_metrics.avg_duration_bars:.1f} bars")
            click.echo(f"    Max duration: {state_metrics.max_duration_bars} bars")
            click.echo(f"    Total time: {state_metrics.total_duration_minutes} min")

    # Transition metrics
    trans_metrics = metrics.transition_metrics
    click.echo("\nRegime Transition Analysis:")
    click.echo(f"  Total transitions: {trans_metrics.total_transitions}")
    click.echo(f"  Regime flips: {trans_metrics.regime_flips}")
    click.echo(f"  Stability ratio: {trans_metrics.stability_ratio:.2%}")
    click.echo(f"  Avg time between flips: {trans_metrics.avg_time_between_flips:.1f} min")

    # Performance metrics
    perf_metrics = metrics.performance_metrics
    if perf_metrics.regime_trades:
        click.echo("\nPerformance by Regime:")
        for regime, trades in perf_metrics.regime_trades.items():
            if trades > 0:
                click.echo(f"  {regime.value}:")
                click.echo(f"    Trades: {trades}")
                click.echo(f"    Win rate: {perf_metrics.regime_win_rate[regime]:.1%}")
                click.echo(f"    Total PnL: {perf_metrics.regime_pnl[regime]:.2f}")
                click.echo(f"    Sharpe: {perf_metrics.regime_sharpe[regime]:.2f}")

    click.echo("\n" + "=" * 60)


def display_regime_analysis(metrics: RegimeMonitoringMetrics) -> None:
    """Display detailed regime analysis."""
    summary = metrics.get_comprehensive_summary()

    click.echo("\n" + "=" * 60)
    click.echo("DETAILED REGIME ANALYSIS")
    click.echo("=" * 60)

    # Health assessment
    health_score = summary["metadata"]["health_score"]
    click.echo(f"\nSystem Health Assessment: {health_score:.2f}")

    if health_score >= 0.8:
        click.echo("  Status: EXCELLENT - Regime detection is highly stable and reliable")
    elif health_score >= 0.6:
        click.echo("  Status: GOOD - Regime detection is functioning well")
    elif health_score >= 0.4:
        click.echo("  Status: FAIR - Some instability detected, monitor closely")
    else:
        click.echo("  Status: POOR - Significant instability, investigation needed")

    # Regime stability insights
    click.echo("\nRegime Stability Insights:")
    flip_frequency = summary["transition_metrics"]["flip_frequency_per_hour"]
    if flip_frequency < 0.1:
        click.echo("  • Very stable regime behavior (low flip frequency)")
    elif flip_frequency < 0.5:
        click.echo("  • Moderate regime stability")
    else:
        click.echo("  • High regime volatility (frequent flips)")

    # Performance insights
    if summary["performance_metrics"]["regime_breakdown"]:
        click.echo("\nPerformance Insights:")
        best_regime = max(
            summary["performance_metrics"]["regime_breakdown"].items(),
            key=lambda x: x[1]["sharpe"],
        )
        worst_regime = min(
            summary["performance_metrics"]["regime_breakdown"].items(),
            key=lambda x: x[1]["sharpe"],
        )

        click.echo(
            f"  • Best performing regime: {best_regime[0]} (Sharpe: {best_regime[1]['sharpe']:.2f})"
        )
        click.echo(
            f"  • Worst performing regime: {worst_regime[0]} (Sharpe: {worst_regime[1]['sharpe']:.2f})"
        )

    # Recommendations
    click.echo("\nRecommendations:")
    if flip_frequency > 0.5:
        click.echo("  • Consider increasing regime persistence thresholds")
    if health_score < 0.6:
        click.echo("  • Review regime detection parameters")
        click.echo("  • Check data quality and feature calculations")

    click.echo("\n" + "=" * 60)


def generate_comparison_report(all_metrics: dict[str, RegimeMonitoringMetrics]) -> dict[str, Any]:
    """Generate comparison report across multiple symbols."""
    comparison = {
        "metadata": {
            "symbols_analyzed": list(all_metrics.keys()),
            "analysis_timestamp": datetime.now().isoformat(),
        },
        "symbol_comparison": {},
        "aggregate_metrics": {},
    }

    # Individual symbol metrics
    for symbol, metrics in all_metrics.items():
        comparison["symbol_comparison"][symbol] = {
            "health_score": metrics.get_health_score(),
            "total_bars": metrics.total_bars,
            "regime_changes": metrics.regime_changes,
            "unique_regimes": len(metrics.unique_regimes_seen),
            "avg_confidence": metrics.detection_confidence_avg,
            "stability_ratio": metrics.transition_metrics.stability_ratio,
            "flip_frequency": metrics.transition_metrics.flip_frequency_per_hour,
        }

    # Aggregate metrics
    health_scores = [m.get_health_score() for m in all_metrics.values()]
    comparison["aggregate_metrics"] = {
        "avg_health_score": sum(health_scores) / len(health_scores),
        "best_performing_symbol": max(
            all_metrics.keys(), key=lambda s: all_metrics[s].get_health_score()
        ),
        "worst_performing_symbol": min(
            all_metrics.keys(), key=lambda s: all_metrics[s].get_health_score()
        ),
        "regime_diversity": {
            symbol: len(m.unique_regimes_seen) for symbol, m in all_metrics.items()
        },
    }

    return comparison


def display_comparison_report(comparison: dict[str, Any]) -> None:
    """Display comparison report."""
    click.echo("\n" + "=" * 60)
    click.echo("REGIME BEHAVIOR COMPARISON REPORT")
    click.echo("=" * 60)

    # Aggregate metrics
    agg = comparison["aggregate_metrics"]
    click.echo("\nAggregate Summary:")
    click.echo(f"  Symbols analyzed: {len(comparison['metadata']['symbols_analyzed'])}")
    click.echo(f"  Average health score: {agg['avg_health_score']:.2f}")
    click.echo(f"  Best performing: {agg['best_performing_symbol']}")
    click.echo(f"  Worst performing: {agg['worst_performing_symbol']}")

    # Symbol-by-symbol comparison
    click.echo("\nSymbol-by-Symbol Comparison:")
    for symbol, metrics in comparison["symbol_comparison"].items():
        click.echo(f"  {symbol}:")
        click.echo(f"    Health score: {metrics['health_score']:.2f}")
        click.echo(f"    Regime changes: {metrics['regime_changes']}")
        click.echo(f"    Stability: {metrics['stability_ratio']:.2%}")
        click.echo(f"    Flip frequency: {metrics['flip_frequency']:.3f}/hour")

    click.echo("\n" + "=" * 60)


def save_metrics(metrics: RegimeMonitoringMetrics, output_file: str) -> None:
    """Save metrics to JSON file."""
    data = metrics.get_comprehensive_summary()

    with open(output_file, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_metrics(metrics_file: str) -> RegimeMonitoringMetrics | None:
    """Load metrics from JSON file."""
    try:
        with open(metrics_file) as f:
            data = json.load(f)

        # Recreate metrics object from saved data
        metadata = data["metadata"]
        metrics = RegimeMonitoringMetrics(
            symbol=metadata["symbol"],
            start_time=datetime.fromisoformat(metadata["start_time"]),
            end_time=(
                datetime.fromisoformat(metadata["end_time"]) if metadata["end_time"] else None
            ),
        )

        # Restore other properties
        metrics.total_bars = metadata["total_bars"]
        metrics.regime_changes = metadata["regime_changes"]
        metrics.unique_regimes_seen = {RegimeType(r) for r in metadata["unique_regimes_seen"]}

        return metrics

    except Exception as e:
        click.echo(f"Error loading metrics: {e}", err=True)
        return None


if __name__ == "__main__":
    regime_monitor()
