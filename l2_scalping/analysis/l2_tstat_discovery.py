#!/usr/bin/env python3
"""
L2 Pattern Discovery with T-Statistic Ranking

Replaces lift-based pattern discovery with statistically rigorous t-stat ranking.
Computes actual trading metrics: expectancy, win rate, profit factor, Sharpe.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_l2_data():
    """Load L2 data from parquet files."""
    l2_dir = Path("/home/jacobw/quantstack/data/l2/l2_maximum/features")

    all_data = []
    for date_dir in l2_dir.glob("date=*"):
        for symbol_dir in date_dir.glob("symbol=*"):
            for pq_file in symbol_dir.glob("*.parquet"):
                try:
                    df = pd.read_parquet(pq_file)
                    df["symbol"] = symbol_dir.name.replace("symbol=", "")
                    df["date"] = date_dir.name.replace("date=", "")
                    all_data.append(df)
                except Exception as e:
                    logger.warning(f"Error loading {pq_file}: {e}")

    if not all_data:
        logger.error("No L2 data found!")
        return pd.DataFrame()

    df = pd.concat(all_data, ignore_index=True)
    logger.info(f"Loaded {len(df):,} L2 snapshots")
    return df


def compute_forward_returns(
    df: pd.DataFrame, horizons: list[int] = [60, 120, 300]
) -> pd.DataFrame:
    """Compute forward returns in basis points."""
    result = df.copy()

    for symbol, group in result.groupby("symbol"):
        group = group.sort_values("ts_epoch")

        for horizon in horizons:
            # Forward mid price change in bps
            fwd_mid = group["mid"].shift(-horizon)
            fwd_ret = (fwd_mid / group["mid"] - 1) * 10000  # bps
            result.loc[group.index, f"fwd_ret_{horizon}s"] = fwd_ret

    return result


def compute_pattern_stats(returns: pd.Series, min_samples: int = 50) -> dict | None:
    """Compute trading statistics for a pattern's returns."""
    returns = returns.dropna()
    n = len(returns)

    if n < min_samples:
        return None

    mean_ret = returns.mean()
    std_ret = returns.std()

    # t-statistic
    if std_ret > 0:
        t_stat = mean_ret / (std_ret / np.sqrt(n))
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    else:
        t_stat = 0.0
        p_value = 1.0

    # Win rate
    wins = returns > 0
    win_rate = wins.mean()

    # Avg win / Avg loss
    avg_win = returns[wins].mean() if wins.any() else 0.0
    avg_loss = abs(returns[~wins].mean()) if (~wins).any() else 0.0

    # Profit factor
    gross_profit = returns[wins].sum() if wins.any() else 0.0
    gross_loss = abs(returns[~wins].sum()) if (~wins).any() else 0.001
    profit_factor = gross_profit / gross_loss

    # Sharpe (annualized)
    if std_ret > 0:
        # Assuming ~2 trades/min, 390 min/day, 252 days
        sharpe = mean_ret / std_ret * np.sqrt(252 * 390)
    else:
        sharpe = 0.0

    return {
        "t_stat": t_stat,
        "p_value": p_value,
        "expectancy_bps": mean_ret,
        "win_rate": win_rate,
        "avg_win_bps": avg_win,
        "avg_loss_bps": avg_loss,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "n_trades": n,
        "std_bps": std_ret,
    }


