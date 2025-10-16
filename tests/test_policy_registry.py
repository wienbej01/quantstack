"""Test policy registry includes VWAP momentum policies."""

import pytest

EXPECTED_POLICY_COUNT = 4

# Test constants for policy parameters
TEST_VWAP_WINDOW_BASIC = 20
TEST_RVOL_BASIC = 1.2
TEST_BREAKOUT_STRENGTH = 0.8

TEST_VWAP_WINDOW_ENHANCED = 15
TEST_ATR_WINDOW = 10
TEST_ATR_MULTIPLIER = 1.5
TEST_MIN_PROFIT_ATR = 0.8

TEST_CONFIG_VWAP_WINDOW = 25
TEST_CONFIG_RVOL = 1.5
TEST_CONFIG_BREAKOUT_STRENGTH = 0.7


def test_policy_registry_includes_momentum() -> None:
    """Test that VWAP momentum policy is in policy registry."""
    from qx_backtest.policies import get_policy_class

    policy_class = get_policy_class("VwapMomentum")
    assert policy_class is not None
    assert policy_class.__name__ == "VwapMomentumPolicy"

    enhanced_class = get_policy_class("VwapMomentumEnhanced")
    assert enhanced_class is not None
    assert enhanced_class.__name__ == "VwapMomentumPolicyEnhanced"


def test_list_policies_includes_momentum() -> None:
    """Test that list_policies includes momentum policies."""
    from qx_backtest.policies import list_policies

    policies = list_policies()
    assert "VwapMomentum" in policies
    assert "VwapMomentumEnhanced" in policies
    assert (
        len(policies) >= EXPECTED_POLICY_COUNT
    )  # At least: VwapRevert, VwapRevertEnhanced, VwapMomentum, VwapMomentumEnhanced


def test_policy_imports() -> None:
    """Test that momentum policies can be imported directly."""
    from qx_backtest.policies.vwap_momentum import (
        VwapMomentumPolicy,
        VwapMomentumPolicyEnhanced,
    )

    # Test instantiation
    basic_policy = VwapMomentumPolicy()
    assert basic_policy.name == "VwapMomentum"

    enhanced_policy = VwapMomentumPolicyEnhanced()
    assert enhanced_policy.name == "VwapMomentumEnhanced"


def test_policy_creation_through_registry() -> None:
    """Test creating policies through the registry."""
    from qx_backtest.policies import get_policy_class

    # Test basic momentum policy
    momentum_class = get_policy_class("VwapMomentum")
    momentum_policy = momentum_class(
        vwap_window=TEST_VWAP_WINDOW_BASIC,
        min_rvol=TEST_RVOL_BASIC,
        min_breakout_strength=TEST_BREAKOUT_STRENGTH
    )
    assert momentum_policy.vwap_window == TEST_VWAP_WINDOW_BASIC
    assert momentum_policy.min_rvol == TEST_RVOL_BASIC
    assert momentum_policy.min_breakout_strength == TEST_BREAKOUT_STRENGTH

    # Test enhanced momentum policy
    enhanced_class = get_policy_class("VwapMomentumEnhanced")
    enhanced_policy = enhanced_class(
        vwap_window=TEST_VWAP_WINDOW_ENHANCED,
        atr_window=TEST_ATR_WINDOW,
        atr_multiplier=TEST_ATR_MULTIPLIER,
        min_profit_atr=TEST_MIN_PROFIT_ATR
    )
    assert enhanced_policy.vwap_window == TEST_VWAP_WINDOW_ENHANCED
    assert enhanced_policy.atr_window == TEST_ATR_WINDOW
    assert enhanced_policy.atr_multiplier == TEST_ATR_MULTIPLIER
    assert enhanced_policy.min_profit_atr == TEST_MIN_PROFIT_ATR


def test_invalid_policy_name() -> None:
    """Test that invalid policy names return None."""
    from qx_backtest.policies import get_policy_class

    invalid_class = get_policy_class("NonExistentPolicy")
    assert invalid_class is None

    invalid_class = get_policy_class("")
    assert invalid_class is None

    invalid_class = get_policy_class(None)
    assert invalid_class is None


def test_policy_registry_completeness() -> None:
    """Test that all registered policies can be instantiated."""
    from qx_backtest.policies import get_policy_class, list_policies

    policies = list_policies()

    for policy_name in policies:
        policy_class = get_policy_class(policy_name)
        assert policy_class is not None, f"Policy {policy_name} not found in registry"

        # Try to instantiate with default parameters
        try:
            policy_instance = policy_class()
            assert hasattr(policy_instance, "name")
            assert hasattr(policy_instance, "process_bar")
        except Exception:
            # If instantiation fails, it should be due to missing required parameters
            # Try with minimal parameters
            try:
                policy_instance = policy_class(vwap_window=30)
                assert hasattr(policy_instance, "name")
                assert hasattr(policy_instance, "process_bar")
            except Exception as e2:
                pytest.fail(f"Failed to instantiate policy {policy_name}: {e2}")

    print(f"✅ All {len(policies)} policies in registry are functional")


def test_policy_from_config() -> None:
    """Test creating policy from configuration dictionary."""
    from qx_backtest.policies import get_policy_class

    config = {
        "type": "VwapMomentum",
        "params": {
            "vwap_window": TEST_CONFIG_VWAP_WINDOW,
            "min_rvol": TEST_CONFIG_RVOL,
            "max_position_bars": 40,
            "position_size_pct": 0.15,
            "max_positions": 3,
            "min_breakout_strength": TEST_CONFIG_BREAKOUT_STRENGTH,
        },
    }

    policy_class = get_policy_class(config["type"])
    assert policy_class is not None

    policy = policy_class(**config["params"])
    assert policy.name == "VwapMomentum"
    assert policy.vwap_window == TEST_CONFIG_VWAP_WINDOW
    assert policy.min_rvol == TEST_CONFIG_RVOL
    assert policy.min_breakout_strength == TEST_CONFIG_BREAKOUT_STRENGTH
