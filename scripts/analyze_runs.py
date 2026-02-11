#!/usr/bin/env python3
"""
Comprehensive analysis of all test runs in /home/jacobw/quantstack/runs/
"""

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def extract_run_data(runs_dir):
    """Extract data from all run directories"""
    runs_data = []

    for run_dir in Path(runs_dir).iterdir():
        if not run_dir.is_dir() or run_dir.name == ".gitkeep":
            continue

        run_info = {
            "run_id": run_dir.name,
            "run_path": str(run_dir),
        }

        # Extract timestamp from directory name if present
        try:
            if "_" in run_dir.name and any(c.isdigit() for c in run_dir.name):
                parts = run_dir.name.split("_")
                for part in parts:
                    if len(part) == 8 and part.isdigit():
                        run_info["date"] = datetime.strptime(part, "%Y%m%d").date()
                    elif len(part) == 6 and part.isdigit():
                        run_info["time"] = datetime.strptime(part, "%H%M%S").time()
        except:
            pass

        # Read metrics.json
        metrics_file = run_dir / "metrics.json"
        if metrics_file.exists():
            try:
                with open(metrics_file) as f:
                    run_info["metrics"] = json.load(f)
            except Exception as e:
                run_info["metrics_error"] = str(e)

        # Read inputs_checksum.json
        checksum_file = run_dir / "inputs_checksum.json"
        if checksum_file.exists():
            try:
                with open(checksum_file) as f:
                    run_info["checksums"] = json.load(f)
            except Exception as e:
                run_info["checksums_error"] = str(e)

        runs_data.append(run_info)

    return runs_data


def analyze_performance_metrics(runs_data):
    """Analyze performance metrics across all runs"""
    analysis = {
        "total_runs": len(runs_data),
        "runs_with_metrics": sum(1 for r in runs_data if "metrics" in r),
        "runs_with_checksums": sum(1 for r in runs_data if "checksums" in r),
        "zero_trades_runs": 0,
        "profitable_runs": 0,
        "losing_runs": 0,
    }

    # Extract numerical metrics
    trades_list = []
    returns_list = []
    sharpe_list = []
    win_rates = []

    for run in runs_data:
        if "metrics" in run:
            metrics = run["metrics"]

            # Trade counts
            trades = metrics.get("trades", 0)
            trades_list.append(trades)
            if trades == 0:
                analysis["zero_trades_runs"] += 1

            # Returns
            if "total_return" in metrics:
                returns_list.append(metrics["total_return"])
                if metrics["total_return"] > 0:
                    analysis["profitable_runs"] += 1
                elif metrics["total_return"] < 0:
                    analysis["losing_runs"] += 1

            # Sharpe ratios
            if "sharpe_ratio" in metrics:
                sharpe_list.append(metrics["sharpe_ratio"])

            # Win rates
            if "win_rate" in metrics:
                win_rates.append(metrics["win_rate"])

    # Calculate statistics
    if trades_list:
        analysis["trade_stats"] = {
            "total_trades": sum(trades_list),
            "avg_trades_per_run": statistics.mean(trades_list),
            "median_trades": statistics.median(trades_list),
            "max_trades": max(trades_list),
            "min_trades": min(trades_list),
            "std_trades": statistics.stdev(trades_list) if len(trades_list) > 1 else 0,
        }

    if returns_list:
        analysis["return_stats"] = {
            "mean_return": statistics.mean(returns_list),
            "median_return": statistics.median(returns_list),
            "max_return": max(returns_list),
            "min_return": min(returns_list),
            "std_return": (
                statistics.stdev(returns_list) if len(returns_list) > 1 else 0
            ),
            "positive_returns": sum(1 for r in returns_list if r > 0),
            "negative_returns": sum(1 for r in returns_list if r < 0),
        }

    if sharpe_list:
        analysis["sharpe_stats"] = {
            "mean_sharpe": statistics.mean(sharpe_list),
            "median_sharpe": statistics.median(sharpe_list),
            "max_sharpe": max(sharpe_list),
            "min_sharpe": min(sharpe_list),
        }

    if win_rates:
        analysis["win_rate_stats"] = {
            "mean_win_rate": statistics.mean(win_rates),
            "median_win_rate": statistics.median(win_rates),
            "max_win_rate": max(win_rates),
            "min_win_rate": min(win_rates),
        }

    return analysis


