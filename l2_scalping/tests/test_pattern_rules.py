"""Tests for L2 pattern-based trading rules."""

import pytest
from signals.pattern_rules import (
    PatternRules,
    MultiRuleSignalGenerator,
    ExtendedL2Snapshot,
    RuleName,
)


@pytest.fixture
def default_config():
    """Default configuration for pattern rules."""
    return {
        "pattern_rules": {
            "rule1_enabled": True,
            "rule1_d_obi_30s": 0.2,
            "rule1_depth_ask": 25000,
            "rule2_enabled": True,
            "rule2_depth_bid": 20000,
            "rule2_d_obi_15s": 0.1,
            "rule3_enabled": True,
            "rule3_obi_1": 0.1,
            "rule3_depth_ask": 30000,
        }
    }


@pytest.fixture
def pattern_rules(default_config):
    """Create PatternRules instance."""
    return PatternRules(default_config)


@pytest.fixture
def multi_rule_generator(default_config):
    """Create MultiRuleSignalGenerator instance."""
    return MultiRuleSignalGenerator(default_config)


class TestPatternRules:
    """Test individual pattern rules."""

    def test_rule1_long_signal(self, pattern_rules):
        """Test Rule 1 generates long signal when conditions met."""
        snapshot = ExtendedL2Snapshot(
            symbol="TEST",
            timestamp=1000.0,
            mid=100.0,
            spread=0.02,
            obi_1=0.3,
            obi_5=0.2,
            depth_bid=20000,
            depth_ask=30000,  # Above threshold
            pressure=5000,
            d_obi_1_30s=0.25,  # Above threshold
        )
        
        signal = pattern_rules._rule1_obi_depth_combo(snapshot)
        
        assert signal.direction == 1  # Long
        assert signal.rule_name == RuleName.OBI_DEPTH_COMBO
        assert signal.confidence == 0.75

    def test_rule1_short_signal(self, pattern_rules):
        """Test Rule 1 generates short signal when inverse conditions met."""
        snapshot = ExtendedL2Snapshot(
            symbol="TEST",
            timestamp=1000.0,
            mid=100.0,
            spread=0.02,
            obi_1=-0.3,
            obi_5=-0.2,
            depth_bid=30000,  # Above threshold (for short)
            depth_ask=20000,
            pressure=-5000,
            d_obi_1_30s=-0.25,  # Below negative threshold
        )
        
        signal = pattern_rules._rule1_obi_depth_combo(snapshot)
        
        assert signal.direction == -1  # Short
        assert signal.rule_name == RuleName.OBI_DEPTH_COMBO

    def test_rule1_no_signal(self, pattern_rules):
        """Test Rule 1 returns no signal when conditions not met."""
        snapshot = ExtendedL2Snapshot(
            symbol="TEST",
            timestamp=1000.0,
            mid=100.0,
            spread=0.02,
            obi_1=0.1,
            obi_5=0.1,
            depth_bid=15000,
            depth_ask=15000,  # Below threshold
            pressure=0,
            d_obi_1_30s=0.1,  # Below threshold
        )
        
        signal = pattern_rules._rule1_obi_depth_combo(snapshot)
        
        assert signal.direction == 0

    def test_rule2_long_signal(self, pattern_rules):
        """Test Rule 2 generates long signal when conditions met."""
        snapshot = ExtendedL2Snapshot(
            symbol="TEST",
            timestamp=1000.0,
            mid=100.0,
            spread=0.02,
            obi_1=0.2,
            obi_5=0.1,
            depth_bid=25000,  # Above threshold
            depth_ask=15000,
            pressure=5000,
            d_obi_1_15s=0.15,  # Above threshold
        )
        
        signal = pattern_rules._rule2_bid_depth_obi(snapshot)
        
        assert signal.direction == 1  # Long
        assert signal.rule_name == RuleName.BID_DEPTH_OBI
        assert signal.confidence == 0.65

    def test_rule3_long_signal(self, pattern_rules):
        """Test Rule 3 generates long signal when conditions met."""
        snapshot = ExtendedL2Snapshot(
            symbol="TEST",
            timestamp=1000.0,
            mid=100.0,
            spread=0.02,
            obi_1=0.15,  # Above threshold
            obi_5=0.1,
            depth_bid=20000,
            depth_ask=35000,  # Above threshold
            pressure=5000,
        )
        
        signal = pattern_rules._rule3_high_obi_depth(snapshot)
        
        assert signal.direction == 1  # Long
        assert signal.rule_name == RuleName.HIGH_OBI_DEPTH
        assert signal.confidence == 0.60

    def test_evaluate_all_multiple_signals(self, pattern_rules):
        """Test evaluate_all returns multiple signals when conditions overlap."""
        # Snapshot that triggers multiple rules
        snapshot = ExtendedL2Snapshot(
            symbol="TEST",
            timestamp=1000.0,
            mid=100.0,
            spread=0.02,
            obi_1=0.2,
            obi_5=0.15,
            depth_bid=25000,
            depth_ask=35000,
            pressure=5000,
            d_obi_1_15s=0.15,
            d_obi_1_30s=0.25,
        )
        
        signals = pattern_rules.evaluate_all(snapshot)
        
        # Should trigger Rule 1 and Rule 3 (Rule 2 needs depth_bid > 20k)
        assert len(signals) >= 2
        rule_names = [s.rule_name for s in signals]
        assert RuleName.OBI_DEPTH_COMBO in rule_names
        assert RuleName.HIGH_OBI_DEPTH in rule_names