def discover_l2_patterns(
    df: pd.DataFrame,
    return_col: str = "fwd_ret_300s",
    min_t_stat: float = 2.0,
    min_expectancy: float = 0.5,  # 0.5 bps minimum
    min_trades: int = 50,
    max_patterns: int = 20,
) -> pd.DataFrame:
    """Discover L2 patterns ranked by t-statistic."""

    logger.info(f"\nDiscovering patterns for {return_col}")
    logger.info(
        f"Criteria: t-stat >= {min_t_stat}, expectancy >= {min_expectancy} bps, n >= {min_trades}"
    )

    # Define L2 feature thresholds to test
    rules = []

    # OBI thresholds
    for obi_thresh in [0.1, 0.2, 0.3, 0.5]:
        rules.append((f"obi_1 > {obi_thresh}", df["obi_1"] > obi_thresh, "LONG"))
        rules.append((f"obi_1 < -{obi_thresh}", df["obi_1"] < -obi_thresh, "SHORT"))

    # Delta OBI thresholds
    for col in ["d_obi_1_5s", "d_obi_1_15s", "d_obi_1_30s"]:
        if col not in df.columns:
            continue
        for thresh in [0.05, 0.1, 0.2]:
            rules.append((f"{col} > {thresh}", df[col] > thresh, "LONG"))
            rules.append((f"{col} < -{thresh}", df[col] < -thresh, "SHORT"))

    # Depth thresholds
    for col in ["depth_bid_k", "depth_ask_k"]:
        if col not in df.columns:
            continue
        for thresh in [10, 20, 30, 50]:
            direction = "LONG" if "bid" in col else "SHORT"
            rules.append((f"{col} > {thresh}", df[col] > thresh, direction))

    # Pressure thresholds
    if "pressure_k" in df.columns:
        for thresh in [5, 10, 20]:
            rules.append((f"pressure_k > {thresh}", df["pressure_k"] > thresh, "LONG"))
            rules.append(
                (f"pressure_k < -{thresh}", df["pressure_k"] < -thresh, "SHORT")
            )

    # Combination rules (2 conditions)
    combo_rules = [
        # OBI + Depth
        (
            "obi_1 > 0.2 AND depth_ask_k > 25",
            (df["obi_1"] > 0.2) & (df.get("depth_ask_k", 0) > 25),
            "LONG",
        ),
        (
            "obi_1 < -0.2 AND depth_bid_k > 25",
            (df["obi_1"] < -0.2) & (df.get("depth_bid_k", 0) > 25),
            "SHORT",
        ),
        # Delta OBI + Depth
        (
            "d_obi_1_30s > 0.2 AND depth_ask_k > 25",
            (df.get("d_obi_1_30s", 0) > 0.2) & (df.get("depth_ask_k", 0) > 25),
            "LONG",
        ),
        (
            "d_obi_1_30s < -0.2 AND depth_bid_k > 25",
            (df.get("d_obi_1_30s", 0) < -0.2) & (df.get("depth_bid_k", 0) > 25),
            "SHORT",
        ),
        # OBI + Pressure
        (
            "obi_1 > 0.3 AND pressure_k > 10",
            (df["obi_1"] > 0.3) & (df.get("pressure_k", 0) > 10),
            "LONG",
        ),
        (
            "obi_1 < -0.3 AND pressure_k < -10",
            (df["obi_1"] < -0.3) & (df.get("pressure_k", 0) < -10),
            "SHORT",
        ),
    ]

    rules.extend(combo_rules)

    # Evaluate all rules
    patterns = []

    for rule_desc, mask, direction in rules:
        if not isinstance(mask, pd.Series):
            continue

        # Get returns for this pattern
        returns = df.loc[mask, return_col]

        # For SHORT, flip returns
        if direction == "SHORT":
            returns = -returns

        pattern_stats = compute_pattern_stats(returns, min_samples=min_trades)

        if pattern_stats is None:
            continue

        # Filter by thresholds
        if (
            pattern_stats["t_stat"] >= min_t_stat
            and pattern_stats["expectancy_bps"] >= min_expectancy
        ):
            patterns.append(
                {
                    "rule": rule_desc,
                    "direction": direction,
                    "horizon": return_col,
                    **pattern_stats,
                }
            )

    if not patterns:
        logger.warning(f"No patterns found meeting criteria")
        return pd.DataFrame()

    patterns_df = pd.DataFrame(patterns)
    patterns_df = patterns_df.sort_values("t_stat", ascending=False).head(max_patterns)
    patterns_df = patterns_df.reset_index(drop=True)

    logger.info(f"Found {len(patterns_df)} patterns")

    return patterns_df