def analyze_checksums(runs_data):
    """Analyze hash values and seeds across runs"""
    hash_analysis = {
        "unique_bar_hashes": set(),
        "unique_feature_hashes": set(),
        "unique_sip_hashes": set(),
        "unique_config_hashes": set(),
        "seeds": [],
        "hash_combinations": Counter(),
    }

    for run in runs_data:
        if "checksums" in run:
            checksums = run["checksums"]

            if "bars_norm_hash" in checksums:
                hash_analysis["unique_bar_hashes"].add(checksums["bars_norm_hash"])

            if "features_hash" in checksums:
                hash_analysis["unique_feature_hashes"].add(checksums["features_hash"])

            if "sip_hash" in checksums:
                hash_analysis["unique_sip_hashes"].add(checksums["sip_hash"])

            if "config_hash" in checksums:
                hash_analysis["unique_config_hashes"].add(checksums["config_hash"])

            if "seed" in checksums:
                hash_analysis["seeds"].append(checksums["seed"])

            # Track hash combinations
            combo = (
                f"{checksums.get('bars_norm_hash', 'none')[:8]}_"
                + f"{checksums.get('features_hash', 'none')[:8]}_"
                + f"{checksums.get('sip_hash', 'none')[:8]}_"
                + f"{checksums.get('config_hash', 'none')[:8]}"
            )
            hash_analysis["hash_combinations"][combo] += 1

    # Convert sets to counts
    hash_analysis["unique_bar_hashes"] = len(hash_analysis["unique_bar_hashes"])
    hash_analysis["unique_feature_hashes"] = len(hash_analysis["unique_feature_hashes"])
    hash_analysis["unique_sip_hashes"] = len(hash_analysis["unique_sip_hashes"])
    hash_analysis["unique_config_hashes"] = len(hash_analysis["unique_config_hashes"])

    if hash_analysis["seeds"]:
        hash_analysis["seed_stats"] = {
            "unique_seeds": len(set(hash_analysis["seeds"])),
            "min_seed": min(hash_analysis["seeds"]),
            "max_seed": max(hash_analysis["seeds"]),
            "seed_distribution": Counter(hash_analysis["seeds"]),
        }

    return hash_analysis


def identify_patterns(runs_data):
    """Identify notable patterns and outliers"""
    patterns = {
        "best_performing_runs": [],
        "worst_performing_runs": [],
        "highest_trade_count_runs": [],
        "zero_trade_runs": [],
        "run_types": Counter(),
        "strategy_performance": defaultdict(list),
    }

    runs_with_performance = []

    for run in runs_data:
        if "metrics" not in run:
            continue

        metrics = run["metrics"]
        run_id = run["run_id"]

        # Categorize run type
        if "vwap" in run_id.lower():
            patterns["run_types"]["vwap"] += 1
        elif "hmm" in run_id.lower():
            patterns["run_types"]["hmm"] += 1
        else:
            patterns["run_types"]["other"] += 1

        # Track performance
        if "total_return" in metrics:
            runs_with_performance.append((run_id, metrics["total_return"], metrics))

        # Track trade counts
        trades = metrics.get("trades", 0)
        if trades == 0:
            patterns["zero_trade_runs"].append(run_id)

        # Strategy-specific performance
        strategy = metrics.get("strategy", "unknown")
        if "total_return" in metrics:
            patterns["strategy_performance"][strategy].append(metrics["total_return"])

    # Sort by performance
    if runs_with_performance:
        runs_with_performance.sort(key=lambda x: x[1], reverse=True)
        patterns["best_performing_runs"] = runs_with_performance[:5]
        patterns["worst_performing_runs"] = runs_with_performance[-5:]

    return patterns


