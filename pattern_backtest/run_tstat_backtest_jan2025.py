#!/usr/bin/env python3
"""
Updated pattern backtest using the 5 top t-stat patterns for January 2025.
Based on the existing test_clean_180m.py but with new pattern strategies.
"""

import json
import pickle
import sys
import traceback
from pathlib import Path

import pandas as pd

# Setup paths - exactly like the working version
root = Path("/home/jacobw/quantstack")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "sip_pattern_discovery"))
sys.path.insert(0, str(root / "pattern_backtest"))

# Imports - exactly like the working version
try:
    # Import our pattern components
    from src.pattern_parser import parse_strategies_yaml
    from src.rule_evaluator import RuleEvaluator

    from qx_backtest import BacktestConfig, BacktestEngine
    from qx_backtest.fill import DefaultFiller
    from qx_backtest.order import Order, OrderSide, OrderType

    print("✅ All imports successful")
except ImportError as e:
    print(f"❌ Import error: {e}")
    traceback.print_exc()
    sys.exit(1)

# Configuration
START_DATE = "2025-01-01"
END_DATE = "2025-01-31"
LOOKBACK_DAYS = 5
POSITION_SIZE = 100
HORIZON_BARS = 180
MAX_POSITIONS_PER_STRATEGY = 5  # Limit concurrent positions per strategy
MAX_ENTRIES_PER_DAY_PER_STRATEGY = 2  # Limit new entries per day per strategy
FEATURED_CACHE_FILE = (
    root / "pattern_backtest" / "cache" / f"featured_data_{START_DATE}_{END_DATE}.pkl"
)

sip_dir = Path("/home/jacobw/intraday_stack/data/daily_sip")
gold_dir = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

print("\n" + "=" * 80)
print("T-STAT PATTERN BACKTEST - JANUARY 2025")
print("=" * 80)
print(f"Period: {START_DATE} to {END_DATE}")
print(f"Position size: {POSITION_SIZE} shares")
print(f"Exit horizon: {HORIZON_BARS} bars (~180 minutes)")
print("=" * 80)

# ============================================================================
# STEP 1: Load pattern strategies
# ============================================================================
print("\n[1/5] Loading pattern strategies...")

strategies_yaml = root / "pattern_backtest" / "config" / "top5_strategies.yaml"
strategies = parse_strategies_yaml(strategies_yaml)

# Create evaluators
evaluators = {}
for strategy in strategies:
    evaluators[strategy.method_id] = RuleEvaluator(strategy.rule_string)

print(f"✅ Loaded {len(strategies)} strategies:")
for strategy in strategies:
    print(f"  - {strategy.method_id}: {strategy.rule_string}")

# ============================================================================
# STEP 2: Load or generate featured data
# ============================================================================
print("\n[2/5] Loading data...")

if FEATURED_CACHE_FILE.exists():
    print(f"Loading from cache: {FEATURED_CACHE_FILE}")
    with open(FEATURED_CACHE_FILE, "rb") as f:
        df = pickle.load(f)
    print(f"✅ Loaded {len(df):,} bars with features from cache")
else:
    print("❌ ERROR: Featured cache not found")
    print(f"Expected: {FEATURED_CACHE_FILE}")
    print("Run feature generation first to create cache")
    sys.exit(1)

# Sort and validate
df = df.sort_values("ts").reset_index(drop=True)
print("✅ Data validated and sorted")

# ============================================================================
# STEP 3: Create strategy with proper tracking
# ============================================================================
print("\n[3/5] Setting up strategy...")


