"""
Event-based pattern filter.
Requires patterns to have time-constrained conditions.
"""


class EventFilter:
    """Filter to ensure patterns are event-based, not state-based."""
    
    EVENT_KEYWORDS = [
        'is_first_hour',
        'is_power_hour',
        'at_session_low',
        'at_session_high',
    ]
    
    def is_event_based(self, rule: str) -> bool:
        """
        Check if rule contains time-constrained event conditions.
        
        Args:
            rule: Pattern rule string
        
        Returns:
            True if event-based, False if state-based
        """
        rule_lower = rule.lower()
        return any(keyword in rule_lower for keyword in self.EVENT_KEYWORDS)
    
    def filter_events(self, patterns: list) -> list:
        """Filter to only event-based patterns."""
        return [p for p in patterns if self.is_event_based(p['rule'])]