def run_l2_pattern_discovery():
    """Main entry point for L2 pattern discovery."""

    logger.info("=" * 70)
    logger.info("L2 PATTERN DISCOVERY (T-STATISTIC RANKING)")
    logger.info("=" * 70)

    # Load data
    logger.info("\n[1/3] Loading L2 data...")
    df = load_l2_data()

    if df.empty:
        logger.error("No data loaded!")
        return

    # Compute forward returns
    logger.info("\n[2/3] Computing forward returns...")
    horizons = [60, 120, 300]  # 1min, 2min, 5min
    df = compute_forward_returns(df, horizons)

    # Report return statistics
    for h in horizons:
        col = f"fwd_ret_{h}s"
        valid = df[col].dropna()
        logger.info(
            f"  {col}: mean={valid.mean():.2f} bps, std={valid.std():.2f} bps, n={len(valid):,}"
        )

    # Discover patterns
    logger.info("\n[3/3] Discovering patterns...")

    all_patterns = []

    for horizon in horizons:
        return_col = f"fwd_ret_{horizon}s"

        patterns = discover_l2_patterns(
            df,
            return_col=return_col,
            min_t_stat=2.0,  # 95% confidence
            min_expectancy=0.5,  # 0.5 bps minimum
            min_trades=50,
            max_patterns=10,
        )

        if not patterns.empty:
            all_patterns.append(patterns)

    if all_patterns:
        combined = pd.concat(all_patterns, ignore_index=True)
        combined = combined.sort_values("t_stat", ascending=False).reset_index(
            drop=True
        )

        # Save results
        output_file = OUTPUT_DIR / "l2_patterns_tstat.csv"
        combined.to_csv(output_file, index=False)
        logger.info(f"\nSaved {len(combined)} patterns to {output_file}")

        # Print top patterns
        logger.info("\n" + "=" * 70)
        logger.info("TOP L2 PATTERNS BY T-STATISTIC")
        logger.info("=" * 70)

        cols = [
            "rule",
            "direction",
            "horizon",
            "t_stat",
            "expectancy_bps",
            "win_rate",
            "profit_factor",
            "n_trades",
        ]
        print(combined[cols].head(15).to_string(index=False))

        # Compare with old lift-based rules
        logger.info("\n" + "=" * 70)
        logger.info("VALIDATION OF EXISTING RULES")
        logger.info("=" * 70)

        old_rules = [
            (
                "Rule 1: d_obi_1_30s > 0.2 AND depth_ask > 25k",
                (df.get("d_obi_1_30s", 0) > 0.2) & (df.get("depth_ask_k", 0) > 25),
            ),
            (
                "Rule 2: depth_bid > 20k AND d_obi_1_15s > 0.1",
                (df.get("depth_bid_k", 0) > 20) & (df.get("d_obi_1_15s", 0) > 0.1),
            ),
            (
                "Rule 3: obi_1 > 0.1 AND depth_ask > 30k",
                (df["obi_1"] > 0.1) & (df.get("depth_ask_k", 0) > 30),
            ),
        ]

        for rule_name, mask in old_rules:
            if not isinstance(mask, pd.Series):
                continue
            returns = df.loc[mask, "fwd_ret_300s"]
            stats = compute_pattern_stats(returns, min_samples=10)
            if stats:
                logger.info(f"\n{rule_name}")
                logger.info(
                    f"  t-stat: {stats['t_stat']:.2f}, expectancy: {stats['expectancy_bps']:.2f} bps"
                )
                logger.info(
                    f"  win_rate: {stats['win_rate']:.1%}, profit_factor: {stats['profit_factor']:.2f}"
                )
                logger.info(f"  n_trades: {stats['n_trades']}")
            else:
                logger.info(f"\n{rule_name}: Insufficient data")
    else:
        logger.warning("No patterns found!")

    return combined if all_patterns else pd.DataFrame()


if __name__ == "__main__":
    run_l2_pattern_discovery()
