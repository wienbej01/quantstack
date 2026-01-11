"""Evaluate pattern rules against bar data."""

from typing import Any

from .pattern_parser import parse_rule_conditions


class RuleEvaluator:
    """Evaluates pattern rules against bar data."""

    def __init__(self, rule_string: str):
        """Initialize evaluator with rule string.

        Args:
            rule_string: Rule like "atr_14_bin == 4 AND is_power_hour_bin == True"
        """
        self.rule_string = rule_string
        self.conditions = parse_rule_conditions(rule_string)

    def evaluate(self, bar: dict[str, Any]) -> bool:
        """Evaluate rule against bar data.

        Args:
            bar: Bar data dictionary with features

        Returns:
            True if all conditions are met, False otherwise
        """
        for feature, operator, value in self.conditions:
            if feature not in bar:
                return False

            bar_value = bar[feature]

            # Handle NaN
            if bar_value is None or (
                isinstance(bar_value, float) and pd.isna(bar_value)
            ):
                return False

            # Evaluate condition
            if operator == "==":
                if bar_value != value:
                    return False
            else:
                # Add other operators if needed
                return False

        return True


import pandas as pd
