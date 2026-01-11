"""Pattern discovery engine - find high-lift trading rules."""

from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency


def discretize_features(
    df: pd.DataFrame, feature_cols: list[str], n_bins: int = 5
) -> pd.DataFrame:
    """Discretize continuous features into bins.

    Args:
        df: DataFrame with features
        feature_cols: List of feature column names
        n_bins: Number of bins per feature

    Returns:
        DataFrame with discretized features (suffix _bin)
    """
    result = df.copy()

    for col in feature_cols:
        if col not in df.columns:
            continue

        # Skip if already binary
        if df[col].nunique() <= 2:
            result[f"{col}_bin"] = df[col]
            continue

        # Quantile-based binning
        try:
            result[f"{col}_bin"] = pd.qcut(
                df[col], q=n_bins, labels=False, duplicates="drop"
            )
        except Exception:
            # Fall back to equal-width if quantile fails
            result[f"{col}_bin"] = pd.cut(df[col], bins=n_bins, labels=False)

    return result


def compute_lift(
    df: pd.DataFrame, rule_mask: pd.Series, target_col: str
) -> tuple[float, float, float, float]:
    """Compute lift, support, and statistical significance for a rule.

    Args:
        df: DataFrame with target column
        rule_mask: Boolean mask for rule matches
        target_col: Target column name

    Returns:
        Tuple of (lift, support, p_value, baseline_rate)
    """
    # Remove NaN targets
    valid_mask = ~df[target_col].isna()
    rule_mask = rule_mask & valid_mask

    n_total = valid_mask.sum()
    n_rule = rule_mask.sum()

    if n_rule == 0 or n_total == 0:
        return 0.0, 0.0, 1.0, 0.0

    # Support
    support = n_rule / n_total

    # Baseline rate
    baseline_rate = df.loc[valid_mask, target_col].mean()

    if baseline_rate == 0:
        return 0.0, support, 1.0, 0.0

    # Rule rate
    rule_rate = df.loc[rule_mask, target_col].mean()

    # Lift
    lift = rule_rate / baseline_rate

    # Chi-square test
    rule_pos = (rule_mask & (df[target_col] == 1)).sum()
    rule_neg = (rule_mask & (df[target_col] == 0)).sum()
    no_rule_pos = (valid_mask & ~rule_mask & (df[target_col] == 1)).sum()
    no_rule_neg = (valid_mask & ~rule_mask & (df[target_col] == 0)).sum()

    contingency = np.array([[rule_pos, rule_neg], [no_rule_pos, no_rule_neg]])

    try:
        _, p_value, _, _ = chi2_contingency(contingency)
    except Exception:
        p_value = 1.0

    return lift, support, p_value, baseline_rate


def generate_candidate_rules(
    df: pd.DataFrame,
    feature_cols: list[str],
    max_conditions: int = 3,
) -> list[tuple[str, pd.Series]]:
    """Generate candidate rules from feature combinations.

    Args:
        df: DataFrame with discretized features
        feature_cols: List of feature column names (with _bin suffix)
        max_conditions: Maximum conditions per rule

    Returns:
        List of (rule_description, rule_mask) tuples
    """
    rules = []

    # Single condition rules
    for col in feature_cols:
        if col not in df.columns:
            continue

        unique_vals = df[col].dropna().unique()

        for val in unique_vals:
            mask = df[col] == val
            rule_desc = f"{col} == {val}"
            rules.append((rule_desc, mask))

    # Two condition rules
    if max_conditions >= 2:
        for col1, col2 in combinations(feature_cols, 2):
            if col1 not in df.columns or col2 not in df.columns:
                continue

            vals1 = df[col1].dropna().unique()
            vals2 = df[col2].dropna().unique()

            # Limit combinations to avoid explosion
            if len(vals1) * len(vals2) > 25:
                continue

            for v1 in vals1:
                for v2 in vals2:
                    mask = (df[col1] == v1) & (df[col2] == v2)
                    rule_desc = f"{col1} == {v1} AND {col2} == {v2}"
                    rules.append((rule_desc, mask))

    return rules


def discover_patterns(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    min_lift: float = 2.0,
    min_support: float = 0.005,
    max_p_value: float = 0.01,
    max_conditions: int = 2,
    n_bins: int = 5,
) -> pd.DataFrame:
    """Discover high-lift patterns.

    Args:
        df: DataFrame with features and target
        feature_cols: List of feature columns to use
        target_col: Target column name
        min_lift: Minimum lift threshold
        min_support: Minimum support threshold
        max_p_value: Maximum p-value for significance
        max_conditions: Maximum conditions per rule
        n_bins: Number of bins for discretization

    Returns:
        DataFrame with discovered patterns
    """
    print(f"Discretizing {len(feature_cols)} features into {n_bins} bins...")
    df_binned = discretize_features(df, feature_cols, n_bins)

    bin_cols = [
        f"{col}_bin" for col in feature_cols if f"{col}_bin" in df_binned.columns
    ]

    print(f"Generating candidate rules (max {max_conditions} conditions)...")
    candidate_rules = generate_candidate_rules(df_binned, bin_cols, max_conditions)
    print(f"Generated {len(candidate_rules)} candidate rules")

    print("Computing lift and significance...")
    patterns = []

    for rule_desc, rule_mask in candidate_rules:
        lift, support, p_value, baseline = compute_lift(
            df_binned, rule_mask, target_col
        )

        # Filter by thresholds
        if lift >= min_lift and support >= min_support and p_value <= max_p_value:
            patterns.append(
                {
                    "rule": rule_desc,
                    "lift": lift,
                    "support": support,
                    "p_value": p_value,
                    "baseline_rate": baseline,
                    "n_samples": rule_mask.sum(),
                }
            )

    if not patterns:
        return pd.DataFrame()

    patterns_df = pd.DataFrame(patterns)
    patterns_df = patterns_df.sort_values("lift", ascending=False).reset_index(
        drop=True
    )

    return patterns_df
