"""Backtest runner - orchestrate pattern backtesting."""

import json
import sys
from pathlib import Path

import pandas as pd

# Add paths for imports
script_dir = Path(__file__).parent.parent
sip_discovery_dir = script_dir.parent / "sip_pattern_discovery"

sys.path.insert(0, str(script_dir))
sys.path.insert(0, str(sip_discovery_dir))

# Import data loader from sip_pattern_discovery
import src.data_loader as sip_data_loader

# Import local modules
import src.feature_pipeline as feature_pipeline
import src.pattern_policy as pattern_policy

from qx_backtest import BacktestConfig, BacktestEngine
from qx_backtest.fill import DefaultFiller


class PatternBacktestRunner:
    """Run backtest on discovered patterns."""

    def __init__(
        self,
        patterns_csv: Path,
        start_date: str,
        end_date: str,
        sip_dir: Path,
        gold_dir: Path,
        output_dir: Path,
        position_size: int = 100,
        commission: float = 2.0,
        horizon_minutes: int = 60,
        min_lift: float = 2.0,
        max_patterns: int = 20,
        lookback_days: int = 5,
        method_id: str = "pattern_discovery",
    ):
        """Initialize backtest runner.

        Args:
            patterns_csv: Path to patterns CSV
            start_date: Start date YYYY-MM-DD
            end_date: End date YYYY-MM-DD
            sip_dir: Path to daily_sip directory
            gold_dir: Path to gold data directory
            output_dir: Output directory for results
            position_size: Fixed position size in shares
            commission: Commission per round-turn
            horizon_minutes: Exit horizon in minutes
            min_lift: Minimum pattern lift
            max_patterns: Maximum patterns to trade
            lookback_days: Days of lookback for features
            method_id: Identifier for this method
        """
        self.patterns_csv = patterns_csv
        self.start_date = start_date
        self.end_date = end_date
        self.sip_dir = sip_dir
        self.gold_dir = gold_dir
        self.output_dir = output_dir
        self.position_size = position_size
        self.commission = commission
        self.horizon_minutes = horizon_minutes
        self.min_lift = min_lift
        self.max_patterns = max_patterns
        self.lookback_days = lookback_days
        self.method_id = method_id

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict:
        """Run backtest and generate reports.

        Returns:
            Dictionary with backtest results
        """
        print("=" * 80)
        print("PATTERN BACKTEST")
        print("=" * 80)
        print(f"Method ID: {self.method_id}")
        print(f"Patterns: {self.patterns_csv}")
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

        # Step 3: Run backtest
        print("\n[3/4] Running backtest...")

        # Create policy
        policy = pattern_policy.PatternPolicy(
            patterns_csv=self.patterns_csv,
            position_size=self.position_size,
            min_lift=self.min_lift,
            max_patterns=self.max_patterns,
            horizon_minutes=self.horizon_minutes,
            method_id=self.method_id,
        )

        # Create filler with commission
        filler = DefaultFiller(
            commission_per_share=self.commission / self.position_size / 2
        )

        # Create backtest config
        config = BacktestConfig(
            initial_cash=1_000_000.0,
            start_date=self.start_date,
            end_date=self.end_date,
            filler=filler,
            show_progress=True,
        )

        # Run backtest
        engine = BacktestEngine(config)
        result = engine.run(df, policy)

        # Step 4: Save results
        print("\n[4/4] Saving results...")

        # Save trades
        if result.trades_history:
            trades_df = pd.DataFrame(result.trades_history)
            # Add method_id to trades
            trades_df["method_id"] = self.method_id
            trades_path = self.output_dir / f"trades_{self.method_id}.csv"
            trades_df.to_csv(trades_path, index=False)
            print(f"Saved trades to {trades_path}")

        # Save equity curve
        if not result.equity_curve.empty:
            equity_path = self.output_dir / f"equity_curve_{self.method_id}.csv"
            result.equity_curve.to_csv(equity_path)
            print(f"Saved equity curve to {equity_path}")

        # Save performance metrics
        metrics = {
            "method_id": self.method_id,
            "total_return": result.total_return,
            "annualized_return": result.annualized_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "total_trades": len(result.trades_history),
        }

        metrics_path = self.output_dir / f"performance_metrics_{self.method_id}.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"Saved metrics to {metrics_path}")

        # Print summary
        print("\n" + "=" * 80)
        print("BACKTEST COMPLETE")
        print("=" * 80)
        print(f"Total trades: {len(result.trades_history)}")
        print(f"Total return: {result.total_return:.2%}")
        print(f"Sharpe ratio: {result.sharpe_ratio:.2f}")
        print(f"Win rate: {result.win_rate:.2%}")
        print(f"Max drawdown: {result.max_drawdown:.2%}")
        print("=" * 80)

        return metrics