# Trade tracking
class TradeTracker:
    def __init__(self):
        self.positions = (
            {}
        )  # symbol -> {entry_bar_idx, entry_price, strategy_id, quantity, horizon_minutes}
        self.pending = set()  # symbols with pending orders
        self.completed_trades = []
        self.symbol_bar_counts = {}  # symbol -> bar count (per-symbol, not global)
        self.daily_entries = {}  # (date, strategy_id) -> count
        self.current_date = None

    def get_strategy_position_count(self, strategy_id):
        """Get number of open positions for a strategy."""
        return sum(
            1 for pos in self.positions.values() if pos["strategy_id"] == strategy_id
        )

    def get_daily_entry_count(self, date, strategy_id):
        """Get number of entries today for a strategy."""
        return self.daily_entries.get((date, strategy_id), 0)

    def increment_daily_entry(self, date, strategy_id):
        """Increment daily entry count."""
        key = (date, strategy_id)
        self.daily_entries[key] = self.daily_entries.get(key, 0) + 1

    def on_entry(self, symbol, bar_idx, price, strategy_id, quantity, horizon_minutes):
        """Record entry."""
        self.positions[symbol] = {
            "entry_bar_idx": bar_idx,
            "entry_price": price,
            "strategy_id": strategy_id,
            "quantity": quantity,
            "horizon_minutes": horizon_minutes,
        }
        self.pending.add(symbol)

    def on_exit(self, symbol, bar_idx, price):
        """Record exit and create trade record."""
        if symbol in self.positions:
            pos = self.positions[symbol]

            # Calculate P&L
            pnl = (price - pos["entry_price"]) * pos["quantity"]
            bars_held = bar_idx - pos["entry_bar_idx"]

            self.completed_trades.append(
                {
                    "symbol": symbol,
                    "strategy_id": pos["strategy_id"],
                    "entry_bar_idx": pos["entry_bar_idx"],
                    "exit_bar_idx": bar_idx,
                    "bars_held": bars_held,
                    "entry_price": pos["entry_price"],
                    "exit_price": price,
                    "quantity": pos["quantity"],
                    "pnl_gross": pnl,
                }
            )

            del self.positions[symbol]
            self.pending.discard(symbol)


tracker = TradeTracker()


# Fixed filler
class FixedFiller(DefaultFiller):
    def _get_fill_quantity(self, order, bar_data):
        return order.quantity


def strategy_func(engine, bar):
    """Strategy function with 5 pattern strategies."""
    symbol = bar["symbol"]

    # Track per-symbol bar count
    if symbol not in tracker.symbol_bar_counts:
        tracker.symbol_bar_counts[symbol] = 0
    tracker.symbol_bar_counts[symbol] += 1
    symbol_bar_idx = tracker.symbol_bar_counts[symbol]

    # Track current date for daily limits
    bar_date = pd.Timestamp(bar["ts"]).date()
    if tracker.current_date != bar_date:
        tracker.current_date = bar_date

    # Get position
    position = engine.get_position(symbol)
    has_position = position is not None and position.quantity != 0

    # Check for exit (time-based)
    if has_position and symbol in tracker.positions:
        pos_info = tracker.positions[symbol]
        bars_held = symbol_bar_idx - pos_info["entry_bar_idx"]
        # horizon_minutes = bars since we have 1-minute bars
        horizon_bars = pos_info["horizon_minutes"]

        if bars_held >= horizon_bars:
            # Exit
            side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
            order = Order(
                order_id=f"exit_{symbol}_{symbol_bar_idx}",
                symbol=symbol,
                order_type=OrderType.MARKET,
                side=side,
                quantity=abs(position.quantity),
            )
            engine.submit_order(order)
            tracker.on_exit(symbol, symbol_bar_idx, bar["close"])
            return

    # Check for entry (no position, no pending)
    if not has_position and symbol not in tracker.pending:
        # Evaluate all 5 strategies
        for strategy in strategies:
            evaluator = evaluators[strategy.method_id]

            # Check position limit for this strategy
            if (
                tracker.get_strategy_position_count(strategy.method_id)
                >= MAX_POSITIONS_PER_STRATEGY
            ):
                continue  # Skip if strategy already has max positions

            # Check daily entry limit
            if (
                tracker.get_daily_entry_count(bar_date, strategy.method_id)
                >= MAX_ENTRIES_PER_DAY_PER_STRATEGY
            ):
                continue  # Skip if strategy hit daily entry limit

            if evaluator.evaluate(bar):
                # Enter with this strategy
                side = OrderSide.BUY if strategy.direction == "LONG" else OrderSide.SELL
                order = Order(
                    order_id=f"entry_{symbol}_{symbol_bar_idx}_{strategy.method_id}",
                    symbol=symbol,
                    order_type=OrderType.MARKET,
                    side=side,
                    quantity=POSITION_SIZE,
                )
                engine.submit_order(order)
                tracker.on_entry(
                    symbol,
                    symbol_bar_idx,
                    bar["close"],
                    strategy.method_id,
                    POSITION_SIZE,
                    strategy.horizon_minutes,
                )
                tracker.increment_daily_entry(bar_date, strategy.method_id)
                break  # Only one entry per bar


