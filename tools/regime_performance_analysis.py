#!/usr/bin/env python3
"""
Regime Performance Analysis Tool

Compares strategy performance with and without regime gating to validate
the effectiveness of regime detection in improving trading results.

Usage:
    python regime_performance_analysis.py --config experiments/regime/strategy_basic.yaml
    python regime_performance_analysis.py --config experiments/regime/strategy_basic.yaml --baseline experiments/regime/disabled.yaml
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_core.regime_config import RegimeConfig, validate_regime_config
from qx_data.gold_loader import load_bars
from qx_features.registry import apply


class RegimePerformanceAnalyzer:
    """Analyzes performance impact of regime detection."""

    def __init__(self):
        self.results = {}
        self.comparison_data = {}

    def load_configuration(self, config_path: str) -> Dict[str, Any]:
        """Load and validate configuration from YAML/JSON file."""
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        try:
            # Try JSON first
            with open(config_path, "r") as f:
                config_dict = json.load(f)
        except json.JSONDecodeError:
            # Try YAML (requires pyyaml)
            try:
                import yaml

                with open(config_path, "r") as f:
                    config_dict = yaml.safe_load(f)
            except ImportError:
                raise ImportError(
                    "PyYAML required for YAML config files. Install with: pip install pyyaml"
                )

        # Validate regime configuration if present
        if "regime" in config_dict:
            regime_config = validate_regime_config(config_dict["regime"])
            config_dict["regime"] = regime_config.dict()

        return config_dict

    def generate_sample_data(
        self, symbols: List[str], start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Generate sample market data for testing."""
        dates = pd.date_range(start=start_date, end=end_date, freq="B")  # Business days
        data = []

        for symbol in symbols:
            for date in dates:
                # Generate intraday data (hourly for simplicity)
                for hour in range(9, 16):  # 9 AM to 3 PM
                    base_price = 100.0 * (1 + hash(symbol) % 50 / 100.0)

                    # Add realistic market dynamics
                    daily_return = np.random.normal(0, 0.02)  # 2% daily volatility
                    intraday_noise = np.random.normal(0, 0.005)  # 0.5% intraday noise

                    price = base_price * (1 + daily_return) * (1 + intraday_noise)

                    # Generate OHLCV
                    high = price * (1 + abs(np.random.normal(0, 0.002)))
                    low = price * (1 - abs(np.random.normal(0, 0.002)))
                    open_price = low + (high - low) * np.random.random()
                    close = price
                    volume = int(np.random.lognormal(10, 1))

                    data.append(
                        {
                            "ts": int(
                                datetime.combine(
                                    date, datetime.min.time().replace(hour=hour)
                                ).timestamp()
                                * 1e9
                            ),
                            "symbol": symbol,
                            "open": open_price,
                            "high": high,
                            "low": low,
                            "close": close,
                            "volume": volume,
                        }
                    )

        return pd.DataFrame(data)

    def run_backtest(
        self, config: Dict[str, Any], data: pd.DataFrame, experiment_name: str
    ) -> Dict[str, Any]:
        """Run single backtest with given configuration."""
        print(f"Running backtest: {experiment_name}")

        # Add features
        features_config = []
        if config.get("regime", {}).get("enabled", False):
            features_config.append({"type": "regime_basics"})

        features_config.append({"type": "core_basics"})
        data_with_features = apply(data, features_config)

        # Configure backtest engine
        backtest_config = BacktestConfig(
            initial_cash=config.get("backtest", {}).get("initial_equity", 1000000),
            regime_config=config.get("regime"),
            strategy_map=config.get("regime", {}).get("strategy_map", {}),
        )

        engine = BacktestEngine(backtest_config)

        # Define strategy
        trades = []

        def test_strategy(engine, bar):
            # Simple VWAP reversion strategy
            vwap = bar.get("f__ta__vwap_30")
            if not vwap:
                return

            close = bar["close"]
            symbol = bar["symbol"]

            # Get current position
            position = engine.get_position(symbol)

            # Entry signals
            if position is None:
                if close < vwap * 0.995:  # 0.5% below VWAP
                    order = engine.order_factory.create_order(
                        symbol=symbol,
                        side="BUY",
                        qty=100,
                        entry=close,
                        tag="vwap_revert",
                    )
                    engine.submit_order(order)
                    trades.append(
                        {
                            "timestamp": bar["ts"],
                            "symbol": symbol,
                            "action": "BUY",
                            "price": close,
                            "regime": (
                                engine.get_current_regime().value
                                if engine.get_current_regime()
                                else None
                            ),
                        }
                    )

            # Exit signals
            elif position and position.quantity > 0:
                if close > vwap * 1.005 or close < vwap * 0.98:  # Exit conditions
                    order = engine.order_factory.create_order(
                        symbol=symbol,
                        side="SELL",
                        qty=position.quantity,
                        entry=close,
                        tag="vwap_revert_exit",
                    )
                    engine.submit_order(order)
                    trades.append(
                        {
                            "timestamp": bar["ts"],
                            "symbol": symbol,
                            "action": "SELL",
                            "price": close,
                            "regime": (
                                engine.get_current_regime().value
                                if engine.get_current_regime()
                                else None
                            ),
                        }
                    )

        # Run backtest
        result = engine.run(data_with_features, test_strategy)

        # Collect results
        performance = result.to_dict()["performance"]
        trading = result.to_dict()["trading"]

        # Get regime statistics
        regime_stats = engine.get_regime_statistics()
        regime_history = engine.get_regime_history()

        return {
            "experiment_name": experiment_name,
            "config": config,
            "performance": performance,
            "trading": trading,
            "regime_statistics": regime_stats,
            "regime_history": regime_history,
            "trades": trades,
            "equity_curve": (
                result.equity_curve.to_dict("records")
                if hasattr(result.equity_curve, "to_dict")
                else []
            ),
        }

    def compare_performance(
        self,
        enabled_config: Dict[str, Any],
        disabled_config: Dict[str, Any],
        data: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Compare performance between regime-enabled and disabled configurations."""

        # Run both backtests
        enabled_result = self.run_backtest(enabled_config, data, "regime_enabled")
        disabled_result = self.run_backtest(disabled_config, data, "regime_disabled")

        # Calculate performance differences
        comparison = {
            "enabled_performance": enabled_result["performance"],
            "disabled_performance": disabled_result["performance"],
            "enabled_trading": enabled_result["trading"],
            "disabled_trading": disabled_result["trading"],
            "regime_enabled_stats": enabled_result["regime_statistics"],
            "regime_disabled_stats": disabled_result["regime_statistics"],
            "enabled_trades": enabled_result["trades"],
            "disabled_trades": disabled_result["trades"],
        }

        # Calculate performance improvements
        if (
            enabled_result["performance"]["total_return"]
            and disabled_result["performance"]["total_return"]
        ):
            enabled_return = enabled_result["performance"]["total_return"]
            disabled_return = disabled_result["performance"]["total_return"]
            comparison["return_improvement"] = enabled_return - disabled_return
            comparison["return_improvement_pct"] = (
                ((enabled_return / abs(disabled_return)) - 1) * 100
                if disabled_return != 0
                else 0
            )

        if (
            enabled_result["performance"]["sharpe_ratio"]
            and disabled_result["performance"]["sharpe_ratio"]
        ):
            enabled_sharpe = enabled_result["performance"]["sharpe_ratio"]
            disabled_sharpe = disabled_result["performance"]["sharpe_ratio"]
            comparison["sharpe_improvement"] = enabled_sharpe - disabled_sharpe
            comparison["sharpe_improvement_pct"] = (
                ((enabled_sharpe / abs(disabled_sharpe)) - 1) * 100
                if disabled_sharpe != 0
                else 0
            )

        if (
            enabled_result["performance"]["max_drawdown"]
            and disabled_result["performance"]["max_drawdown"]
        ):
            enabled_dd = enabled_result["performance"]["max_drawdown"]
            disabled_dd = disabled_result["performance"]["max_drawdown"]
            comparison["drawdown_improvement"] = (
                disabled_dd - enabled_dd
            )  # Less negative is better
            comparison["drawdown_improvement_pct"] = (
                ((disabled_dd / abs(enabled_dd)) - 1) * 100 if enabled_dd != 0 else 0
            )

        # Trade analysis by regime
        trades_by_regime_enabled = {}
        trades_by_regime_disabled = {}

        for trade in enabled_result["trades"]:
            regime = trade.get("regime", "UNKNOWN")
            if regime not in trades_by_regime_enabled:
                trades_by_regime_enabled[regime] = []
            trades_by_regime_enabled[regime].append(trade)

        for trade in disabled_result["trades"]:
            regime = trade.get("regime", "UNKNOWN")
            if regime not in trades_by_regime_disabled:
                trades_by_regime_disabled[regime] = []
            trades_by_regime_disabled[regime].append(trade)

        comparison["trades_by_regime_enabled"] = trades_by_regime_enabled
        comparison["trades_by_regime_disabled"] = trades_by_regime_disabled

        return comparison

    def generate_report(self, comparison: Dict[str, Any], output_path: str):
        """Generate comprehensive performance comparison report."""
        report = {
            "analysis_date": datetime.now().isoformat(),
            "summary": self._generate_summary(comparison),
            "performance_comparison": self._generate_performance_comparison(comparison),
            "regime_analysis": self._generate_regime_analysis(comparison),
            "trade_analysis": self._generate_trade_analysis(comparison),
            "recommendations": self._generate_recommendations(comparison),
        }

        # Save report
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        print(f"Performance analysis report saved to: {output_path}")

        # Print summary
        self._print_summary(report)

    def _generate_summary(self, comparison: Dict[str, Any]) -> Dict[str, Any]:
        """Generate executive summary."""
        return {
            "total_return_improvement": comparison.get("return_improvement_pct", 0),
            "sharpe_improvement": comparison.get("sharpe_improvement_pct", 0),
            "drawdown_improvement": comparison.get("drawdown_improvement_pct", 0),
            "trade_count_difference": len(comparison.get("enabled_trades", []))
            - len(comparison.get("disabled_trades", [])),
            "regime_detection_effective": comparison.get("return_improvement_pct", 0)
            > 0,
        }

    def _generate_performance_comparison(
        self, comparison: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate detailed performance comparison."""
        return {
            "returns": {
                "enabled": comparison["enabled_performance"]["total_return"],
                "disabled": comparison["disabled_performance"]["total_return"],
                "improvement": comparison.get("return_improvement"),
                "improvement_pct": comparison.get("return_improvement_pct"),
            },
            "sharpe_ratio": {
                "enabled": comparison["enabled_performance"]["sharpe_ratio"],
                "disabled": comparison["disabled_performance"]["sharpe_ratio"],
                "improvement": comparison.get("sharpe_improvement"),
                "improvement_pct": comparison.get("sharpe_improvement_pct"),
            },
            "max_drawdown": {
                "enabled": comparison["enabled_performance"]["max_drawdown"],
                "disabled": comparison["disabled_performance"]["max_drawdown"],
                "improvement": comparison.get("drawdown_improvement"),
                "improvement_pct": comparison.get("drawdown_improvement_pct"),
            },
            "win_rate": {
                "enabled": comparison["enabled_performance"]["win_rate"],
                "disabled": comparison["disabled_performance"]["win_rate"],
            },
            "total_trades": {
                "enabled": comparison["enabled_trading"]["total_trades"],
                "disabled": comparison["disabled_trading"]["total_trades"],
            },
        }

    def _generate_regime_analysis(self, comparison: Dict[str, Any]) -> Dict[str, Any]:
        """Generate regime detection analysis."""
        stats = comparison["regime_enabled_stats"]

        if not stats.get("regime_detection_enabled", False):
            return {"message": "Regime detection was not enabled"}

        return {
            "regime_distribution": stats.get("regime_distribution", {}),
            "evaluation_count": stats.get("evaluations", 0),
            "change_rate": stats.get("change_rate", 0),
            "average_persistence": stats.get("avg_persistence", 0),
            "current_regime": stats.get("current_regime"),
        }

    def _generate_trade_analysis(self, comparison: Dict[str, Any]) -> Dict[str, Any]:
        """Generate trade analysis by regime."""
        enabled_trades = comparison["trades_by_regime_enabled"]
        disabled_trades = comparison["trades_by_regime_disabled"]

        analysis = {
            "trade_count_by_regime": {
                "enabled": {
                    regime: len(trades) for regime, trades in enabled_trades.items()
                },
                "disabled": {
                    regime: len(trades) for regime, trades in disabled_trades.items()
                },
            }
        }

        # Calculate performance by regime for enabled configuration
        regime_performance = {}
        for regime, trades in enabled_trades.items():
            if trades:
                # Simple P&L calculation (simplified)
                pnl = 0
                for i in range(0, len(trades), 2):  # Pair trades
                    if i + 1 < len(trades):
                        pnl += trades[i + 1]["price"] - trades[i]["price"]
                regime_performance[regime] = {
                    "trade_count": len(trades),
                    "total_pnl": pnl,
                    "avg_pnl": pnl / (len(trades) // 2) if len(trades) > 1 else 0,
                }

        analysis["performance_by_regime"] = regime_performance

        return analysis

    def _generate_recommendations(
        self, comparison: Dict, improvement_pct: float
    ) -> List[str]:
        """Generate actionable recommendations based on analysis."""
        recommendations = []

        return_improvement = comparison.get("return_improvement_pct", 0)

        if return_improvement > 5:
            recommendations.append(
                "Regime detection is highly effective. Consider expanding to more strategies."
            )
        elif return_improvement > 0:
            recommendations.append(
                "Regime detection shows positive impact. Monitor performance regularly."
            )
        else:
            recommendations.append(
                "Regime detection is not improving performance. Consider adjusting parameters."
            )

        sharpe_improvement = comparison.get("sharpe_improvement_pct", 0)
        if sharpe_improvement > 10:
            recommendations.append(
                "Significant Sharpe ratio improvement detected. Risk-adjusted performance enhanced."
            )
        elif sharpe_improvement < -5:
            recommendations[
                "Sharpe ratio decreased. Review risk management in regime-aware mode."
            ]

        drawdown_improvement = comparison.get("drawdown_improvement_pct", 0)
        if drawdown_improvement > 10:
            recommendations.append(
                "Significant drawdown reduction achieved. Risk management improved."
            )

        # Add specific regime-based recommendations
        stats = comparison["regime_enabled_stats"]
        if stats.get("change_rate", 0) > 0.5:
            recommendations.append(
                "High regime switching detected. Consider increasing persistence bars or cooldown periods."
            )

        return recommendations

    def _print_summary(self, report: Dict[str, Any]):
        """Print executive summary to console."""
        print("\n" + "=" * 60)
        print("REGIME PERFORMANCE ANALYSIS SUMMARY")
        print("=" * 60)

        summary = report["summary"]

        print(f"Total Return Improvement: {summary['total_return_improvement']:+.2f}%")
        print(f"Sharpe Ratio Improvement: {summary['sharpe_improvement']:+.2f}%")
        print(f"Max Drawdown Improvement: {summary['drawdown_improvement']:+.2f}%")
        print(f"Trade Count Difference: {summary['trade_count_difference']:+d}")
        print(f"Regime Detection Effective: {summary['regime_detection_effective']}")

        print("\nPerformance Comparison:")
        perf = report["performance_comparison"]
        print(
            f"  Returns: {perf['returns']['enabled']:.2%} vs {perf['returns']['disabled']:.2%} ({perf['returns']['improvement_pct']:+.1f}%)"
        )
        print(
            f"  Sharpe: {perf['sharpe_ratio']['enabled']:.2f} vs {perf['sharpe_ratio']['disabled']:.2f} ({perf['sharpe_ratio']['improvement_pct']:+.1f}%)"
        )
        print(
            f"  Drawdown: {perf['max_drawdown']['enabled']:.2%} vs {perf['max_drawdown']['disabled']:.2%} ({perf['max_drawdown']['improvement_pct']:+.1f}%)"
        )

        print("\nRecommendations:")
        for i, rec in enumerate(report["recommendations"], 1):
            print(f"{i}. {rec}")

        print("\n" + "=" * 60)

    def create_visualizations(self, comparison: Dict[str, Any], output_dir: str):
        """Create visualization charts for the analysis."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Create performance comparison chart
        self._create_performance_chart(
            comparison, output_path / "performance_comparison.png"
        )

        # Create regime distribution chart
        self._create_regime_distribution_chart(
            comparison, output_path / "regime_distribution.png"
        )

        # Create trade timeline chart
        self._create_trade_timeline_chart(
            comparison, output_path / "trade_timeline.png"
        )

        print(f"Visualizations saved to: {output_path}")

    def _create_performance_chart(self, comparison: Dict[str, Any], output_path: Path):
        """Create performance comparison bar chart."""
        metrics = ["total_return", "sharpe_ratio", "max_drawdown", "win_rate"]
        enabled_vals = [comparison["enabled_performance"][metric] for metric in metrics]
        disabled_vals = [
            comparison["disabled_performance"][metric] for metric in metrics
        ]

        x = np.arange(len(metrics))
        width = 0.35

        fig, ax = plt.subplots(figsize=(12, 6))
        bars1 = ax.bar(
            x - width / 2, enabled_vals, width, label="Regime Enabled", alpha=0.8
        )
        bars2 = ax.bar(
            x + width / 2, disabled_vals, width, label="Regime Disabled", alpha=0.8
        )

        ax.set_xlabel("Metrics")
        ax.set_ylabel("Values")
        ax.set_title("Performance Comparison: Regime Enabled vs Disabled")
        ax.set_xticks(x)
        ax.set_xticklabels(["Return", "Sharpe", "Max DD", "Win Rate"])
        ax.legend()

        # Add value labels on bars
        for bar in bars1:
            height = bar.get_height()
            ax.annotate(
                f"{height:.3f}",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
            )

        for bar in bars2:
            height = bar.get_height()
            ax.annotate(
                f"{height:.3f}",
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
            )

        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close()

    def _create_regime_distribution_chart(
        self, comparison: Dict[str, Any], output_path: Path
    ):
        """Create regime distribution pie chart."""
        stats = comparison["regime_enabled_stats"]

        if not stats.get("regime_detection_enabled", False):
            return

        distribution = stats.get("regime_distribution", {})
        if not distribution:
            return

        fig, ax = plt.subplots(figsize=(10, 8))
        wedges, texts, autotexts = ax.pie(
            distribution.values(),
            labels=list(distribution.keys()),
            autopct="%1.1f%%",
            startangle=90,
        )

        ax.set_title("Regime Distribution")
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close()

    def _create_trade_timeline_chart(
        self, comparison: Dict[str, Any], output_path: Path
    ):
        """Create trade timeline chart showing trades by regime."""
        enabled_trades = comparison["trades_by_regime_enabled"]

        if not enabled_trades:
            return

        # Prepare data for plotting
        plot_data = []
        for regime, trades in enabled_trades.items():
            for trade in trades:
                plot_data.append(
                    {
                        "timestamp": pd.to_datetime(trade["timestamp"], unit="ns"),
                        "regime": regime,
                        "action": trade["action"],
                    }
                )

        if not plot_data:
            return

        df = pd.DataFrame(plot_data)
        df = df.sort_values("timestamp")

        fig, ax = plt.subplots(figsize=(14, 8))

        # Plot trades colored by regime
        colors = {
            "BULL": "green",
            "BEAR": "red",
            "SIDEWAYS": "blue",
            "STRESS": "orange",
            "UNKNOWN": "gray",
        }

        for regime in df["regime"].unique():
            regime_data = df[df["regime"] == regime]
            ax.scatter(
                regime_data["timestamp"],
                [0.5] * len(regime_data),
                c=colors.get(regime, "gray"),
                label=regime,
                alpha=0.7,
                s=50,
            )

        ax.set_xlabel("Time")
        ax.set_ylabel("Trades")
        ax.set_title("Trade Timeline by Regime")
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        plt.close()


def main():
    """Main function for CLI interface."""
    parser = argparse.ArgumentParser(description="Regime Performance Analysis Tool")
    parser.add_argument(
        "--config", required=True, help="Path to regime-enabled configuration file"
    )
    parser.add_argument(
        "--baseline", help="Path to baseline (regime disabled) configuration file"
    )
    parser.add_argument(
        "--output",
        default="regime_analysis.json",
        help="Output file for analysis results",
    )
    parser.add_argument(
        "--visualizations",
        default="regime_charts",
        help="Directory for visualization charts",
    )
    parser.add_argument(
        "--symbols", default="AAPL,MSFT,GOOGL", help="Comma-separated list of symbols"
    )
    parser.add_argument(
        "--start-date", default="2024-01-01", help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date", default="2024-01-31", help="End date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--sample-data",
        action="store_true",
        help="Generate sample data instead of using real data",
    )

    args = parser.parse_args()

    # Initialize analyzer
    analyzer = RegimePerformanceAnalyzer()

    try:
        # Load configurations
        print("Loading configurations...")
        enabled_config = analyzer.load_configuration(args.config)

        if args.baseline:
            disabled_config = analyzer.load_configuration(args.baseline)
        else:
            # Create disabled configuration by modifying enabled config
            disabled_config = enabled_config.copy()
            disabled_config["regime"]["enabled"] = False
            disabled_config["regime"]["strategy_map"] = {}

        print(f"Using enabled config: {args.config}")
        if args.baseline:
            print(f"Using baseline config: {args.baseline}")
        else:
            print("Using auto-generated baseline (regime disabled)")

        # Prepare data
        symbols = [s.strip() for s in args.symbols.split(",")]
        print(f"Symbols: {symbols}")
        print(f"Date range: {args.start_date} to {args.end_date}")

        if args.sample_data:
            print("Generating sample data...")
            data = analyzer.generate_sample_data(
                symbols, args.start_date, args.end_date
            )
        else:
            print("Loading real data from Gold...")
            try:
                data = load_bars(
                    root="/home/jacobw/gcs-mount",
                    family="bars_1m",
                    symbols=symbols,
                    dates=analyzer._generate_date_range(args.start_date, args.end_date),
                )
                print(f"Loaded {len(data)} bars")
            except Exception as e:
                print(f"Warning: Could not load real data: {e}")
                print("Falling back to sample data...")
                data = analyzer.generate_sample_data(
                    symbols, args.start_date, args.end_date
                )

        # Run comparison
        print("\nRunning performance comparison...")
        comparison = analyzer.compare_performance(enabled_config, disabled_config, data)

        # Generate report
        print("\nGenerating analysis report...")
        analyzer.generate_report(comparison, args.output)

        # Create visualizations
        print("\nCreating visualizations...")
        analyzer.create_visualizations(comparison, args.visualizations)

        print(f"\nAnalysis complete! Results saved to: {args.output}")
        print(f"Charts saved to: {args.visualizations}")

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
