"""Entry/Exit AB testing framework for signal analysis."""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .engine import BacktestConfig, BacktestEngine, BacktestResult
from .policies.vwap_revert import VwapRevertPolicy


@dataclass
class ABTestConfig:
    """Configuration for AB testing framework."""

    # Test parameters
    entry_variants: list[dict[str, Any]] = field(default_factory=list)
    exit_variants: list[dict[str, Any]] = field(default_factory=list)

    # Test data
    symbols: list[str] = field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None

    # Risk management
    initial_cash: float = 1_000_000.0
    position_size_pct: float = 0.1
    max_positions: int = 5

    # Performance metrics to track
    metrics: list[str] = field(
        default_factory=lambda: [
            "total_return",
            "sharpe_ratio",
            "max_drawdown",
            "win_rate",
            "profit_factor",
            "avg_trade_pnl",
            "total_trades",
        ]
    )

    # Statistical testing
    confidence_level: float = 0.95
    min_trades_for_significance: int = 30


@dataclass
class ABTestResult:
    """Results from AB testing analysis."""

    # Individual test results
    entry_results: dict[str, BacktestResult] = field(default_factory=dict)
    exit_results: dict[str, BacktestResult] = field(default_factory=dict)
    combination_results: dict[tuple[str, str], BacktestResult] = field(default_factory=dict)

    # Statistical analysis
    entry_comparison: dict[str, Any] = field(default_factory=dict)
    exit_comparison: dict[str, Any] = field(default_factory=dict)
    combination_comparison: dict[str, Any] = field(default_factory=dict)

    # Best performing configurations
    best_entry: str | None = None
    best_exit: str | None = None
    best_combination: tuple[str, str] | None = None

    # Metadata
    total_tests_run: int = 0
    test_duration: float = 0.0