print("✅ Strategy configured")

# ============================================================================
# STEP 4: Run backtest
# ============================================================================
print("\n[4/5] Running backtest...")

try:
    filler = FixedFiller(commission_per_share=0.01)
    config = BacktestConfig(
        initial_cash=1_000_000.0,
        filler=filler,
        show_progress=False,
    )

    engine = BacktestEngine(config)
    result = engine.run(df, strategy_func)
    print("✅ Backtest complete")

except Exception as e:
    print(f"❌ ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# STEP 5: Generate segregated reports
# ============================================================================
print("\n[5/5] Generating segregated reports...")

# Save completed trades
trades_df = pd.DataFrame(tracker.completed_trades)

if trades_df.empty:
    print("⚠️ No completed trades")
    sys.exit(0)

output_dir = root / "pattern_backtest" / "output"
output_dir.mkdir(parents=True, exist_ok=True)

trades_file = output_dir / "trades_tstat_jan2025.csv"
trades_df.to_csv(trades_file, index=False)
print(f"✅ Saved {len(trades_df)} trades to {trades_file}")

# Per-strategy performance (segregated reporting)
print("\n" + "=" * 80)
print("SEGREGATED STRATEGY PERFORMANCE")
print("=" * 80)

strategy_stats = {}
for strategy in strategies:
    strategy_id = strategy.method_id
    strategy_trades = trades_df[trades_df["strategy_id"] == strategy_id]

    if len(strategy_trades) == 0:
        print(f"\n{strategy_id}: No trades")
        continue

    stats = {
        "trades": len(strategy_trades),
        "total_pnl": strategy_trades["pnl_gross"].sum(),
        "avg_pnl": strategy_trades["pnl_gross"].mean(),
        "win_rate": (strategy_trades["pnl_gross"] > 0).mean(),
        "avg_bars_held": strategy_trades["bars_held"].mean(),
        "expected_expectancy": strategy.expectancy,
        "expected_win_rate": strategy.win_rate,
    }
    strategy_stats[strategy_id] = stats

    print(f"\n{strategy_id}:")
    print(f"  Rule: {strategy.rule_string}")
    print(f"  Trades: {stats['trades']}")
    print(f"  Total P&L: ${stats['total_pnl']:,.2f}")
    print(f"  Avg P&L: ${stats['avg_pnl']:,.2f}")
    print(f"  Win rate: {stats['win_rate']:.1%} (expected: {strategy.win_rate:.1%})")
    print(f"  Avg bars held: {stats['avg_bars_held']:.1f}")

    # Save individual strategy results
    strategy_file = output_dir / f"trades_{strategy_id}.csv"
    strategy_trades.to_csv(strategy_file, index=False)
    print(f"  Saved to: {strategy_file}")

# Consolidated performance
print("\n" + "=" * 80)
print("CONSOLIDATED PERFORMANCE")
print("=" * 80)

print(f"Total trades: {len(trades_df)}")
print(f"Total P&L: ${trades_df['pnl_gross'].sum():,.2f}")
print(f"Avg P&L: ${trades_df['pnl_gross'].mean():,.2f}")
print(f"Win rate: {(trades_df['pnl_gross'] > 0).mean():.1%}")
print(f"Avg bars held: {trades_df['bars_held'].mean():.1f}")

# Save summary with segregated results
summary = {
    "period": f"{START_DATE} to {END_DATE}",
    "total_trades": len(trades_df),
    "total_pnl": float(trades_df["pnl_gross"].sum()),
    "win_rate": float((trades_df["pnl_gross"] > 0).mean()),
    "segregated_strategies": {
        k: {
            kk: float(vv) if isinstance(vv, (int, float)) else vv
            for kk, vv in v.items()
        }
        for k, v in strategy_stats.items()
    },
}

summary_file = output_dir / "summary_tstat_jan2025.json"
with open(summary_file, "w") as f:
    json.dump(summary, f, indent=2)

print(f"\n✅ Segregated summary saved to {summary_file}")
print("\n" + "=" * 80)
print("DONE - 5 STRATEGIES WITH SEGREGATED REPORTING")
print("=" * 80)
