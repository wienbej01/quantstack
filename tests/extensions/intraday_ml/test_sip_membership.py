"""
Unit tests for the SIP membership I/O layer and pipeline integration.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from extensions.intraday_ml.sip_membership import (
    get_phase_symbols_with_sip,
    get_sip_membership_base_path,
    load_sip_membership_for_dates,
    save_sip_membership,
)


@pytest.fixture
def sample_sip_data() -> pd.DataFrame:
    """Create a sample DataFrame of SIP membership data for testing."""
    return pd.DataFrame(
        {
            "trade_date": [
                "2023-01-02",
                "2023-01-02",
                "2023-01-03",
                "2023-01-03",
                "2023-01-04",
            ],
            "symbol": ["AAPL", "MSFT", "AAPL", "GOOG", "TSLA"],
            "is_sip": [True, False, True, True, False],
            "sip_score": [0.9, 0.1, 0.95, 0.8, 0.2],
        }
    )


@pytest.fixture
def mock_gold_root(tmp_path: Path) -> Path:
    """Create a temporary directory to act as a mock gold root."""
    return tmp_path / "gold"


def test_save_and_load_sip_membership(sample_sip_data: pd.DataFrame, mock_gold_root: Path):
    """Test saving and then loading SIP membership data."""
    save_sip_membership(sample_sip_data, mock_gold_root)

    # Verify that the partitioned directories were created
    base_path = get_sip_membership_base_path(mock_gold_root)
    assert (base_path / "trade_date=2023-01-02").exists()
    assert (base_path / "trade_date=2023-01-03").exists()

    # Test loading with different modes
    # Mode: sip_only
    sip_only_df = load_sip_membership_for_dates(
        mock_gold_root, "2023-01-02", "2023-01-03", mode="sip_only"
    )
    assert len(sip_only_df) == 3
    assert set(sip_only_df["symbol"]) == {"AAPL", "GOOG"}
    assert sip_only_df["is_sip"].all()

    # Mode: no_sip
    no_sip_df = load_sip_membership_for_dates(
        mock_gold_root, "2023-01-02", "2023-01-03", mode="no_sip"
    )
    assert len(no_sip_df) == 1
    assert set(no_sip_df["symbol"]) == {"MSFT"}
    assert not no_sip_df["is_sip"].any()

    # Mode: all
    all_df = load_sip_membership_for_dates(mock_gold_root, "2023-01-02", "2023-01-03", mode="all")
    assert len(all_df) == 4
    assert set(all_df["symbol"]) == {"AAPL", "MSFT", "GOOG"}

    # Test date range filtering
    single_day_df = load_sip_membership_for_dates(
        mock_gold_root, "2023-01-02", "2023-01-02", mode="all"
    )
    assert len(single_day_df) == 2
    assert set(single_day_df["symbol"]) == {"AAPL", "MSFT"}


def test_load_sip_membership_missing_data(mock_gold_root: Path):
    """Test that loading from an empty or non-existent path raises an error."""
    with pytest.raises(FileNotFoundError):
        load_sip_membership_for_dates(mock_gold_root, "2024-01-01", "2024-01-02", mode="all")


def test_get_phase_symbols_with_sip_disabled():
    """Test that the original symbol list is returned when SIP is disabled."""
    sip_config = {"enabled": False}
    candidate_symbols = ["AAPL", "MSFT", "GOOG"]
    splits_config = {}

    result = get_phase_symbols_with_sip(splits_config, sip_config, candidate_symbols, "train")
    assert result == candidate_symbols


def test_get_phase_symbols_with_sip_enabled(sample_sip_data: pd.DataFrame, mock_gold_root: Path):
    """Test symbol filtering when SIP is enabled."""
    save_sip_membership(sample_sip_data, mock_gold_root)

    candidate_symbols = ["AAPL", "MSFT", "GOOG", "TSLA", "AMZN"]
    splits_config = {
        "train": {"start": "2023-01-02", "end": "2023-01-03"},
        "oos": {"start": "2023-01-04", "end": "2023-01-04"},
    }
    sip_config = {
        "enabled": True,
        "mode": "sip_only",
        "membership_path": str(get_sip_membership_base_path(mock_gold_root)),
    }

    # Test train phase with sip_only
    train_symbols = get_phase_symbols_with_sip(
        splits_config, sip_config, candidate_symbols, "train"
    )
    assert set(train_symbols) == {"AAPL", "GOOG"}

    # Test OOS phase (should only contain symbols from that date)
    oos_symbols = get_phase_symbols_with_sip(splits_config, sip_config, candidate_symbols, "oos")
    # TSLA is not a SIP stock on 2023-01-04
    assert oos_symbols == []

    # Test with mode="no_sip"
    sip_config["mode"] = "no_sip"
    train_no_sip_symbols = get_phase_symbols_with_sip(
        splits_config, sip_config, candidate_symbols, "train"
    )
    assert set(train_no_sip_symbols) == {"MSFT"}

    # Test with mode="all"
    sip_config["mode"] = "all"
    train_all_symbols = get_phase_symbols_with_sip(
        splits_config, sip_config, candidate_symbols, "train"
    )
    assert set(train_all_symbols) == {"AAPL", "MSFT", "GOOG"}


def test_get_phase_symbols_with_sip_empty_result(
    sample_sip_data: pd.DataFrame, mock_gold_root: Path
):
    """Test that an empty list is returned if no SIP symbols match."""
    save_sip_membership(sample_sip_data, mock_gold_root)

    candidate_symbols = ["AMZN", "NFLX"]  # Symbols not in the sample SIP data
    splits_config = {"train": {"start": "2023-01-02", "end": "2023-01-03"}}
    sip_config = {
        "enabled": True,
        "mode": "sip_only",
        "membership_path": str(get_sip_membership_base_path(mock_gold_root)),
    }

    result = get_phase_symbols_with_sip(splits_config, sip_config, candidate_symbols, "train")
    assert result == []
