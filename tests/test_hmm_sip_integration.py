from qx_screener.daily_hmm_sip import DailyHMMSIPSelector
from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector


def test_hmm_sip_mode_routing() -> None:
    config_legacy = HMMSIPConfig(mode="legacy")
    config_daily = HMMSIPConfig(mode="daily")

    selector_legacy = HMMSIPUniverseSelector(config_legacy)
    selector_daily = HMMSIPUniverseSelector(config_daily)

    # Legacy mode should use original implementation
    assert hasattr(selector_legacy, "select")
    assert selector_legacy._daily_selector is None
    assert selector_legacy.cfg.mode == "legacy"

    # Daily mode should have daily selector
    assert hasattr(selector_daily, "_daily_selector")
    assert isinstance(selector_daily._daily_selector, DailyHMMSIPSelector)
    assert selector_daily.cfg.mode == "daily"
