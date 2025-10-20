"""Cost sweep experiment for analyzing transaction cost sensitivity."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from .base import BaseExperiment, ExperimentConfig, ExperimentResult


@dataclass
class CostSweepConfig(ExperimentConfig):
    """Configuration for cost sweep experiment."""

    # Cost parameters to sweep
    commission_per_share: list[float] = field(
        default_factory=lambda: [0.001, 0.0035, 0.005, 0.01]
    )
    commission_min: list[float] = field(default_factory=lambda: [0.0, 0.35, 1.0])
    slippage_bps: list[int] = field(default_factory=lambda: [0, 2, 5, 10])
    tick_size: list[float] = field(default_factory=lambda: [0.01, 0.001])

    # Strategy parameters
    strategy_name: str = "VwapRevert"
    vwap_window: int = 30
    min_rvol: float = 1.0
    max_position_bars: int = 50
    position_size_pct: float = 0.1
    max_positions: int = 5

    # Portfolio parameters
    initial_cash: float = 1_000_000.0

    # Analysis parameters
    primary_metric: str = "sharpe_ratio"  # Primary metric for optimization
    secondary_metrics: list[str] = field(
        default_factory=lambda: ["total_return", "max_drawdown", "win_rate"]
    )

    def __post_init__(self):
        """Validate configuration."""
        if not self.commission_per_share:
            self.commission_per_share = [0.0035]
        if not self.commission_min:
            self.commission_min = [0.35]
        if not self.slippage_bps:
            self.slippage_bps = [5]
        if not self.tick_size:
            self.tick_size = [0.01]


@dataclass
class CostSweepResult:
    """Results from cost sweep analysis."""

    # Best configuration
    best_config: dict[str, Any]
    best_metrics: dict[str, float]

    # All results
    all_results: list[dict[str, Any]] = field(default_factory=list)

    # Sensitivity analysis
    sensitivity_analysis: dict[str, Any] = field(default_factory=dict)

    # Cost impact analysis
    cost_impact: dict[str, float] = field(default_factory=dict)


class CostSweepExperiment(BaseExperiment):
    """Cost sweep experiment for transaction cost analysis."""

    def __init__(self, config: CostSweepConfig):
        """Initialize cost sweep experiment.

        Args:
            config: Cost sweep configuration
        """
        super().__init__(config)
        self.cost_config = config

    def validate_config(self) -> None:
        """Validate cost sweep configuration."""
        if not self.config.symbols:
            raise ValueError("At least one symbol must be specified")

        if not self.config.commission_per_share:
            raise ValueError("Commission per share values must be specified")

    def run(self) -> ExperimentResult:
        """Run cost sweep experiment.

        Returns:
            ExperimentResult with cost sweep analysis
        """
        result = ExperimentResult(
            experiment_id=self.experiment_id,
            config=self.config,
            start_time=datetime.now(),
            status="running",
        )

        # Generate parameter combinations
        param_combinations = self._generate_parameter_combinations()

        print(f"Running {len(param_combinations)} parameter combinations...")

        # Run backtest for each combination
        all_results = []
        for i, params in enumerate(param_combinations):
            print(f"Running combination {i+1}/{len(param_combinations)}: {params}")

            try:
                backtest_result = self._run_single_backtest(params)
                backtest_result["parameters"] = params
                all_results.append(backtest_result)

            except Exception as e:
                print(f"Failed to run combination {i+1}: {e}")
                continue

        # Analyze results
        analysis = self._analyze_results(all_results)

        # Save results
        result.results = {
            "cost_sweep_analysis": analysis,
            "parameter_combinations": len(param_combinations),
            "successful_runs": len(all_results),
        }

        # Save detailed results
        if all_results:
            results_df = pd.DataFrame(all_results)
            result.save_artifact("cost_sweep_results", results_df, "parquet")

        # Save analysis
        result.save_artifact("cost_sweep_analysis", analysis, "json")

        # Return actual result with analysis
        actual_result = ExperimentResult(
            experiment_id=result.experiment_id,
            config=result.config,
            start_time=result.start_time,
            end_time=datetime.now(),
            results=result.results,
            artifacts=result.artifacts,
            status="completed",
        )

        return actual_result

    def _generate_parameter_combinations(self) -> list[dict[str, Any]]:
        """Generate all parameter combinations."""
        combinations = []

        # Generate all combinations
        for commission_per_share in self.config.commission_per_share:
            for commission_min in self.config.commission_min:
                for slippage_bps in self.config.slippage_bps:
                    for tick_size in self.config.tick_size:
                        combo = {
                            "commission_per_share": commission_per_share,
                            "commission_min": commission_min,
                            "slippage_bps": slippage_bps,
                            "tick_size": tick_size,
                            "strategy_params": {
                                "strategy_name": self.config.strategy_name,
                                "vwap_window": self.config.vwap_window,
                                "min_rvol": self.config.min_rvol,
                                "max_position_bars": self.config.max_position_bars,
                                "position_size_pct": self.config.position_size_pct,
                                "max_positions": self.config.max_positions,
                            },
                            "portfolio_params": {
                                "initial_cash": self.config.initial_cash,
                            },
                        }
                        combinations.append(combo)

        return combinations

    def _run_single_backtest(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run single backtest with given parameters."""
        # Import here to avoid circular dependencies
        import os
        import sys

        sys.path.insert(0, os.path.join(os.getcwd(), "qx-backtest", "src"))

        try:
            from qx_backtest.engine import BacktestConfig, BacktestEngine
            from qx_backtest.fill import DefaultFiller
            from qx_backtest.policies.vwap_revert import VwapRevertPolicy

            # Create data loader (placeholder - would normally load real data)
            test_data = self._create_test_data()

            # Configure backtest
            filler = DefaultFiller(
                commission_per_share=params["commission_per_share"],
                commission_min=params["commission_min"],
                slippage_bps=params["slippage_bps"],
            )

            config = BacktestConfig(
                initial_cash=params["portfolio_params"]["initial_cash"], filler=filler
            )

            # Create strategy
            strategy_params = params["strategy_params"]
            policy = VwapRevertPolicy(
                vwap_window=strategy_params["vwap_window"],
                min_rvol=strategy_params["min_rvol"],
                max_position_bars=strategy_params["max_position_bars"],
                position_size_pct=strategy_params["position_size_pct"],
                max_positions=strategy_params["max_positions"],
            )

            # Create engine
            engine = BacktestEngine(config)
            engine.add_policy(policy)

            # Define strategy function
            def strategy_func(engine, bar):
                # Policy will process bars automatically
                pass

            # Run backtest
            backtest_result = engine.run(test_data, strategy_func)

            # Extract metrics
            metrics = {
                "total_return": backtest_result.total_return,
                "sharpe_ratio": backtest_result.sharpe_ratio,
                "max_drawdown": backtest_result.max_drawdown,
                "win_rate": backtest_result.win_rate,
                "profit_factor": backtest_result.profit_factor,
                "total_trades": backtest_result.total_trades,
                "avg_trade_pnl": backtest_result.avg_trade_pnl,
                "total_commissions": backtest_result.total_commissions,
                "fill_rate": backtest_result.fill_rate,
                "volatility": backtest_result.volatility,
                "annualized_return": backtest_result.annualized_return,
            }

            return metrics

        except ImportError as e:
            raise RuntimeError(f"Failed to import backtest modules: {e}")

    def _create_test_data(self) -> pd.DataFrame:
        """Create test data for backtesting (placeholder)."""
        # This would normally load real data from qx-data
        # For now, create synthetic data
        np.random.seed(42)

        symbols = (
            self.config.symbols[:3]
            if self.config.symbols
            else ["AAPL", "GOOGL", "MSFT"]
        )
        dates = pd.date_range("2023-01-01", "2023-01-31", freq="D")

        bars = []
        for symbol in symbols:
            for date in dates:
                if date.weekday() >= 5:  # Skip weekends
                    continue

                # Generate synthetic OHLCV data
                base_price = {"AAPL": 100.0, "GOOGL": 150.0, "MSFT": 200.0}[symbol]
                close = base_price * (1 + np.random.normal(0, 0.02))
                high = close * (1 + abs(np.random.normal(0, 0.01)))
                low = close * (1 - abs(np.random.normal(0, 0.01)))
                open_price = close

                volume = int(1_000_000 * (1 + np.random.normal(0, 0.3)))

                # Add features required by VWAP policy
                vwap = close * (1 + np.random.normal(0, 0.005))
                rvol = max(0.5, 1.0 + np.random.normal(0, 0.5))
                atr = close * 0.02 * (1 + np.random.normal(0, 0.3))

                ts = pd.Timestamp(date).value

                bars.append(
                    {
                        "ts": ts,
                        "symbol": symbol,
                        "open": round(open_price, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "close": round(close, 2),
                        "volume": max(volume, 1000),
                        "f__ta__vwap_30": round(vwap, 2),
                        "f__vol__rel_volume_30": round(rvol, 2),
                        "f__vol__atr_14": round(max(atr, 0.1), 2),
                        "f__warmup_ok": True,
                    }
                )

        return pd.DataFrame(bars).sort_values(["ts", "symbol"]).reset_index(drop=True)

    def _analyze_results(self, all_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze cost sweep results."""
        if not all_results:
            return {}

        df = pd.DataFrame(all_results)

        # Find best configuration based on primary metric
        primary_metric = self.config.primary_metric
        if primary_metric in df.columns:
            best_idx = df[primary_metric].idxmax()
            best_row = df.iloc[best_idx]
            best_config = best_row["parameters"]
            best_metrics = best_row.drop("parameters").to_dict()
        else:
            best_config = {}
            best_metrics = {}

        # Calculate cost impact
        cost_impact = self._calculate_cost_impact(df)

        # Sensitivity analysis
        sensitivity_analysis = self._calculate_sensitivity(df)

        # Summary statistics
        summary_stats = {
            "total_combinations": len(df),
            "metric_ranges": {},
            "correlation_matrix": {},
        }

        for metric in [self.config.primary_metric] + self.config.secondary_metrics:
            if metric in df.columns:
                summary_stats["metric_ranges"][metric] = {
                    "min": df[metric].min(),
                    "max": df[metric].max(),
                    "mean": df[metric].mean(),
                    "std": df[metric].std(),
                }

        # Correlation analysis
        numeric_cols = [
            col
            for col in df.columns
            if col not in ["parameters"] and df[col].dtype in ["float64", "int64"]
        ]
        if len(numeric_cols) > 1:
            summary_stats["correlation_matrix"] = df[numeric_cols].corr().to_dict()

        analysis = {
            "best_configuration": best_config,
            "best_metrics": best_metrics,
            "cost_impact": cost_impact,
            "sensitivity_analysis": sensitivity_analysis,
            "summary_statistics": summary_stats,
        }

        return analysis

    def _calculate_cost_impact(self, df: pd.DataFrame) -> dict[str, float]:
        """Calculate cost impact on performance metrics."""
        cost_impact = {}

        # Calculate impact of each cost parameter
        cost_params = [
            "commission_per_share",
            "commission_min",
            "slippage_bps",
            "tick_size",
        ]

        for param in cost_params:
            if param in df["parameters"].iloc[0]:
                # Group by parameter value and calculate average performance
                param_impact = {}
                for value in df["parameters"].apply(lambda x: x[param]).unique():
                    mask = df["parameters"].apply(lambda x: x[param] == value)
                    subset = df[mask]
                    if self.config.primary_metric in subset.columns:
                        param_impact[value] = subset[self.config.primary_metric].mean()

                if len(param_impact) > 1:
                    values = list(param_impact.keys())
                    performance = list(param_impact.values())
                    # Calculate correlation between cost and performance
                    if len(values) > 1 and len(performance) > 1:
                        correlation = np.corr(values, performance)
                        cost_impact[param] = correlation

        return cost_impact

    def _calculate_sensitivity(self, df: pd.DataFrame) -> dict[str, Any]:
        """Calculate sensitivity analysis."""
        sensitivity = {}

        # Calculate sensitivity for each metric to cost changes
        for metric in [self.config.primary_metric] + self.config.secondary_metrics:
            if metric not in df.columns:
                continue

            metric_sensitivity = {}

            # Calculate sensitivity to each cost parameter
            for param in ["commission_per_share", "slippage_bps"]:
                if param in df["parameters"].iloc[0]:
                    values = df["parameters"].apply(lambda x: x[param])
                    performance = df[metric]

                    # Calculate elasticity
                    if len(values) > 1 and len(performance) > 1:
                        # Simple linear regression to estimate sensitivity
                        coeffs = np.polyfit(values, performance, 1)
                        elasticity = coeffs[0]  # Slope represents sensitivity
                        metric_sensitivity[param] = elasticity

            sensitivity[metric] = metric_sensitivity

        return sensitivity


def create_default_cost_sweep_config() -> CostSweepConfig:
    """Create default cost sweep configuration."""
    return CostSweepConfig(
        name="cost_sweep_vwap_revert",
        description="Cost sensitivity analysis for VWAP reversion strategy",
        symbols=["AAPL", "GOOGL", "MSFT"],
        start_date="2023-01-01",
        end_date="2023-12-31",
        # Cost parameters
        commission_per_share=[0.001, 0.0035, 0.005, 0.01],
        commission_min=[0.0, 0.35, 1.0],
        slippage_bps=[0, 2, 5, 10],
        # Strategy parameters
        vwap_window=30,
        min_rvol=1.0,
        max_position_bars=50,
        position_size_pct=0.1,
        max_positions=5,
        # Analysis parameters
        primary_metric="sharpe_ratio",
        secondary_metrics=["total_return", "max_drawdown", "win_rate"],
    )
