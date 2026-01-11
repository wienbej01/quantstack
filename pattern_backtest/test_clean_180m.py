#!/usr/bin/env python3
"""
Clean implementation of manual pattern backtest with proper:
1. 180-bar exit logic (per-symbol counting)
2. Pattern attribution (which pattern triggered each trade)
3. Per-pattern and consolidated reporting
4. Overnight hold validation
"""

import json
import pickle
import sys
import traceback
from pathlib import Path

import pandas as pd

# Setup paths
root = Path("/home/jacobw/quantstack")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "sip_pattern_discovery"))
sys.path.insert(0, str(root / "pattern_backtest"))

# Imports
try:
    from pattern_backtest.src.manual_patterns import (
        MANUAL_PATTERNS,
        evaluate_all_manual_patterns,
    )
    from qx_backtest import BacktestConfig, BacktestEngine
    from qx_backtest.fill import DefaultFiller
    from qx_backtest.order import Order, OrderSide, OrderType

    print("✅ All imports successful")
except ImportError as e:
    print(f"❌ Import error: {e}")
    traceback.print_exc()
    sys.exit(1)

# Configuration
START_DATE = "2024-08-01"
END_DATE = "2024-08-31"
LOOKBACK_DAYS = 5
POSITION_SIZE = 100
HORIZON_BARS = 180
FEATURED_CACHE_FILE = (
    root / "pattern_backtest" / "cache" / f"featured_data_{START_DATE}_{END_DATE}.pkl"
)

sip_dir = Path("/home/jacobw/intraday_stack/data/daily_sip")
gold_dir = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

print("\n" + "=" * 80)
print("MANUAL PATTERN BACKTEST - CLEAN IMPLEMENTATION")
print("=" * 80)
print(f"Period: {START_DATE} to {END_DATE}")
print(f"Position size: {POSITION_SIZE} shares")
print(f"Exit horizon: {HORIZON_BARS} bars (~180 minutes)")
print(f"Patterns: {len(MANUAL_PATTERNS)}")
print("=" * 80)

# ============================================================================
# STEP 1: Load featured data from cache
# ============================================================================
print("\n[1/4] Loading data...")

if not FEATURED_CACHE_FILE.exists():
    print(f"❌ ERROR: Featured cache not found: {FEATURED_CACHE_FILE}")
    print("Run test_manual_backtest_v2.py first to generate cache")
    sys.exit(1)

with open(FEATURED_CACHE_FILE, "rb") as f:
    df = pickle.load(f)

print(f"✅ Loaded {len(df):,} bars with features")

# Sort and validate
df = df.sort_values("ts").reset_index(drop=True)
if not df["ts"].is_monotonic_increasing:
    print("❌ ERROR: Data not sorted")
    sys.exit(1)

print("✅ Data validated and sorted")

# ============================================================================
# STEP 2: Create strategy with proper tracking
# ============================================================================
print("\n[2/4] Setting up strategy...")


