"""Pattern discovery engine - find statistically significant trading rules."""

from functools import partial
from itertools import combinations
from multiprocessing import Pool

import numpy as np
import pandas as pd
from scipy import stats


def discretize_features(
    df: pd.DataFrame, feature_cols: list[str], n_bins: int = 5
) -> pd.DataFrame:
    """Discretize continuous features into bins (MEMORY-OPTIMIZED: in-place).

    Modifies df in-place instead of creating a copy to save memory.
    """
    for col in feature_cols:
        if col not in df.columns:
            continue

        if df[col].nunique() <= 2:
            df[f"{col}_bin"] = df[col].values  # Use values to avoid copy
            continue

        try:
            df[f"{col}_bin"] = pd.qcut(
                df[col], q=n_bins, labels=False, duplicates="drop"
            )
        except Exception:
            df[f"{col}_bin"] = pd.cut(df[col], bins=n_bins, labels=False)

    return df  # Return same object, modified in-place


def generate_candidate_rules(
    df: pd.DataFrame,
    feature_cols: list[str],
    max_conditions: int = 2,
) -> list[dict]:
    """Generate candidate rule DESCRIPTORS from feature combinations (MEMORY-OPTIMIZED).

    Returns dict descriptors instead of (desc, mask) tuples to avoid storing
    millions of boolean Series in memory. Masks are created on-the-fly during
    evaluation instead.

    Only generates POSITIVE conditions with economic rationale:
    - Binary features: Only test "== True" (not "== False")
    - Binned features: Only test high bins (3, 4) for momentum/strength
    - Avoids trivial "NOT X" patterns that aren't actionable
    """
    rules = []

    # Single condition rules
    for col in feature_cols:
        if col not in df.columns:
            continue

        unique_vals = df[col].dropna().unique()

        # For binary features (True/False), only test True
        if len(unique_vals) == 2 and True in unique_vals:
            rules.append({
                "type": "single",
                "col": col,
                "val": True,
                "desc": f"{col} == True"
            })

        # For binned features (0-4), only test high bins (momentum/strength)
        elif len(unique_vals) <= 5:
            for val in unique_vals:
                # Only high bins (3, 4) or extreme low (0) for mean reversion
                if val in [0, 3, 4]:
                    rules.append({
                        "type": "single",
                        "col": col,
                        "val": val,
                        "desc": f"{col} == {val}"
                    })

    # Two condition rules
    if max_conditions >= 2:
        for col1, col2 in combinations(feature_cols, 2):
            if col1 not in df.columns or col2 not in df.columns:
                continue

            vals1 = df[col1].dropna().unique()
            vals2 = df[col2].dropna().unique()

            # Filter to actionable values
            actionable_vals1 = []
            if len(vals1) == 2 and True in vals1:
                actionable_vals1 = [True]
            elif len(vals1) <= 5:
                actionable_vals1 = [v for v in vals1 if v in [0, 3, 4]]

            actionable_vals2 = []
            if len(vals2) == 2 and True in vals2:
                actionable_vals2 = [True]
            elif len(vals2) <= 5:
                actionable_vals2 = [v for v in vals2 if v in [0, 3, 4]]

            if len(actionable_vals1) * len(actionable_vals2) > 25:
                continue

            for v1 in actionable_vals1:
                for v2 in actionable_vals2:
                    rules.append({
                        "type": "double",
                        "col1": col1,
                        "val1": v1,
                        "col2": col2,
                        "val2": v2,
                        "desc": f"{col1} == {v1} AND {col2} == {v2}"
                    })

    return rules


def compute_pattern_stats(returns: pd.Series, min_samples: int = 30) -> dict | None:
    """Compute trading statistics for a pattern's returns.

    Args:
        returns: Series of forward returns (%) for pattern matches
        min_samples: Minimum samples required

    Returns:
        Dict with t_stat, expectancy, win_rate, profit_factor, sharpe, etc.
    """
    returns = returns.dropna()
    n = len(returns)

    if n < min_samples:
        return None

    mean_ret = returns.mean()
    std_ret = returns.std()

    # t-statistic (is mean significantly different from 0?)
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

    # Profit factor (gross profit / gross loss)
    gross_profit = returns[wins].sum() if wins.any() else 0.0
    gross_loss = abs(returns[~wins].sum()) if (~wins).any() else 0.001
    profit_factor = gross_profit / gross_loss

    # Expectancy per trade
    expectancy = mean_ret

    # Sharpe (annualized assuming 390 1-min bars/day, 252 days)
    if std_ret > 0:
        sharpe = mean_ret / std_ret * np.sqrt(252)
    else:
        sharpe = 0.0

    return {
        "t_stat": t_stat,
        "p_value": p_value,
        "expectancy": expectancy,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "n_samples": n,  # Bar-level observations, not actual trades
        "mean_ret": mean_ret,
        "std_ret": std_ret,
    }


