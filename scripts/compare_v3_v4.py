#!/usr/bin/env python3
"""Compare v3 (current) vs v4 (SMB) performance."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
LOGGER = logging.getLogger(__name__)


def load_v3_results() -> dict:
    """Load v3 results from V3_BACKTEST_RESULTS.md."""

    # Hardcoded from V3_BACKTEST_RESULTS.md
    return {
        "version": "v3",
        "universe": "97 symbols (liquidity filter)",
        "total_trades": 65,
        "trading_days": 31,
        "trades_per_day": 2.1,
        "winners": 27,
        "losers": 38,
        "win_rate": 0.423,
        "avg_r_multiple": 1.6,
        "monthly_pnl": 18.94,
        "return_pct": 0.19,  # $18.94 / $10,000
    }


def load_v4_results(results_path: Path) -> dict:
    """Load v4 results from backtest output."""

    if not results_path.exists():
        raise FileNotFoundError(f"v4 results not found: {results_path}")

    # Parse results file
    results = {}
    with open(results_path) as f:
        for line in f:
            if "Total trades:" in line:
                results["total_trades"] = int(line.split(":")[1].strip())
            elif "Trading days:" in line:
                results["trading_days"] = int(line.split(":")[1].strip())
            elif "Trades/day:" in line:
                results["trades_per_day"] = float(line.split(":")[1].strip())
            elif "Winners:" in line:
                results["winners"] = int(line.split(":")[1].strip())
            elif "Losers:" in line:
                results["losers"] = int(line.split(":")[1].strip())
            elif "Win rate:" in line:
                results["win_rate"] = (
                    float(line.split(":")[1].strip().rstrip("%")) / 100
                )
            elif "Avg R-multiple:" in line:
                results["avg_r_multiple"] = float(line.split(":")[1].strip())
            elif "Total PnL:" in line:
                pnl_str = line.split(":")[1].strip().lstrip("$")
                results["total_pnl"] = float(pnl_str)
            elif "Return:" in line:
                results["return_pct"] = (
                    float(line.split(":")[1].strip().rstrip("%")) / 100
                )

    results["version"] = "v4"
    results["universe"] = "SMB catalyst-driven (200-400 symbols)"

    # Calculate monthly PnL (assuming same period)
    if "total_pnl" in results and "trading_days" in results:
        results["monthly_pnl"] = results["total_pnl"] * (31 / results["trading_days"])

    return results


def compare_results(v3: dict, v4: dict) -> pd.DataFrame:
    """Create comparison table."""

    metrics = [
        ("Universe", "universe", "str"),
        ("Total Trades", "total_trades", "int"),
        ("Trading Days", "trading_days", "int"),
        ("Trades/Day", "trades_per_day", "float1"),
        ("Winners", "winners", "int"),
        ("Losers", "losers", "int"),
        ("Win Rate", "win_rate", "pct"),
        ("Avg R-Multiple", "avg_r_multiple", "float1"),
        ("Monthly PnL", "monthly_pnl", "dollar"),
        ("Return %", "return_pct", "pct"),
    ]

    rows = []
    for label, key, fmt in metrics:
        v3_val = v3.get(key, "N/A")
        v4_val = v4.get(key, "N/A")

        # Format values
        if fmt == "int":
            v3_str = f"{v3_val:,}" if isinstance(v3_val, (int, float)) else v3_val
            v4_str = f"{v4_val:,}" if isinstance(v4_val, (int, float)) else v4_val
        elif fmt == "float1":
            v3_str = f"{v3_val:.1f}" if isinstance(v3_val, (int, float)) else v3_val
            v4_str = f"{v4_val:.1f}" if isinstance(v4_val, (int, float)) else v4_val
        elif fmt == "pct":
            v3_str = (
                f"{v3_val*100:.1f}%" if isinstance(v3_val, (int, float)) else v3_val
            )
            v4_str = (
                f"{v4_val*100:.1f}%" if isinstance(v4_val, (int, float)) else v4_val
            )
        elif fmt == "dollar":
            v3_str = f"${v3_val:.2f}" if isinstance(v3_val, (int, float)) else v3_val
            v4_str = f"${v4_val:.2f}" if isinstance(v4_val, (int, float)) else v4_val
        else:
            v3_str = str(v3_val)
            v4_str = str(v4_val)

        # Calculate improvement
        if (
            isinstance(v3_val, (int, float))
            and isinstance(v4_val, (int, float))
            and v3_val != 0
        ):
            improvement = ((v4_val - v3_val) / v3_val) * 100
            improvement_str = f"{improvement:+.1f}%"
        else:
            improvement_str = "N/A"

        rows.append(
            {
                "Metric": label,
                "v3 (Current)": v3_str,
                "v4 (SMB)": v4_str,
                "Improvement": improvement_str,
            }
        )

    return pd.DataFrame(rows)


def main():
    v4_results_path = Path(
        "artefacts/extensions/intraday_ml/v4_smb/backtest_results.txt"
    )
    output_path = Path("artefacts/extensions/intraday_ml/v4_smb/comparison_v3_v4.txt")

    LOGGER.info("=" * 80)
    LOGGER.info("v3 vs v4 Performance Comparison")
    LOGGER.info("=" * 80)

    # Load results
    LOGGER.info("Loading v3 results...")
    v3 = load_v3_results()

    LOGGER.info("Loading v4 results...")
    v4 = load_v4_results(v4_results_path)

    # Create comparison
    comparison = compare_results(v3, v4)

    # Display
    LOGGER.info("")
    LOGGER.info("Comparison Table:")
    LOGGER.info("")
    print(comparison.to_string(index=False))

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("v3 vs v4 Performance Comparison\n")
        f.write("=" * 80 + "\n\n")
        f.write(comparison.to_string(index=False))
        f.write("\n\n")
        f.write("=" * 80 + "\n")
        f.write("Key Improvements:\n")
        f.write("=" * 80 + "\n\n")

        # Calculate key improvements
        trades_improvement = (
            (v4["trades_per_day"] - v3["trades_per_day"]) / v3["trades_per_day"]
        ) * 100
        win_rate_improvement = (
            (v4["win_rate"] - v3["win_rate"]) / v3["win_rate"]
        ) * 100
        pnl_improvement = (
            (v4["monthly_pnl"] - v3["monthly_pnl"]) / v3["monthly_pnl"]
        ) * 100

        f.write(
            f"1. Trades/Day: {v3['trades_per_day']:.1f} → {v4['trades_per_day']:.1f} ({trades_improvement:+.1f}%)\n"
        )
        f.write(
            f"2. Win Rate: {v3['win_rate']*100:.1f}% → {v4['win_rate']*100:.1f}% ({win_rate_improvement:+.1f}%)\n"
        )
        f.write(
            f"3. Monthly PnL: ${v3['monthly_pnl']:.2f} → ${v4['monthly_pnl']:.2f} ({pnl_improvement:+.1f}%)\n"
        )
        f.write("4. Universe: 97 symbols → 200-400 symbols (catalyst-driven)\n")
        f.write("5. Selectivity: Liquidity filter → SMB gap/RVOL/ATR filters\n")

    LOGGER.info("")
    LOGGER.info("Comparison saved to: %s", output_path)
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()