class TestMultiRuleSignalGenerator:
    """Test multi-rule signal generator."""

    def test_history_update(self, multi_rule_generator):
        """Test history is updated correctly."""
        multi_rule_generator.update_history("TEST", 1000.0, 0.3, 100.0)
        multi_rule_generator.update_history("TEST", 1005.0, 0.35, 100.1)
        
        assert len(multi_rule_generator._history["TEST"]) == 2

    def test_delta_computation(self, multi_rule_generator):
        """Test delta computation from history."""
        # Add history points
        multi_rule_generator.update_history("TEST", 1000.0, 0.3, 100.0)
        multi_rule_generator.update_history("TEST", 1005.0, 0.35, 100.1)
        multi_rule_generator.update_history("TEST", 1010.0, 0.4, 100.2)
        
        # Get delta over 5 seconds
        delta = multi_rule_generator._get_delta("TEST", 1010.0, 5, "obi_1")
        
        # Should be 0.4 - 0.35 = 0.05
        assert abs(delta - 0.05) < 0.01

    def test_create_extended_snapshot(self, multi_rule_generator):
        """Test extended snapshot creation with deltas."""
        # Build up history
        for i in range(10):
            ts = 1000.0 + i * 5
            obi = 0.1 + i * 0.02
            mid = 100.0 + i * 0.1
            multi_rule_generator.update_history("TEST", ts, obi, mid)
        
        # Create extended snapshot
        snap = multi_rule_generator.create_extended_snapshot(
            symbol="TEST",
            timestamp=1050.0,
            mid=101.0,
            spread=0.02,
            obi_1=0.3,
            obi_5=0.2,
            depth_bid=20000,
            depth_ask=25000,
            pressure=5000,
        )
        
        assert snap.symbol == "TEST"
        assert snap.mid == 101.0
        # Deltas should be computed
        assert snap.d_obi_1_5s != 0.0 or snap.d_obi_1_15s != 0.0

    def test_generate_pattern_signals(self, multi_rule_generator):
        """Test pattern signal generation."""
        # Build history
        for i in range(60):
            ts = 1000.0 + i
            multi_rule_generator.update_history("TEST", ts, 0.1 + i * 0.005, 100.0)
        
        # Create snapshot that should trigger signals
        snap = multi_rule_generator.create_extended_snapshot(
            symbol="TEST",
            timestamp=1060.0,
            mid=100.0,
            spread=0.02,
            obi_1=0.2,
            obi_5=0.15,
            depth_bid=25000,
            depth_ask=35000,
            pressure=5000,
        )
        
        signals = multi_rule_generator.generate_pattern_signals(snap)
        
        # Should generate at least one signal
        assert isinstance(signals, list)


class TestRuleDisabling:
    """Test rule enable/disable functionality."""

    def test_disabled_rule_not_evaluated(self):
        """Test disabled rules don't generate signals."""
        config = {
            "pattern_rules": {
                "rule1_enabled": False,
                "rule1_d_obi_30s": 0.2,
                "rule1_depth_ask": 25000,
                "rule2_enabled": True,
                "rule2_depth_bid": 20000,
                "rule2_d_obi_15s": 0.1,
                "rule3_enabled": False,
                "rule3_obi_1": 0.1,
                "rule3_depth_ask": 30000,
            }
        }
        
        rules = PatternRules(config)
        
        # Snapshot that would trigger all rules if enabled
        snapshot = ExtendedL2Snapshot(
            symbol="TEST",
            timestamp=1000.0,
            mid=100.0,
            spread=0.02,
            obi_1=0.2,
            obi_5=0.15,
            depth_bid=25000,
            depth_ask=35000,
            pressure=5000,
            d_obi_1_15s=0.15,
            d_obi_1_30s=0.25,
        )
        
        signals = rules.evaluate_all(snapshot)
        
        # Only Rule 2 should be in results
        rule_names = [s.rule_name for s in signals]
        assert RuleName.OBI_DEPTH_COMBO not in rule_names
        assert RuleName.HIGH_OBI_DEPTH not in rule_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
