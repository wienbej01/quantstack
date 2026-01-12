"""Parse discovered patterns from CSV into evaluable rules."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml


@dataclass
class PatternRule:
    """Represents a single pattern rule."""

    rule_id: int
    rule_string: str
    direction: str
    horizon: str
    t_stat: float
    p_value: float
    expectancy: float
    win_rate: float
    profit_factor: float
    sharpe: float
    n_samples: int
    method_id: str = "pattern_discovery"  # Identifier for this method
    # Legacy fields for backward compatibility
    lift: float | None = None
    support: float | None = None
    baseline_rate: float | None = None

    def __repr__(self) -> str:
        return f"PatternRule(id={self.rule_id}, method={self.method_id}, t_stat={self.t_stat:.2f}, expectancy={self.expectancy:.4f}, rule='{self.rule_string}')"


def parse_patterns_csv(
    csv_path: Path,
    min_t_stat: float = 3.0,
    max_patterns: int | None = None,
    method_id: str = "pattern_discovery",
) -> list[PatternRule]:
    """Parse patterns CSV into PatternRule objects.

    Args:
        csv_path: Path to patterns CSV file
        min_t_stat: Minimum t-statistic threshold
        max_patterns: Maximum number of patterns to load (top N by t_stat)
        method_id: Identifier for this method (for tracking performance)

    Returns:
        List of PatternRule objects
    """
    df = pd.read_csv(csv_path)

    # Filter by t_stat
    df = df[df["t_stat"] >= min_t_stat]

    # Sort by t_stat descending
    df = df.sort_values("t_stat", ascending=False)

    # Limit to top N
    if max_patterns is not None:
        df = df.head(max_patterns)

    # Convert to PatternRule objects
    rules = []
    for idx, row in df.iterrows():
        rule = PatternRule(
            rule_id=idx,
            rule_string=row["rule"],
            direction=row["direction"],
            horizon=row["horizon"],
            t_stat=row["t_stat"],
            p_value=row["p_value"],
            expectancy=row["expectancy"],
            win_rate=row["win_rate"],
            profit_factor=row["profit_factor"],
            sharpe=row["sharpe"],
            n_samples=int(row["n_samples"]),
            method_id=method_id,
        )
        rules.append(rule)

    return rules


def parse_strategies_yaml(yaml_path: Path) -> list[PatternRule]:
    """Parse strategies YAML into PatternRule objects.

    Args:
        yaml_path: Path to strategies YAML file

    Returns:
        List of PatternRule objects
    """
    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    rules = []
    for strategy_id, strategy_config in config["strategies"].items():
        rule = PatternRule(
            rule_id=len(rules),
            rule_string=strategy_config["rule"],
            direction=strategy_config["direction"],
            horizon=strategy_config["horizon"],
            t_stat=strategy_config["t_stat"],
            p_value=0.0,  # Not provided in YAML
            expectancy=strategy_config["expectancy"],
            win_rate=strategy_config["win_rate"],
            profit_factor=strategy_config["profit_factor"],
            sharpe=strategy_config["sharpe"],
            n_samples=strategy_config["n_samples"],
            method_id=strategy_config["name"],
        )
        rules.append(rule)

    return rules


def parse_rule_conditions(rule_string: str) -> list[tuple]:
    """Parse rule string into list of (feature, operator, value) tuples.

    Args:
        rule_string: Rule like "atr_14_bin == 4 AND is_power_hour_bin == True"

    Returns:
        List of (feature, operator, value) tuples
    """
    conditions = []

    # Split by AND
    parts = rule_string.split(" AND ")

    for part in parts:
        part = part.strip()

        # Parse condition
        if " == " in part:
            feature, value = part.split(" == ")
            feature = feature.strip()
            value = value.strip()

            # Convert value to appropriate type
            parsed_value: bool | float | str
            if value == "True":
                parsed_value = True
            elif value == "False":
                parsed_value = False
            else:
                try:
                    parsed_value = float(value)
                except ValueError:
                    parsed_value = value

            conditions.append((feature, "==", parsed_value))

    return conditions
