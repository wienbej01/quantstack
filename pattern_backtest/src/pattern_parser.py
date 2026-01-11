"""Parse discovered patterns from CSV into evaluable rules."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class PatternRule:
    """Represents a single pattern rule."""

    rule_id: int
    rule_string: str
    lift: float
    support: float
    p_value: float
    baseline_rate: float
    n_samples: int
    method_id: str = "pattern_discovery"  # Identifier for this method

    def __repr__(self) -> str:
        return f"PatternRule(id={self.rule_id}, method={self.method_id}, lift={self.lift:.2f}x, rule='{self.rule_string}')"


def parse_patterns_csv(
    csv_path: Path,
    min_lift: float = 2.0,
    max_patterns: int | None = None,
    method_id: str = "pattern_discovery",
) -> list[PatternRule]:
    """Parse patterns CSV into PatternRule objects.

    Args:
        csv_path: Path to patterns CSV file
        min_lift: Minimum lift threshold
        max_patterns: Maximum number of patterns to load (top N by lift)
        method_id: Identifier for this method (for tracking performance)

    Returns:
        List of PatternRule objects
    """
    df = pd.read_csv(csv_path)

    # Filter by lift
    df = df[df["lift"] >= min_lift]

    # Sort by lift descending
    df = df.sort_values("lift", ascending=False)

    # Limit to top N
    if max_patterns is not None:
        df = df.head(max_patterns)

    # Convert to PatternRule objects
    rules = []
    for idx, row in df.iterrows():
        rule = PatternRule(
            rule_id=idx,
            rule_string=row["rule"],
            lift=row["lift"],
            support=row["support"],
            p_value=row["p_value"],
            baseline_rate=row["baseline_rate"],
            n_samples=int(row["n_samples"]),
            method_id=method_id,
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
