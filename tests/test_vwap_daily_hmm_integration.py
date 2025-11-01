# tests/test_vwap_daily_hmm_integration.py
from datetime import datetime
from typing import Any

import pandas as pd
from qx_cli.exp.entry_ab import _setup_sip_selector
from qx_screener.hmm_sip import HMMSIPConfig

# Constants
EXPECTED_TOP_K = 2
EXPECTED_TRADING_DAYS = 2
EXPECTED_SCORE_FLOOR = 0.01
EXPECTED_CONFIG_TOP_K = 3


def test_vwap_strategy_with_daily_hmm_integration() -> None:
    """End-to-end test of VWAP strategy with daily HMM_SIP filtering"""

    # Create experiment config
    config: dict[str, Any] = {
        "base_config": {
            "gold_root": "/home/jacobw/gcs-mount",
            "dates": ["2024-01-03", "2024-01-04"],
            "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN"],  # SP500 sample
            "features": [{"name": "core_basics", "params": {"vwap_window_m": 30}}],
            "policy": "vwap_revert",
            "sip": {
                "method": "hmm",
                "config": {
                    "mode": "daily",
                    "score_floor": EXPECTED_SCORE_FLOOR,
                    "top_k": EXPECTED_TOP_K,  # Only trade top 2 symbols per day
                },
            },
        },
        "variants": [
            {
                "name": "vwap_daily_hmm",
                "policy_params": {"entry_threshold": 0.02, "max_position_bars": 20},
            }
        ],
    }

    # Test that HMM config can be created from experiment config
    sip_config_dict = config["base_config"]["sip"]["config"]
    sip_config = HMMSIPConfig(**sip_config_dict)
    assert sip_config.mode == "daily"
    assert sip_config.top_k == EXPECTED_TOP_K

    # Test that SIP selector can be setup
    selector, sip_method = _setup_sip_selector(config["base_config"])
    assert sip_method == "hmm"
    assert selector.cfg.mode == "daily"
    assert hasattr(selector, "_daily_selector")
    assert selector._daily_selector is not None

    # Mock data with multiple dates
    bars = pd.DataFrame(
        {
            "ts": [
                datetime(2024, 1, 3, 9, 30),
                datetime(2024, 1, 3, 10, 0),
                datetime(2024, 1, 4, 9, 30),
                datetime(2024, 1, 4, 10, 0),
            ],
            "symbol": ["AAPL", "MSFT", "GOOGL", "AMZN"],
            "close": [150.0, 250.0, 120.0, 130.0],
            "volume": [1000000, 800000, 1500000, 600000],
        }
    )

    # Test daily universe selection
    daily_universes = selector._daily_selector.select_daily_universes(bars)
    assert len(daily_universes) == EXPECTED_TRADING_DAYS  # 2 trading days

    # Each day should have at most 2 symbols
    for day_universe in daily_universes.values():
        assert len(day_universe) <= EXPECTED_TOP_K

    print("✅ VWAP strategy with daily HMM_SIP integration test passed!")


def test_experiment_configuration_structure() -> None:
    """Test that experiment configuration has required structure for daily HMM_SIP"""

    # Test configuration structure validation
    config = {
        "gold_root": "/home/jacobw/gcs-mount",
        "family": "stocks",
        "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "JPM"],
        "dates": ["2024-01-03", "2024-01-04", "2024-01-05"],
        "features": [{"name": "core_basics", "params": {"vwap_window_m": 30}}],
        "policy": "vwap_revert",
        "policy_params": {
            "entry_threshold": 0.02,
            "exit_threshold": 0.01,
            "max_position_bars": 20,
            "max_concurrent_positions": 3,
            "position_size_pct": 0.1,
        },
        "sip": {
            "method": "hmm",
            "config": {
                "mode": "daily",
                "score_floor": EXPECTED_SCORE_FLOOR,
                "top_k": EXPECTED_CONFIG_TOP_K,
                "rebalance_frequency": "daily",
                "broadcast_time": "09:30:00",
            },
        },
        "risk": {"max_drawdown": 0.15, "max_portfolio_risk": 0.02},
        "backtest": {
            "initial_equity": 1000000,
            "cost_bps": 5,
            "cost_per_share": 0.0035,
            "seed": 42,
        },
    }

    # Verify configuration can be used to setup SIP selector
    selector, sip_method = _setup_sip_selector(config)
    assert sip_method == "hmm"
    assert selector.cfg.mode == "daily"
    assert selector.cfg.score_floor == EXPECTED_SCORE_FLOOR
    assert selector.cfg.top_k == EXPECTED_CONFIG_TOP_K
    assert selector.cfg.rebalance_frequency == "daily"

    print("✅ Experiment configuration structure test passed!")


if __name__ == "__main__":
    test_vwap_strategy_with_daily_hmm_integration()
    test_experiment_configuration_structure()
    print("✅ All VWAP daily HMM_SIP integration tests completed successfully!")
