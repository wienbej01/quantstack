"""
Validation backtest for AAA patterns.
Tests patterns on holdout period and checks degradation.
"""

from typing import Dict, List

import pandas as pd


def backtest_pattern_on_period(
    pattern: dict,
    df: pd.DataFrame,
    return_col: str,
) -> dict:
    """
    Backtest a single pattern on a data period.

    Args:
        pattern: Pattern dict with 'rule' and 'direction'
        df: DataFrame with features and returns
        return_col: Forward return column name

    Returns:
        Dict with validation metrics
    """
    # Parse rule and evaluate
    rule = pattern["rule"]

    # Simple rule evaluation (handles AND conditions)
    mask = pd.Series(True, index=df.index)

    for condition in rule.split(" AND "):
        condition = condition.strip()

        if " == " in condition:
            col, val = condition.split(" == ")
            col = col.strip()
            val = val.strip()

            # Handle boolean values
            if val == "True":
                val = True
            elif val == "False":
                val = False
            else:
                try:
                    val = float(val)
                except:
                    pass

            if col in df.columns:
                mask = mask & (df[col] == val)

    # Get returns for pattern matches
    returns = df.loc[mask, return_col].dropna()

    # Flip sign for SHORT patterns
    if pattern["direction"] == "SHORT":
        returns = -returns

    if len(returns) < 10:
        return None

    # Calculate metrics
    mean_ret = returns.mean()
    std_ret = returns.std()
    wins = returns > 0
    win_rate = wins.mean()

    avg_win = returns[wins].mean() if wins.any() else 0.0
    avg_loss = abs(returns[~wins].mean()) if (~wins).any() else 0.0

    gross_profit = returns[wins].sum() if wins.any() else 0.0
    gross_loss = abs(returns[~wins].sum()) if (~wins).any() else 0.001
    profit_factor = gross_profit / gross_loss

    sharpe = mean_ret / std_ret if std_ret > 0 else 0.0

    return {
        "n_trades": len(returns),
        "expectancy": mean_ret,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
    }


def validate_patterns(
    patterns: List[dict],
    scan_df: pd.DataFrame,
    val_df: pd.DataFrame,
    validation_gate,
) -> List[dict]:
    """
    Validate patterns on holdout period.

    Args:
        patterns: List of pattern dicts
        scan_df: Scan period data
        val_df: Validation period data
        validation_gate: ValidationGate instance

    Returns:
        List of patterns that passed validation
    """
    validated = []

    for pattern in patterns:
        return_col = pattern["horizon"]

        # Get scan metrics (already computed)
        scan_metrics = {
            "expectancy": pattern["expectancy"],
            "win_rate": pattern["win_rate"],
            "sharpe": pattern["sharpe"],
            "n_trades": pattern["n_samples"],
        }

        # Backtest on validation period
        val_metrics = backtest_pattern_on_period(pattern, val_df, return_col)

        if val_metrics is None:
            print(f"  ❌ {pattern['rule'][:50]}... - Insufficient validation trades")
            continue

        # Check validation gate
        passes, reason = validation_gate.passes_validation(scan_metrics, val_metrics)

        if passes:
            # Add validation metrics to pattern
            pattern["val_expectancy"] = val_metrics["expectancy"]
            pattern["val_win_rate"] = val_metrics["win_rate"]
            pattern["val_sharpe"] = val_metrics["sharpe"]
            pattern["val_trades"] = val_metrics["n_trades"]
            pattern["validation_passed"] = True

            validated.append(pattern)
            print(f"  ✅ {pattern['rule'][:50]}... - PASSED validation")
            print(
                f"     Scan: WR={scan_metrics['win_rate']:.1%}, Exp={scan_metrics['expectancy']:.3%}"
            )
            print(
                f"     Val:  WR={val_metrics['win_rate']:.1%}, Exp={val_metrics['expectancy']:.3%}"
            )
        else:
            print(f"  ❌ {pattern['rule'][:50]}... - {reason}")

    return validated
