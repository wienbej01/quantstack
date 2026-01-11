#!/usr/bin/env python3
"""Generate consolidated performance report across multiple methods."""

import argparse
import json
from pathlib import Path

import pandas as pd


def load_method_results(output_dir: Path) -> dict:
    """Load results for all methods in output directory.

    Args:
        output_dir: Directory containing method results

    Returns:
        Dictionary mapping method_id to results
    """
    results = {}

    # Find all performance metrics files
    for metrics_file in output_dir.glob("performance_metrics_*.json"):
        with open(metrics_file) as f:
            metrics = json.load(f)

        method_id = metrics["method_id"]

        # Load trades
        trades_file = output_dir / f"trades_{method_id}.csv"
        if trades_file.exists():
            trades = pd.read_csv(trades_file)
        else:
            trades = pd.DataFrame()

        results[method_id] = {
            "metrics": metrics,
            "trades": trades,
        }

    return results


def generate_consolidated_report(output_dir: Path):
    """Generate consolidated performance report.

    Args:
        output_dir: Directory containing method results
    """
    results = load_method_results(output_dir)

    if not results:
        print("No results found in output directory")
        return

    print("=" * 80)
    print("CONSOLIDATED PERFORMANCE REPORT")
    print("=" * 80)
    print(f"Output directory: {output_dir}")
    print(f"Methods: {len(results)}")
    print("=" * 80)

    # Per-method performance
    print("\n## PER-METHOD PERFORMANCE\n")

    metrics_rows = []
    for method_id, data in results.items():
        metrics = data["metrics"]
        metrics_rows.append(
            {
                "Method": method_id,
                "Trades": metrics["total_trades"],
                "Return": f"{metrics['total_return']:.2%}",
                "Sharpe": f"{metrics['sharpe_ratio']:.2f}",
                "Win Rate": f"{metrics['win_rate']:.2%}",
                "Max DD": f"{metrics['max_drawdown']:.2%}",
                "Profit Factor": f"{metrics['profit_factor']:.2f}",
            }
        )

    metrics_df = pd.DataFrame(metrics_rows)
    print(metrics_df.to_string(index=False))

    # Consolidated metrics
    print("\n## CONSOLIDATED METRICS\n")

    all_trades = pd.concat(
        [data["trades"] for data in results.values()], ignore_index=True
    )

    if not all_trades.empty:
        total_trades = len(all_trades)
        total_pnl = all_trades["pnl"].sum() if "pnl" in all_trades.columns else 0

        print(f"Total trades (all methods): {total_trades}")
        print(f"Total P&L (all methods): ${total_pnl:,.2f}")

        # Per-method trade breakdown
        print("\n## TRADE BREAKDOWN BY METHOD\n")
        trade_counts = all_trades.groupby("method_id").size()
        print(trade_counts.to_string())

    # Save consolidated report
    report_path = output_dir / "consolidated_report.txt"
    with open(report_path, "w") as f:
        f.write("=" * 80 + "\n")
        f.write("CONSOLIDATED PERFORMANCE REPORT\n")
        f.write("=" * 80 + "\n\n")
        f.write(metrics_df.to_string(index=False))
        f.write("\n\n")
        if not all_trades.empty:
            f.write(f"Total trades: {total_trades}\n")
            f.write(f"Total P&L: ${total_pnl:,.2f}\n")

    print(f"\nConsolidated report saved to {report_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate consolidated performance report"
    )
    parser.add_argument(
        "--output-dir", required=True, help="Output directory with method results"
    )

    args = parser.parse_args()

    generate_consolidated_report(Path(args.output_dir))


if __name__ == "__main__":
    main()
