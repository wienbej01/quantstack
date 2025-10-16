# tests/test_hmm_sip_daily_config.py
import pytest
from pydantic import ValidationError

from qx_screener.hmm_sip import HMMSIPConfig


def test_hmm_sip_daily_config_validation() -> None:
    """Test that daily HMM_SIP configuration validates correctly"""
    # Valid daily config
    config = HMMSIPConfig(
        mode="daily",
        score_floor=0.02,
        top_k=40,
        external_premarket_root="hybrid-local/signals/sip/universe/pre",
        rebalance_frequency="daily",
        broadcast_time="09:30:00",
    )
    assert config.mode == "daily"
    assert config.rebalance_frequency == "daily"
    assert config.broadcast_time == "09:30:00"


def test_hmm_sip_invalid_mode():
    """Test that invalid mode raises ValidationError"""
    with pytest.raises(ValidationError):
        HMMSIPConfig(mode="invalid")


def test_hmm_sip_legacy_config_compatibility():
    """Test that legacy config still works (default mode)"""
    config = HMMSIPConfig(
        score_floor=0.01,
        top_k=20,
        external_premarket_root="hybrid-local/signals/sip/universe/pre",
    )
    assert config.mode == "legacy"  # default


def test_hmm_sip_invalid_rebalance_frequency():
    """Test that invalid rebalance_frequency raises ValidationError"""
    with pytest.raises(ValidationError):
        HMMSIPConfig(mode="daily", rebalance_frequency="invalid")


def test_hmm_sip_all_daily_fields():
    """Test all daily mode fields work together"""
    config = HMMSIPConfig(
        mode="daily",
        score_floor=0.015,
        top_k=25,
        external_premarket_root="hybrid-local/signals/sip/universe/pre",
        rebalance_frequency="daily",
        broadcast_time="09:31:00",
        enable_gold_fallback=False,
        p_hat_threshold=0.7,
        min_minutes_in_state=5,
    )
    assert config.mode == "daily"
    assert config.score_floor == 0.015
    assert config.top_k == 25
    assert config.rebalance_frequency == "daily"
    assert config.broadcast_time == "09:31:00"
    assert config.enable_gold_fallback is False
    assert config.p_hat_threshold == 0.7
    assert config.min_minutes_in_state == 5