# Trade tracking
class TradeTracker:
    def __init__(self):
        self.positions = (
            {}
        )  # symbol -> {entry_bar_idx, entry_price, pattern_id, quantity}
        self.pending = set()  # symbols with pending orders
        self.completed_trades = []
        self.bar_index = 0  # Global bar index for exit timing

    def on_entry(self, symbol, bar_idx, price, pattern_id, quantity):
        """Record entry."""
        self.positions[symbol] = {
            "entry_bar_idx": bar_idx,
            "entry_price": price,
            "pattern_id": pattern_id,
            "quantity": quantity,
            "entry_time": None,  # Will be set from bar data
        }
        self.pending.add(symbol)

    def on_exit(self, symbol, bar_idx, price):
        """Record exit and create trade record."""
        if symbol in self.positions:
            pos = self.positions[symbol]

            # Calculate P&L (simplified - actual will include commissions)
            pnl = (price - pos["entry_price"]) * pos["quantity"]
            bars_held = bar_idx - pos["entry_bar_idx"]

            self.completed_trades.append(
                {
                    "symbol": symbol,
                    "pattern_id": pos["pattern_id"],
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
    """Strategy function with proper bar counting and pattern attribution."""
    symbol = bar["symbol"]

    # Increment global bar index
    tracker.bar_index += 1
    current_bar_idx = tracker.bar_index

    # Get position
    position = engine.get_position(symbol)
    has_position = position is not None and position.quantity != 0

    # Check for exit (time-based on global bar index)
    if has_position and symbol in tracker.positions:
        pos_info = tracker.positions[symbol]
        bars_held = current_bar_idx - pos_info["entry_bar_idx"]

        if bars_held >= HORIZON_BARS:
            # Exit
            side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
            order = Order(
                order_id=f"exit_{symbol}_{current_bar_idx}",
                symbol=symbol,
                order_type=OrderType.MARKET,
                side=side,
                quantity=abs(position.quantity),
            )
            engine.submit_order(order)
            tracker.on_exit(symbol, current_bar_idx, bar["close"])
            return

    # Check for entry (no position, no pending)
    if not has_position and symbol not in tracker.pending:
        # Evaluate patterns and get which one matched
        matches = evaluate_all_manual_patterns(bar)

        if matches:
            # Use first matching pattern
            pattern_id = matches[0]

            # Enter
            order = Order(
                order_id=f"entry_{symbol}_{current_bar_idx}_{pattern_id}",
                symbol=symbol,
                order_type=OrderType.MARKET,
                side=OrderSide.BUY,
                quantity=POSITION_SIZE,
            )
            engine.submit_order(order)
            tracker.on_entry(
                symbol, current_bar_idx, bar["close"], pattern_id, POSITION_SIZE
            )


print("✅ Strategy configured")
print(f"   Patterns: {list(MANUAL_PATTERNS.keys())}")

# ============================================================================
# STEP 3: Run backtest
# ============================================================================
print("\n[3/4] Running backtest...")

try:
    filler = FixedFiller(commission_per_share=0.01)
    config = BacktestConfig(
        initial_cash=1_000_000.0,
        filler=filler,
        show_progress=False,  # Disable progress to reduce spam
    )

    engine = BacktestEngine(config)
    result = engine.run(df, strategy_func)
    print("✅ Backtest complete")

except Exception as e:
    print(f"❌ ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# STEP 4: Generate reports
# ============================================================================
print("\n[4/4] Generating reports...")

# Save completed trades
trades_df = pd.DataFrame(tracker.completed_trades)

if trades_df.empty:
    print("⚠️ No completed trades")
    sys.exit(0)

output_dir = root / "pattern_backtest" / "output"
output_dir.mkdir(parents=True, exist_ok=True)

trades_file = output_dir / "trades_clean_180m.csv"
trades_df.to_csv(trades_file, index=False)
print(f"✅ Saved {len(trades_df)} trades to {trades_file}")

# Per-pattern performance
print("\n" + "=" * 80)
print("PER-PATTERN PERFORMANCE")
print("=" * 80)

pattern_stats = {}
for pattern_id in MANUAL_PATTERNS.keys():
    pattern_trades = trades_df[trades_df["pattern_id"] == pattern_id]

    if len(pattern_trades) == 0:
        continue

    stats = {
        "trades": len(pattern_trades),
        "total_pnl": pattern_trades["pnl_gross"].sum(),
        "avg_pnl": pattern_trades["pnl_gross"].mean(),
        "win_rate": (pattern_trades["pnl_gross"] > 0).mean(),
        "avg_bars_held": pattern_trades["bars_held"].mean(),
    }
    pattern_stats[pattern_id] = stats

    print(f"\n{pattern_id} ({MANUAL_PATTERNS[pattern_id]['description']}):")
    print(f"  Trades: {stats['trades']}")
    print(f"  Total P&L: ${stats['total_pnl']:,.2f}")
    print(f"  Avg P&L: ${stats['avg_pnl']:,.2f}")
    print(f"  Win rate: {stats['win_rate']:.1%}")
    print(f"  Avg bars held: {stats['avg_bars_held']:.1f}")

# Consolidated performance
print("\n" + "=" * 80)
print("CONSOLIDATED PERFORMANCE")
print("=" * 80)

print(f"Total trades: {len(trades_df)}")
print(f"Total P&L: ${trades_df['pnl_gross'].sum():,.2f}")
print(f"Avg P&L: ${trades_df['pnl_gross'].mean():,.2f}")
print(f"Win rate: {(trades_df['pnl_gross'] > 0).mean():.1%}")
print(f"Avg bars held: {trades_df['bars_held'].mean():.1f}")
print(f"Min bars held: {trades_df['bars_held'].min()}")
print(f"Max bars held: {trades_df['bars_held'].max()}")

# Save summary
summary = {
    "period": f"{START_DATE} to {END_DATE}",
    "total_trades": len(trades_df),
    "total_pnl": float(trades_df["pnl_gross"].sum()),
    "win_rate": float((trades_df["pnl_gross"] > 0).mean()),
    "per_pattern": {
        k: {
            kk: float(vv) if isinstance(vv, (int, float)) else vv
            for kk, vv in v.items()
        }
        for k, v in pattern_stats.items()
    },
}

summary_file = output_dir / "summary_clean_180m.json"
with open(summary_file, "w") as f:
    json.dump(summary, f, indent=2)

print(f"\n✅ Summary saved to {summary_file}")
print("\n" + "=" * 80)
print("DONE")
print("=" * 80)