def main():
    runs_dir = "/home/jacobw/quantstack/runs"

    print("Extracting run data...")
    runs_data = extract_run_data(runs_dir)

    print("Analyzing performance metrics...")
    performance_analysis = analyze_performance_metrics(runs_data)

    print("Analyzing checksums...")
    hash_analysis = analyze_checksums(runs_data)

    print("Identifying patterns...")
    patterns = identify_patterns(runs_data)

    # Generate comprehensive report
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_runs_analyzed": len(runs_data),
            "runs_with_metrics": performance_analysis["runs_with_metrics"],
            "runs_with_checksums": performance_analysis["runs_with_checksums"],
            "zero_trades_runs": performance_analysis["zero_trades_runs"],
            "profitable_runs": performance_analysis.get("profitable_runs", 0),
            "losing_runs": performance_analysis.get("losing_runs", 0),
        },
        "performance_analysis": performance_analysis,
        "hash_analysis": hash_analysis,
        "patterns": patterns,
    }

    # Save detailed data
    with open("/home/jacobw/quantstack/runs_analysis.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Print summary
    print("\n" + "=" * 60)
    print("RUNS ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"Total runs analyzed: {report['summary']['total_runs_analyzed']}")
    print(f"Runs with metrics: {report['summary']['runs_with_metrics']}")
    print(f"Runs with checksums: {report['summary']['runs_with_checksums']}")
    print(f"Zero-trade runs: {report['summary']['zero_trades_runs']}")
    print(f"Profitable runs: {report['summary']['profitable_runs']}")
    print(f"Losing runs: {report['summary']['losing_runs']}")

    if "trade_stats" in performance_analysis:
        ts = performance_analysis["trade_stats"]
        print("\nTrade Statistics:")
        print(f"  Total trades across all runs: {ts['total_trades']}")
        print(f"  Average trades per run: {ts['avg_trades_per_run']:.1f}")
        print(f"  Median trades per run: {ts['median_trades']}")
        print(f"  Max trades in a run: {ts['max_trades']}")
        print(f"  Min trades in a run: {ts['min_trades']}")

    if "return_stats" in performance_analysis:
        rs = performance_analysis["return_stats"]
        print("\nReturn Statistics:")
        print(
            f"  Mean return: {rs['mean_return']:.4f} ({rs['mean_return'] * 100:.2f}%)"
        )
        print(
            f"  Median return: {rs['median_return']:.4f} ({rs['median_return'] * 100:.2f}%)"
        )
        print(f"  Best return: {rs['max_return']:.4f} ({rs['max_return'] * 100:.2f}%)")
        print(f"  Worst return: {rs['min_return']:.4f} ({rs['min_return'] * 100:.2f}%)")
        print(
            f"  Positive returns: {rs['positive_returns']}/{len(runs_data)} ({rs['positive_returns'] / len(runs_data) * 100:.1f}%)"
        )

    print("\nHash Analysis:")
    print(f"  Unique bar data hashes: {hash_analysis['unique_bar_hashes']}")
    print(f"  Unique feature hashes: {hash_analysis['unique_feature_hashes']}")
    print(f"  Unique SIP hashes: {hash_analysis['unique_sip_hashes']}")
    print(f"  Unique config hashes: {hash_analysis['unique_config_hashes']}")

    if "seed_stats" in hash_analysis:
        ss = hash_analysis["seed_stats"]
        print(f"  Unique seeds: {ss['unique_seeds']}")
        print(f"  Seed range: {ss['min_seed']} - {ss['max_seed']}")

    print("\nRun Types:")
    for run_type, count in patterns["run_types"].items():
        print(f"  {run_type}: {count}")

    if patterns["best_performing_runs"]:
        print("\nTop 5 Performing Runs:")
        for run_id, return_pct, metrics in patterns["best_performing_runs"]:
            print(
                f"  {run_id}: {return_pct:.4f} ({return_pct * 100:.2f}%) - {metrics.get('trades', 0)} trades"
            )

    if patterns["zero_trade_runs"]:
        print(f"\nZero Trade Runs ({len(patterns['zero_trade_runs'])}):")
        for run_id in patterns["zero_trade_runs"][:10]:  # Show first 10
            print(f"  {run_id}")
        if len(patterns["zero_trade_runs"]) > 10:
            print(f"  ... and {len(patterns['zero_trade_runs']) - 10} more")

    print("\nDetailed report saved to: /home/jacobw/quantstack/runs_analysis.json")

    return report


if __name__ == "__main__":
    main()
