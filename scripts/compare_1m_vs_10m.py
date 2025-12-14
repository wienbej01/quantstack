#!/usr/bin/env python3
"""Compare 1m vs 10m results."""


import pandas as pd

print("=" * 80)
print("1M vs 10M COMPARISON")
print("=" * 80)
print()

# Load results
metrics_1m = pd.read_csv("run/rolling_results/metrics.csv")
metrics_10m = pd.read_csv("run/rolling_results_10m/metrics.csv")

trades_1m = pd.read_csv("run/rolling_results/trades.csv")
trades_10m = pd.read_csv("run/rolling_results_10m/trades.csv")

# Overall comparison
print("OVERALL PERFORMANCE")
print("-" * 80)
print(f"{'Metric':<30} {'1m':<20} {'10m':<20}")
print("-" * 80)

print(f"{'Total Trades':<30} {len(trades_1m):<20,} {len(trades_10m):<20,}")
print(
    f"{'Avg Win Rate':<30} {metrics_1m['win_rate'].mean():<20.2%} {metrics_10m['win_rate'].mean():<20.2%}"
)
print(
    f"{'Final Equity':<30} ${metrics_1m['final_equity'].iloc[-1]:<19,.2f} ${metrics_10m['final_equity'].iloc[-1]:<19,.2f}"
)
print(
    f"{'Total P&L':<30} {(metrics_1m['final_equity'].iloc[-1]/10000-1):<20.2%} {(metrics_10m['final_equity'].iloc[-1]/10000-1):<20.2%}"
)
print(
    f"{'Avg P&L per Trade':<30} ${trades_1m['net_pnl'].mean():<19.2f} ${trades_10m['net_pnl'].mean():<19.2f}"
)
print(
    f"{'Avg R-Multiple':<30} {trades_1m['r_multiple'].mean():<20.2f} {trades_10m['r_multiple'].mean():<20.2f}"
)
print()

# Exit reasons
print("EXIT REASONS")
print("-" * 80)
print(f"{'Reason':<30} {'1m Count':<15} {'1m %':<15} {'10m Count':<15} {'10m %':<15}")
print("-" * 80)

for reason in ["stop_hit", "target_hit", "time_exit"]:
    count_1m = (trades_1m["exit_reason"] == reason).sum()
    pct_1m = count_1m / len(trades_1m) * 100
    count_10m = (trades_10m["exit_reason"] == reason).sum()
    pct_10m = count_10m / len(trades_10m) * 100
    print(
        f"{reason:<30} {count_1m:<15,} {pct_1m:<15.1f} {count_10m:<15,} {pct_10m:<15.1f}"
    )
print()

# Monthly comparison
print("MONTHLY COMPARISON (First 10 months)")
print("-" * 80)
print(
    f"{'Month':<12} {'1m Trades':<12} {'1m P&L':<12} {'10m Trades':<12} {'10m P&L':<12}"
)
print("-" * 80)

for i in range(min(10, len(metrics_1m), len(metrics_10m))):
    month_1m = metrics_1m.iloc[i]
    month_10m = metrics_10m.iloc[i]
    print(
        f"{month_1m['oos_month']:<12} {month_1m['signals']:<12,} {month_1m['total_pnl']:<12.2%} "
        f"{month_10m['signals']:<12,} {month_10m['total_pnl']:<12.2%}"
    )
print()

# Cost analysis
print("COST ANALYSIS")
print("-" * 80)
print(f"{'Metric':<30} {'1m':<20} {'10m':<20}")
print("-" * 80)
print(
    f"{'Total Fees':<30} ${trades_1m['fee'].sum():<19,.2f} ${trades_10m['fee'].sum():<19,.2f}"
)
print(
    f"{'Total Spread':<30} ${trades_1m['spread'].sum():<19,.2f} ${trades_10m['spread'].sum():<19,.2f}"
)
print(
    f"{'Total Costs':<30} ${(trades_1m['fee'].sum() + trades_1m['spread'].sum()):<19,.2f} "
    f"${(trades_10m['fee'].sum() + trades_10m['spread'].sum()):<19,.2f}"
)
print(
    f"{'Avg Cost per Trade':<30} ${(trades_1m['fee'].mean() + trades_1m['spread'].mean()):<19.2f} "
    f"${(trades_10m['fee'].mean() + trades_10m['spread'].mean()):<19.2f}"
)
print()

# Winner
print("=" * 80)
if metrics_10m["final_equity"].iloc[-1] > metrics_1m["final_equity"].iloc[-1]:
    diff = metrics_10m["final_equity"].iloc[-1] - metrics_1m["final_equity"].iloc[-1]
    print(
        f"✓ 10M WINS by ${diff:,.2f} ({diff/metrics_1m['final_equity'].iloc[-1]:.2%})"
    )
else:
    diff = metrics_1m["final_equity"].iloc[-1] - metrics_10m["final_equity"].iloc[-1]
    print(
        f"✓ 1M WINS by ${diff:,.2f} ({diff/metrics_10m['final_equity'].iloc[-1]:.2%})"
    )
print("=" * 80)
