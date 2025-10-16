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
