"""Multi-strategy backtest runner for January 2025."""

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# Add paths for imports
script_dir = Path(__file__).parent.parent
sip_discovery_dir = script_dir.parent / "sip_pattern_discovery"

sys.path.insert(0, str(script_dir))
sys.path.insert(0, str(sip_discovery_dir))
sys.path.insert(0, str(sip_discovery_dir / "src"))

# Import data loader from sip_pattern_discovery
import data_loader as sip_data_loader

# Import local modules
from src import feature_pipeline
from src.pattern_multi_policy import PatternMultiPolicy

# Import qx_backtest components - simplified to avoid dependency issues
from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.fill import DefaultFiller


class MultiStrategyBacktestRunner:
    """Run backtest on multiple pattern strategies for January 2025."""

    def __init__(
        self,
        strategies_yaml: Path,
        sip_dir: Path,
        gold_dir: Path,
        output_dir: Path,
        lookback_days: int = 5,
    ):
        """Initialize multi-strategy backtest runner.

        Args:
            strategies_yaml: Path to strategies YAML file
            sip_dir: Path to daily_sip directory
            gold_dir: Path to gold data directory
            output_dir: Output directory for results
            lookback_days: Days of lookback for features
        """
        self.strategies_yaml = strategies_yaml
        self.sip_dir = sip_dir
        self.gold_dir = gold_dir
        self.output_dir = output_dir
        self.lookback_days = lookback_days

        # Load config from YAML
        with open(strategies_yaml) as f:
            self.config = yaml.safe_load(f)

        self.backtest_config = self.config["backtest_config"]
        self.start_date = self.backtest_config["start_date"]
        self.end_date = self.backtest_config["end_date"]
        self.position_size = self.backtest_config["position_size"]
        self.commission = self.backtest_config["commission"]
        self.horizon_minutes = self.backtest_config["horizon_minutes"]
        self.initial_cash = self.backtest_config["initial_cash"]

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict[str, Any]:
        """Run multi-strategy backtest and generate segregated reports.

        Returns:
            Dictionary with backtest results for each strategy
        """
        print("=" * 80)
        print("MULTI-STRATEGY PATTERN BACKTEST - JANUARY 2025")
        print("=" * 80)
        print(f"Strategies: {len(self.config['strategies'])}")
        print(f"Date range: {self.start_date} to {self.end_date}")
        print(f"Position size: {self.position_size} shares")
        print(f"Commission: ${self.commission} per round-turn")
        print(f"Horizon: {self.horizon_minutes} minutes")
        print("=" * 80)

        # Step 1: Load data
        print("\n[1/4] Loading SIP-filtered data...")
        df, metadata = sip_data_loader.load_sip_filtered_data(
            self.start_date,
            self.end_date,
            self.lookback_days,
            self.sip_dir,
            self.gold_dir,
        )

        if df.empty:
            print("ERROR: No data loaded")
            return {}

        print(f"Loaded {len(df):,} bars across {metadata['unique_symbols']} symbols")

        # Step 2: Compute features
        print("\n[2/4] Computing and discretizing features...")
        df = feature_pipeline.compute_and_discretize_features(df)

        # Step 3: Run backtest with multi-strategy policy
        print("\n[3/4] Running multi-strategy backtest...")

        # Create multi-strategy policy
        policy = PatternMultiPolicy(
            strategies_yaml=self.strategies_yaml,
            position_size=self.position_size,
            horizon_minutes=self.horizon_minutes,
        )

        # Create filler with commission
        filler = DefaultFiller(
            commission_per_share=self.commission / self.position_size / 2
        )

        # Create backtest config
        config = BacktestConfig(
            initial_cash=float(self.initial_cash),
            start_date=self.start_date,
            end_date=self.end_date,
            filler=filler,
            show_progress=True,
        )

        # Run backtest
        engine = BacktestEngine(config)
        result = engine.run(df, policy)

        # Step 4: Generate segregated reports
        print("\n[4/4] Generating segregated reports...")

        all_results = {}

        # Process trades by strategy
        if result.trades_history:
            trades_df = pd.DataFrame(result.trades_history)

            # Group trades by strategy_id
            strategy_groups = (
                trades_df.groupby("strategy_id")
                if "strategy_id" in trades_df.columns
                else {}
            )

            for strategy_name, strategy_config in self.config["strategies"].items():
                strategy_id = strategy_config["name"]

                # Filter trades for this strategy
                if strategy_id in strategy_groups.groups:
                    strategy_trades = strategy_groups.get_group(strategy_id)
                else:
                    strategy_trades = pd.DataFrame()  # No trades for this strategy

                # Calculate strategy-specific metrics
                strategy_metrics = self._calculate_strategy_metrics(
                    strategy_trades, strategy_config, strategy_id
                )

                # Save strategy-specific results
                self._save_strategy_results(
                    strategy_trades, strategy_metrics, strategy_id
                )

                all_results[strategy_id] = strategy_metrics

                print(
                    f"Strategy {strategy_id}: {len(strategy_trades)} trades, "
                    f"Return: {strategy_metrics.get('total_return', 0):.2%}"
                )

        # Save combined results
        combined_path = self.output_dir / "combined_results.json"
        with open(combined_path, "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"Saved combined results to {combined_path}")

        # Save overall equity curve
        if not result.equity_curve.empty:
            equity_path = self.output_dir / "equity_curve_combined.csv"
            result.equity_curve.to_csv(equity_path)
            print(f"Saved combined equity curve to {equity_path}")

        # Print summary
        print("\n" + "=" * 80)
        print("MULTI-STRATEGY BACKTEST COMPLETE")
        print("=" * 80)
        total_trades = sum(
            len(result.get("trades", [])) for result in all_results.values()
        )
        print(f"Total trades across all strategies: {total_trades}")
        print(f"Overall return: {result.total_return:.2%}")
        print(f"Overall Sharpe: {result.sharpe_ratio:.2f}")
        print("=" * 80)

        return all_results

    def _calculate_strategy_metrics(
        self, trades_df: pd.DataFrame, strategy_config: dict, strategy_id: str
    ) -> dict[str, Any]:
        """Calculate performance metrics for a single strategy."""
        if trades_df.empty:
            return {
                "strategy_id": strategy_id,
                "strategy_config": strategy_config,
                "total_trades": 0,
                "total_return": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
            }

        # Calculate basic metrics
        total_pnl = trades_df["pnl"].sum() if "pnl" in trades_df.columns else 0
        winning_trades = (
            trades_df[trades_df["pnl"] > 0]
            if "pnl" in trades_df.columns
            else pd.DataFrame()
        )
        losing_trades = (
            trades_df[trades_df["pnl"] <= 0]
            if "pnl" in trades_df.columns
            else pd.DataFrame()
        )

        win_rate = len(winning_trades) / len(trades_df) if len(trades_df) > 0 else 0

        gross_profit = winning_trades["pnl"].sum() if not winning_trades.empty else 0
        gross_loss = abs(losing_trades["pnl"].sum()) if not losing_trades.empty else 0
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else float("inf") if gross_profit > 0 else 0
        )

        # Estimate return based on position size and commission
        total_return = total_pnl / self.initial_cash

        return {
            "strategy_id": strategy_id,
            "strategy_config": strategy_config,
            "total_trades": len(trades_df),
            "total_return": total_return,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "sharpe_ratio": 0.0,  # Would need daily returns to calculate properly
            "max_drawdown": 0.0,  # Would need equity curve to calculate properly
        }

    def _save_strategy_results(
        self, trades_df: pd.DataFrame, metrics: dict, strategy_id: str
    ):
        """Save results for a single strategy."""
        # Save trades
        if not trades_df.empty:
            trades_path = self.output_dir / f"trades_{strategy_id}.csv"
            trades_df.to_csv(trades_path, index=False)
            print(f"Saved {strategy_id} trades to {trades_path}")

        # Save metrics
        metrics_path = self.output_dir / f"metrics_{strategy_id}.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2, default=str)
        print(f"Saved {strategy_id} metrics to {metrics_path}")


if __name__ == "__main__":
    # Example usage
    runner = MultiStrategyBacktestRunner(
        strategies_yaml=Path("config/top5_strategies.yaml"),
        sip_dir=Path("/home/jacobw/intraday_stack/data/daily_sip"),
        gold_dir=Path("/home/jacobw/gcs-mount/gold/stocks/1m"),
        output_dir=Path("output/jan2025_backtest"),
    )

    results = runner.run()
