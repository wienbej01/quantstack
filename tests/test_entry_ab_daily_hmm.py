# tests/test_entry_ab_daily_hmm.py

from qx_screener.hmm_sip import HMMSIPConfig


def test_entry_ab_supports_daily_hmm_mode():
    """Test that daily HMM_SIP config can be created from experiment config structure"""
    config = {
        "base_config": {
            "sip": {
                "method": "hmm",
                "config": {"mode": "daily", "score_floor": 0.01, "top_k": 20},
            }
        },
        "variants": [
            {"name": "variant_a", "policy_params": {"threshold": 0.1}},
            {"name": "variant_b", "policy_params": {"threshold": 0.2}},
        ],
    }

    # Should be able to create HMM config from experiment config
    sip_config = HMMSIPConfig(**config["base_config"]["sip"]["config"])
    assert sip_config.mode == "daily"
    assert sip_config.top_k == 20


def test_setup_sip_selector_function_exists():
    """Test that _setup_sip_selector function exists and handles daily mode"""
    from qx_cli.exp.entry_ab import _setup_sip_selector

    config = {
        "sip": {
            "method": "hmm",
            "config": {"mode": "daily", "score_floor": 0.01, "top_k": 20},
        }
    }

    selector, method = _setup_sip_selector(config)
    assert method == "hmm"
    assert selector is not None
    assert selector.cfg.mode == "daily"
    assert selector.cfg.top_k == 20


def test_setup_sip_selector_legacy_compatibility():
    """Test that legacy HMM configs still work"""
    from qx_cli.exp.entry_ab import _setup_sip_selector

    config = {
        "sip": {
            "method": "hmm",
            "config": {
                "score_floor": 0.01,
                "top_k": 20,
                # No mode specified - should default to legacy
            },
        }
    }

    selector, method = _setup_sip_selector(config)
    assert method == "hmm"
    assert selector is not None
    assert selector.cfg.mode == "legacy"
    assert selector.cfg.top_k == 20