class EntryExitABTest:
    """Entry/Exit AB testing framework for systematic strategy optimization."""

    def __init__(self, config: ABTestConfig):
        """Initialize AB testing framework.

        Args:
            config: AB testing configuration
        """
        self.config = config

    def run_tests(self, data: pd.DataFrame) -> ABTestResult:
        """Run entry/exit AB tests.

        Args:
            data: Historical OHLCV data with features

        Returns:
            ABTestResult with comprehensive analysis
        """
        import time

        start_time = time.time()

        result = ABTestResult()

        # Prepare data
        test_data = self._prepare_data(data)

        # Test entry variants
        if self.config.entry_variants:
            entry_results = self._test_entry_variants(test_data)
            result.entry_results = entry_results
            result.entry_comparison = self._compare_results(entry_results)
            result.best_entry = self._find_best_config(entry_results)

        # Test exit variants
        if self.config.exit_variants:
            exit_results = self._test_exit_variants(test_data)
            result.exit_results = exit_results
            result.exit_comparison = self._compare_results(exit_results)
            result.best_exit = self._find_best_config(exit_results)

        # Test combinations (if both entry and exit variants exist)
        if self.config.entry_variants and self.config.exit_variants:
            combination_results = self._test_combinations(test_data)
            result.combination_results = combination_results
            result.combination_comparison = self._compare_combination_results(combination_results)
            result.best_combination = self._find_best_combination(combination_results)

        # Calculate total tests run
        result.total_tests_run = (
            len(self.config.entry_variants)
            + len(self.config.exit_variants)
            + len(self.config.entry_variants) * len(self.config.exit_variants)
        )

        result.test_duration = time.time() - start_time

        return result

    def _prepare_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """Prepare data for testing."""
        # Filter by symbols if specified
        if self.config.symbols:
            data = data[data["symbol"].isin(self.config.symbols)]

        # Filter by date range if specified
        if self.config.start_date:
            start_ts = pd.Timestamp(self.config.start_date).value
            data = data[data["ts"] >= start_ts]

        if self.config.end_date:
            end_ts = pd.Timestamp(self.config.end_date).value
            data = data[data["ts"] <= end_ts]

        # Ensure data is sorted
        data = data.sort_values(["ts", "symbol"]).reset_index(drop=True)

        return data

    def _test_entry_variants(self, data: pd.DataFrame) -> dict[str, BacktestResult]:
        """Test different entry variants."""
        results = {}

        for entry_config in self.config.entry_variants:
            entry_name = entry_config.get("name", f"entry_{len(results)}")

            # Create policy with entry variant
            policy = VwapRevertPolicy(
                vwap_window=entry_config.get("vwap_window", 30),
                min_rvol=entry_config.get("min_rvol", 1.0),
                max_position_bars=entry_config.get("max_position_bars", 50),
                position_size_pct=self.config.position_size_pct,
                max_positions=self.config.max_positions,
                name=f"VwapRevert_{entry_name}",
            )

            # Run backtest
            config = BacktestConfig(initial_cash=self.config.initial_cash)
            engine = BacktestEngine(config)
            engine.add_policy(policy)

            def strategy_func(engine, bar):
                policy.process_bar(bar)

            backtest_result = engine.run(data, strategy_func)
            backtest_result.strategy_name = entry_name

            results[entry_name] = backtest_result

        return results

    def _test_exit_variants(self, data: pd.DataFrame) -> dict[str, BacktestResult]:
        """Test different exit variants."""
        results = {}

        for exit_config in self.config.exit_variants:
            exit_name = exit_config.get("name", f"exit_{len(results)}")

            # Create policy with exit variant
            policy = VwapRevertPolicy(
                vwap_window=30,  # Fixed for exit testing
                min_rvol=1.0,  # Fixed for exit testing
                max_position_bars=exit_config.get("max_position_bars", 50),
                position_size_pct=self.config.position_size_pct,
                max_positions=self.config.max_positions,
                name=f"VwapRevert_{exit_name}",
            )

            # Run backtest
            config = BacktestConfig(initial_cash=self.config.initial_cash)
            engine = BacktestEngine(config)
            engine.add_policy(policy)

            def strategy_func(engine, bar):
                policy.process_bar(bar)

            backtest_result = engine.run(data, strategy_func)
            backtest_result.strategy_name = exit_name

            results[exit_name] = backtest_result

        return results

    def _test_combinations(self, data: pd.DataFrame) -> dict[tuple[str, str], BacktestResult]:
        """Test entry/exit combinations."""
        results = {}

        for entry_config in self.config.entry_variants:
            entry_name = entry_config.get("name", f"entry_{len(results)}")

            for exit_config in self.config.exit_variants:
                exit_name = exit_config.get("name", f"exit_{len(results)}")
                combo_name = (entry_name, exit_name)

                # Create policy with combination
                policy = VwapRevertPolicy(
                    vwap_window=entry_config.get("vwap_window", 30),
                    min_rvol=entry_config.get("min_rvol", 1.0),
                    max_position_bars=exit_config.get("max_position_bars", 50),
                    position_size_pct=self.config.position_size_pct,
                    max_positions=self.config.max_positions,
                    name=f"VwapRevert_{entry_name}_{exit_name}",
                )

                # Run backtest
                config = BacktestConfig(initial_cash=self.config.initial_cash)
                engine = BacktestEngine(config)
                engine.add_policy(policy)

                def strategy_func(engine, bar):
                    policy.process_bar(bar)

                backtest_result = engine.run(data, strategy_func)
                backtest_result.strategy_name = f"{entry_name}_{exit_name}"

                results[combo_name] = backtest_result

        return results

    def _compare_results(self, results: dict[str, BacktestResult]) -> dict[str, Any]:
        """Compare results across variants."""
        comparison = {}

        if not results:
            return comparison

        # Extract metrics for each variant
        metrics_data = {}
        for name, result in results.items():
            metrics_data[name] = {
                metric: getattr(result, metric, 0.0) for metric in self.config.metrics
            }

        # Create comparison DataFrame
        comparison_df = pd.DataFrame(metrics_data).T

        # Calculate statistical significance if enough trades
        if len(results) >= 2:
            significance_tests = {}
            for metric in self.config.metrics:
                if metric in ["total_trades"]:  # Skip non-numeric metrics
                    continue

                values = [getattr(result, metric, 0.0) for result in results.values()]
                if any(v > 0 for v in values):  # Only test if there are positive values
                    # Simple t-test between best and worst
                    best_idx = np.argmax(values)
                    worst_idx = np.argmin(values)

                    best_value = values[best_idx]
                    worst_value = values[worst_idx]

                    if best_value != worst_value:
                        # This is simplified - proper AB testing would need more sophisticated stats
                        improvement = (
                            (best_value - worst_value) / abs(worst_value) if worst_value != 0 else 0
                        )
                        significance_tests[metric] = {
                            "improvement_pct": improvement * 100,
                            "best_variant": list(results.keys())[best_idx],
                            "worst_variant": list(results.keys())[worst_idx],
                            "best_value": best_value,
                            "worst_value": worst_value,
                        }

            comparison["significance_tests"] = significance_tests

        comparison["metrics_comparison"] = comparison_df.to_dict()
        comparison["ranking"] = self._rank_variants(results)

        return comparison

    def _compare_combination_results(
        self, results: dict[tuple[str, str], BacktestResult]
    ) -> dict[str, Any]:
        """Compare combination results."""
        comparison = {}

        if not results:
            return comparison

        # Extract metrics for each combination
        metrics_data = {}
        for (entry_name, exit_name), result in results.items():
            combo_name = f"{entry_name}_{exit_name}"
            metrics_data[combo_name] = {
                metric: getattr(result, metric, 0.0) for metric in self.config.metrics
            }

        # Create comparison DataFrame
        comparison_df = pd.DataFrame(metrics_data).T

        # Find best combinations
        best_by_metric = {}
        for metric in self.config.metrics:
            if metric in ["total_trades"]:  # Skip non-numeric metrics
                continue

            best_combo = comparison_df[metric].idxmax()
            best_value = comparison_df[metric].max()
            best_by_metric[metric] = {"combination": best_combo, "value": best_value}

        comparison["metrics_comparison"] = comparison_df.to_dict()
        comparison["best_by_metric"] = best_by_metric

        return comparison

    def _rank_variants(self, results: dict[str, BacktestResult]) -> list[dict[str, Any]]:
        """Rank variants by composite score."""
        rankings = []

        for name, result in results.items():
            # Simple composite score (can be customized)
            score = 0.0
            weights = {
                "total_return": 0.3,
                "sharpe_ratio": 0.3,
                "max_drawdown": -0.2,  # Negative because lower is better
                "win_rate": 0.2,
            }

            for metric, weight in weights.items():
                value = getattr(result, metric, 0.0)
                score += value * weight

            rankings.append(
                {
                    "name": name,
                    "score": score,
                    "metrics": {
                        metric: getattr(result, metric, 0.0) for metric in self.config.metrics
                    },
                }
            )

        # Sort by score (descending)
        rankings.sort(key=lambda x: x["score"], reverse=True)

        return rankings

    def _find_best_config(self, results: dict[str, BacktestResult]) -> str | None:
        """Find best performing configuration."""
        if not results:
            return None

        # Use total return as primary criterion (can be customized)
        best_name = max(results.keys(), key=lambda k: getattr(results[k], "total_return", 0.0))
        return best_name

    def _find_best_combination(
        self, results: dict[tuple[str, str], BacktestResult]
    ) -> tuple[str, str] | None:
        """Find best performing combination."""
        if not results:
            return None

        # Use total return as primary criterion (can be customized)
        best_combo = max(results.keys(), key=lambda k: getattr(results[k], "total_return", 0.0))
        return best_combo

    def generate_report(self, result: ABTestResult) -> str:
        """Generate comprehensive AB testing report."""
        report = []
        report.append("# Entry/Exit AB Testing Report")
        report.append(f"Total Tests Run: {result.total_tests_run}")
        report.append(f"Test Duration: {result.test_duration:.2f} seconds")
        report.append("")

        # Entry variant results
        if result.entry_results:
            report.append("## Entry Variant Results")
            report.append(f"Best Entry: {result.best_entry}")
            report.append("")

            if "ranking" in result.entry_comparison:
                report.append("### Rankings")
                for i, rank in enumerate(result.entry_comparison["ranking"][:5], 1):
                    report.append(f"{i}. {rank['name']} (Score: {rank['score']:.3f})")
                    for metric in ["total_return", "sharpe_ratio", "win_rate"]:
                        if metric in rank["metrics"]:
                            report.append(f"   {metric}: {rank['metrics'][metric]:.3f}")
                report.append("")

        # Exit variant results
        if result.exit_results:
            report.append("## Exit Variant Results")
            report.append(f"Best Exit: {result.best_exit}")
            report.append("")

            if "ranking" in result.exit_comparison:
                report.append("### Rankings")
                for i, rank in enumerate(result.exit_comparison["ranking"][:5], 1):
                    report.append(f"{i}. {rank['name']} (Score: {rank['score']:.3f})")
                    for metric in ["total_return", "sharpe_ratio", "win_rate"]:
                        if metric in rank["metrics"]:
                            report.append(f"   {metric}: {rank['metrics'][metric]:.3f}")
                report.append("")

        # Combination results
        if result.combination_results:
            report.append("## Combination Results")
            report.append(f"Best Combination: {result.best_combination}")
            report.append("")

            if "best_by_metric" in result.combination_comparison:
                report.append("### Best by Metric")
                for metric, best in result.combination_comparison["best_by_metric"].items():
                    report.append(f"{metric}: {best['combination']} ({best['value']:.3f})")
                report.append("")

        return "\n".join(report)


def create_default_ab_test_config() -> ABTestConfig:
    """Create default AB testing configuration."""
    return ABTestConfig(
        entry_variants=[
            {"name": "conservative", "vwap_window": 30, "min_rvol": 1.5},
            {"name": "standard", "vwap_window": 20, "min_rvol": 1.0},
            {"name": "aggressive", "vwap_window": 10, "min_rvol": 0.8},
        ],
        exit_variants=[
            {"name": "quick", "max_position_bars": 20},
            {"name": "medium", "max_position_bars": 50},
            {"name": "slow", "max_position_bars": 100},
        ],
        initial_cash=1_000_000.0,
        position_size_pct=0.1,
        max_positions=5,
    )
