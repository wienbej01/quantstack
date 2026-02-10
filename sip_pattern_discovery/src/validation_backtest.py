"""
Validation backtest for AAA patterns.
Tests patterns on holdout period and checks degradation.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _extract_date_from_ts(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64tz_dtype(series):
        return series.dt.tz_convert("UTC").dt.tz_localize(None).dt.date
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.date
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_datetime(series, unit="ns", utc=True, errors="coerce").dt.date
    return pd.to_datetime(series, utc=True, errors="coerce").dt.date


def _coerce_rule_value(value: Any) -> Any:
    if isinstance(value, str):
        if value == "True":
            return True
        if value == "False":
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _extract_rule_conditions(pattern: dict[str, Any]) -> tuple[list[tuple[str, Any]], str | None]:
    rule_type = pattern.get("rule_type")
    if rule_type == "single":
        col = pattern.get("rule_col")
        val = _coerce_rule_value(pattern.get("rule_val"))
        if not isinstance(col, str):
            return [], "Missing rule_col for rule_type=single"
        return [(col, val)], None

    if rule_type == "double":
        col1 = pattern.get("rule_col1")
        val1 = _coerce_rule_value(pattern.get("rule_val1"))
        col2 = pattern.get("rule_col2")
        val2 = _coerce_rule_value(pattern.get("rule_val2"))
        if not isinstance(col1, str) or not isinstance(col2, str):
            return [], "Missing rule_col1/rule_col2 for rule_type=double"
        return [(col1, val1), (col2, val2)], None

    rule = pattern.get("rule")
    if not isinstance(rule, str) or not rule:
        return [], "Missing rule string"

    conditions: list[tuple[str, Any]] = []
    for condition in rule.split(" AND "):
        condition = condition.strip()
        if " == " not in condition:
            return [], f"Unsupported condition: {condition!r}"
        col, val = condition.split(" == ")
        conditions.append((col.strip(), _coerce_rule_value(val.strip())))

    return conditions, None


def backtest_pattern_on_period(
    pattern: dict[str, Any],
    df: pd.DataFrame,
    return_col: str,
    *,
    dedupe_by_symbol_day: bool = False,
    dedupe_policy: str = "first",
) -> tuple[dict[str, Any] | None, str]:
    """
    Backtest a single pattern on a data period.

    Args:
        pattern: Pattern dict with 'rule' and 'direction'
        df: DataFrame with features and returns
        return_col: Forward return column name
        dedupe_by_symbol_day: If True, keep one signal per symbol/day
        dedupe_policy: Which signal to keep when deduping (first/last)

    Returns:
        (metrics, reason). If metrics is None, reason explains why.
    """
    conditions, err = _extract_rule_conditions(pattern)
    if err is not None:
        return None, err

    mask = pd.Series(True, index=df.index)
    for col, val in conditions:
        if col not in df.columns:
            return None, f"Missing required column {col!r} for rule evaluation"
        mask = mask & (df[col] == val)

    # Get returns for pattern matches
    if dedupe_by_symbol_day:
        if "symbol" not in df.columns or "ts" not in df.columns:
            return None, "Missing symbol/ts for dedupe_by_symbol_day"
        matches = df.loc[mask, ["symbol", "ts", return_col]].dropna(subset=[return_col])
        if matches.empty:
            return None, "No matching rows in validation period"
        matches = matches.copy()
        matches["__date"] = _extract_date_from_ts(matches["ts"])
        matches = matches.sort_values("ts")
        if dedupe_policy == "first":
            matches = matches.drop_duplicates(["symbol", "__date"], keep="first")
        elif dedupe_policy == "last":
            matches = matches.drop_duplicates(["symbol", "__date"], keep="last")
        else:
            return None, f"Unsupported dedupe_policy={dedupe_policy!r}"
        returns = matches[return_col]
    else:
        returns = df.loc[mask, return_col].dropna()

    # Flip sign for SHORT patterns
    if pattern["direction"] == "SHORT":
        returns = -returns

    if returns.empty:
        return None, "No matching rows in validation period"

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
    if std_ret > 0:
        sharpe = mean_ret / std_ret * math.sqrt(252)

    return (
        {
            "n_trades": len(returns),
            "expectancy": mean_ret,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "sharpe": sharpe,
        },
        "PASS",
    )


def validate_patterns_with_diagnostics(
    patterns: list[dict[str, Any]],
    scan_df: pd.DataFrame,
    val_df: pd.DataFrame,
    validation_gate,
    *,
    dedupe_by_symbol_day: bool = False,
    dedupe_policy: str = "first",
    recompute_scan_metrics: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Validate patterns on holdout period.

    Args:
        patterns: List of pattern dicts
        scan_df: Scan period data
        val_df: Validation period data
        validation_gate: ValidationGate instance
        dedupe_by_symbol_day: If True, dedupe signals per symbol/day
        dedupe_policy: Which signal to keep when deduping (first/last)
        recompute_scan_metrics: If True, recompute scan metrics using the same rules

    Returns:
        (validated_patterns, diagnostics_records)
    """
    validated = []
    diagnostics: list[dict[str, Any]] = []
    cost_bps = float(getattr(validation_gate, "cost_bps", 0.0))

    for pattern in patterns:
        return_col = pattern["horizon"]

        # Get scan metrics (already computed)
        scan_metrics = {
            "expectancy": pattern["expectancy"],
            "win_rate": pattern["win_rate"],
            "sharpe": pattern["sharpe"],
            "n_trades": pattern["n_samples"],
        }
        if recompute_scan_metrics:
            scan_metrics, scan_reason = backtest_pattern_on_period(
                pattern,
                scan_df,
                return_col,
                dedupe_by_symbol_day=dedupe_by_symbol_day,
                dedupe_policy=dedupe_policy,
            )
            if scan_metrics is None:
                diagnostics.append(
                    {
                        "rule": pattern.get("rule", ""),
                        "direction": pattern.get("direction"),
                        "horizon": return_col,
                        "validation_passed": False,
                        "validation_reason": f"Scan metrics failed: {scan_reason}",
                    }
                )
                print(f"  ❌ {pattern['rule'][:50]}... - {scan_reason}")
                continue

        # Backtest on validation period
        val_metrics, reason = backtest_pattern_on_period(
            pattern,
            val_df,
            return_col,
            dedupe_by_symbol_day=dedupe_by_symbol_day,
            dedupe_policy=dedupe_policy,
        )
        diag: dict[str, Any] = {
            "rule": pattern.get("rule", ""),
            "direction": pattern.get("direction"),
            "horizon": return_col,
            "validation_passed": False,
            "validation_reason": reason,
        }

        if val_metrics is None:
            diagnostics.append(diag)
            print(f"  ❌ {pattern['rule'][:50]}... - {reason}")
            continue

        # Check validation gate
        passes, reason = validation_gate.passes_validation(scan_metrics, val_metrics)
        val_expectancy_net = val_metrics["expectancy"] - (cost_bps / 100)
        diag.update(
            {
                "val_expectancy": val_metrics["expectancy"],
                "val_expectancy_net": val_expectancy_net,
                "val_win_rate": val_metrics["win_rate"],
                "val_sharpe": val_metrics["sharpe"],
                "val_trades": val_metrics["n_trades"],
                "validation_passed": passes,
                "validation_reason": reason,
            }
        )
        diagnostics.append(diag)

        if passes:
            # Add validation metrics to pattern
            pattern["val_expectancy"] = val_metrics["expectancy"]
            pattern["val_expectancy_net"] = val_expectancy_net
            pattern["val_win_rate"] = val_metrics["win_rate"]
            pattern["val_sharpe"] = val_metrics["sharpe"]
            pattern["val_trades"] = val_metrics["n_trades"]
            pattern["validation_passed"] = True
            pattern["validation_reason"] = "PASS"

            validated.append(pattern)
            print(f"  ✅ {pattern['rule'][:50]}... - PASSED validation")
            print(
                f"     Scan: WR={scan_metrics['win_rate']:.1%}, "
                f"Exp={scan_metrics['expectancy']:.3%}"
            )
            print(
                f"     Val:  WR={val_metrics['win_rate']:.1%}, Exp={val_metrics['expectancy']:.3%}"
            )
        else:
            print(f"  ❌ {pattern['rule'][:50]}... - {reason}")

    return validated, diagnostics


def validate_patterns(
    patterns: list[dict[str, Any]],
    scan_df: pd.DataFrame,
    val_df: pd.DataFrame,
    validation_gate,
) -> list[dict[str, Any]]:
    validated, _ = validate_patterns_with_diagnostics(patterns, scan_df, val_df, validation_gate)
    return validated
