def test_vwap_momentum_policy_initialization() -> None:
    """Test that VwapMomentumPolicy initializes correctly."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(
        vwap_window=20,
        min_rvol=1.2,
        max_position_bars=30,
        position_size_pct=0.15,
        max_positions=3,
        min_breakout_strength=0.8,
    )

    assert policy.name == "VwapMomentum"
    assert policy.vwap_window == 20  # noqa: PLR2004
    assert policy.min_rvol == 1.2  # noqa: PLR2004
    assert policy.max_position_bars == 30  # noqa: PLR2004
    assert policy.position_size_pct == 0.15  # noqa: PLR2004
    assert policy.max_positions == 3  # noqa: PLR2004
    assert policy.min_breakout_strength == 0.8  # noqa: PLR2004


def test_process_bar_feature_validation() -> None:
    """Test that process_bar handles missing features correctly."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(vwap_window=30)

    # Bar without required features should be ignored
    bar_missing_features = {
        "ts": 1640995200000000000,  # 2022-01-01 09:00:00 UTC
        "symbol": "AAPL",
        "close": 150.0,
        "high": 152.0,
        "low": 148.0,
        "volume": 1000000,
    }

    # Should not raise exception, just return without action
    policy.process_bar(bar_missing_features)
    assert len(policy.position_entry_times) == 0

    # Bar with required features should proceed to check signals
    # but will fail when trying to call get_position since no engine is attached
    bar_with_features = {
        "ts": 1640995200000000000,
        "symbol": "AAPL",
        "close": 150.0,
        "high": 152.0,
        "low": 148.0,
        "volume": 1000000,
        "f__ta__vwap_30": 149.0,
        "f__vol__rel_volume_30": 1.2,
    }

    # This should fail when trying to get position since no engine is attached
    try:
        policy.process_bar(bar_with_features)
        raise AssertionError("Should have raised ValueError for missing engine")
    except ValueError as e:
        assert "Policy must be attached to an engine" in str(e)