def evaluate_single_rule(
    rule_desc: dict,
    df_binned: pd.DataFrame,
    return_col: str,
    direction: str,
    min_samples: int,
) -> dict | None:
    """Evaluate a single rule for pattern discovery (MEMORY-OPTIMIZED).

    Creates mask on-the-fly from descriptor, computes stats, then discards mask
    immediately to avoid memory accumulation.
    """
    # Create mask on-the-fly from descriptor
    if rule_desc["type"] == "single":
        mask = df_binned[rule_desc["col"]] == rule_desc["val"]
    else:  # double
        mask = (
            (df_binned[rule_desc["col1"]] == rule_desc["val1"])
            & (df_binned[rule_desc["col2"]] == rule_desc["val2"])
        )

    # Get returns for this pattern
    returns = df_binned.loc[mask, return_col]

    # For SHORT, we want negative returns (flip sign for stats)
    if direction == "SHORT":
        returns = -returns

    pattern_stats = compute_pattern_stats(returns, min_samples=min_samples)

    # Explicit cleanup to free memory immediately
    del mask, returns

    if pattern_stats is None:
        return None

    return {
        "rule": rule_desc["desc"],
        "direction": direction,
        "horizon": return_col,
        **pattern_stats,
    }


def discover_patterns(
    df: pd.DataFrame,
    feature_cols: list[str],
    return_col: str,
    direction: str = "LONG",
    min_t_stat: float = 2.0,
    min_expectancy: float = 0.1,
    min_trades: int = 50,
    max_patterns: int = 10,
    max_conditions: int = 2,
    n_bins: int = 5,
    n_workers: int = 1,  # MEMORY-OPTIMIZED: default to 1 to avoid worker duplication
    use_aaa_scoring: bool = False,
    current_regime: str = None,
) -> pd.DataFrame:
    """Discover patterns ranked by t-statistic or AAA score (MEMORY-OPTIMIZED).

    MEMORY OPTIMIZATIONS:
    - Discretization is done in-place (no DataFrame copy)
    - Rule generation returns descriptors, not mask Series
    - Masks are created on-the-fly during evaluation
    - Default n_workers=1 to avoid memory duplication across workers
    - Use n_workers>1 only if you have abundant memory (>48GB)

    Args:
        df: DataFrame with features and forward returns
        feature_cols: List of feature columns
        return_col: Forward return column (e.g., fwd_ret_60m)
        direction: LONG (positive returns) or SHORT (negative returns)
        min_t_stat: Minimum t-statistic threshold
        min_expectancy: Minimum expectancy per trade (%)
        min_trades: Minimum number of trades
        max_patterns: Maximum patterns to return
        max_conditions: Maximum conditions per rule
        n_bins: Number of bins for discretization
        n_workers: Number of parallel workers (default 1 for memory safety, max 6)
        use_aaa_scoring: If True, rank by AAA score instead of t-stat
        current_regime: Current market regime for AAA scoring

    Returns:
        DataFrame with discovered patterns ranked by t-stat or AAA score
    """
    n_workers = min(n_workers, 6)  # Cap at 6 workers

    print(f"Discretizing {len(feature_cols)} features into {n_bins} bins (in-place)...")
    df_binned = discretize_features(df, feature_cols, n_bins)

    bin_cols = [
        f"{col}_bin" for col in feature_cols if f"{col}_bin" in df_binned.columns
    ]

    print(f"Generating candidate rules (max {max_conditions} conditions)...")
    candidate_rules = generate_candidate_rules(df_binned, bin_cols, max_conditions)
    print(f"Generated {len(candidate_rules)} candidate rule descriptors")

    print(
        f"Computing t-statistics for {direction} patterns using {n_workers} worker(s)..."
    )

    # Prepare evaluation function
    eval_func = partial(
        evaluate_single_rule,
        df_binned=df_binned,
        return_col=return_col,
        direction=direction,
        min_samples=min_trades,
    )

    # Sequential or parallel evaluation based on n_workers
    if n_workers == 1:
        # Sequential evaluation (memory-safe)
        results = [eval_func(rule) for rule in candidate_rules]
    else:
        # Parallel evaluation (may duplicate memory across workers)
        with Pool(n_workers) as pool:
            results = pool.map(eval_func, candidate_rules)

    # Filter out None results and apply thresholds
    patterns = []
    for result in results:
        if result is not None:
            if (
                result["t_stat"] >= min_t_stat
                and result["expectancy"] >= min_expectancy
            ):
                patterns.append(result)

    if not patterns:
        print(
            f"  No patterns found meeting criteria (t>{min_t_stat}, exp>{min_expectancy}%)"
        )
        return pd.DataFrame()

    patterns_df = pd.DataFrame(patterns)

    # Rank by AAA score or t-stat
    if use_aaa_scoring:
        from .aaa_scorer import AAAScorer
        scorer = AAAScorer()
        patterns_df['aaa_score'] = patterns_df.apply(
            lambda row: scorer.calculate_aaa_score(row.to_dict(), current_regime),
            axis=1
        )
        patterns_df = patterns_df.sort_values("aaa_score", ascending=False).head(max_patterns)
        print(f"  Ranked by AAA score (regime: {current_regime})")
    else:
        patterns_df = patterns_df.sort_values("t_stat", ascending=False).head(max_patterns)
        print(f"  Ranked by t-statistic")

    patterns_df = patterns_df.reset_index(drop=True)

    print(f"  Found {len(patterns_df)} patterns")

    return patterns_df
