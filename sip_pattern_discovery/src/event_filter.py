"""
Event-based pattern filter.
Requires patterns to have time-constrained conditions.
"""


class EventFilter:
    """Filter to ensure patterns are event-based, not state-based."""

    DEFAULT_TRIGGER_KEYWORDS = [
        "rel_underperform_extreme",
        "rel_outperform_extreme",
        "price_up_vol_weak",
        "price_down_vol_weak",
        "price_up_vol_strong",
        "price_down_vol_strong",
        "vwap_cross_up",
        "vwap_cross_down",
        "avwap_cross_up",
        "avwap_cross_down",
        "at_session_low",
        "at_session_high",
        "new_session_high",
        "new_session_low",
        "ret_5m_turned_positive",
        "ret_5m_turned_negative",
        "ret_15m_turned_positive",
        "ret_15m_turned_negative",
        "ret_30m_turned_positive",
        "ret_30m_turned_negative",
        "ret_60m_turned_positive",
        "ret_60m_turned_negative",
        "first_hour_start",
        "power_hour_start",
        "last_30min_start",
    ]

    DEFAULT_CONTEXT_KEYWORDS = ["is_first_hour", "is_power_hour"]

    def __init__(
        self,
        event_keywords: list[str] | None = None,
        *,
        trigger_keywords: list[str] | None = None,
        context_keywords: list[str] | None = None,
        require_trigger: bool = True,
    ) -> None:
        if event_keywords is not None:
            self.event_keywords = [keyword.lower() for keyword in event_keywords]
        else:
            self.event_keywords = None

        self.trigger_keywords = [
            keyword.lower() for keyword in (trigger_keywords or self.DEFAULT_TRIGGER_KEYWORDS)
        ]
        self.context_keywords = [
            keyword.lower() for keyword in (context_keywords or self.DEFAULT_CONTEXT_KEYWORDS)
        ]
        self.require_trigger = require_trigger

    def is_event_based(self, rule: str) -> bool:
        """
        Check if rule contains time-constrained event conditions.

        Args:
            rule: Pattern rule string

        Returns:
            True if event-based, False if state-based
        """
        rule_lower = rule.lower()
        if self.event_keywords is not None:
            return any(keyword in rule_lower for keyword in self.event_keywords)

        has_trigger = any(keyword in rule_lower for keyword in self.trigger_keywords)
        if self.require_trigger:
            return has_trigger

        has_context = any(keyword in rule_lower for keyword in self.context_keywords)
        return has_trigger or has_context
    
    def filter_events(self, patterns: list) -> list:
        """Filter to only event-based patterns."""
        return [p for p in patterns if self.is_event_based(p['rule'])]
