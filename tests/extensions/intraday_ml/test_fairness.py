"""Tests for fairness validation functionality."""

import pytest

from extensions.intraday_ml.cli.fairness import ChecksumValidator, FairnessConfig, FairnessResult


@pytest.fixture
def fairness_config():
    """Create test fairness configuration."""
    return FairnessConfig(
        allow_unfair=False,
        require_identical_base_checksums=True,
        require_identical_data_hashes=True,
    )


@pytest.fixture
def validator(fairness_config):
    """Create test validator."""
    return ChecksumValidator(fairness_config)


@pytest.fixture
def mock_run_results():
    """Create mock run results for testing."""
    base_checksums = {
        "bars_norm_hash": "test_bars_hash",
        "features_hash": "test_features_hash",
        "config_hash": "test_config_hash",
        "seed": "test_seed",
    }

    return [
        {
            "run_id": "run1",
            "checksums": base_checksums.copy(),
            "metrics": {
                "trading": {"total_trades": 10},
                "performance": {"total_return": 0.05},
            },
        },
        {
            "run_id": "run2",
            "checksums": base_checksums.copy(),
            "metrics": {
                "trading": {"total_trades": 12},
                "performance": {"total_return": 0.06},
            },
        },
    ]


class TestChecksumValidator:
    """Test checksum validator functionality."""

    def test_initialization(self, fairness_config):
        """Test validator initialization."""
        validator = ChecksumValidator(fairness_config)
        assert validator.config == fairness_config

    def test_fair_validation_success(self, validator, mock_run_results):
        """Test successful fairness validation."""
        result = validator.validate_fairness(mock_run_results)

        assert result.is_fair is True
        assert "All fairness checks passed" in result.reason
        assert len(result.violations) == 0

    def test_insufficient_variants(self, validator, mock_run_results):
        """Test validation with insufficient variants."""
        result = validator.validate_fairness([mock_run_results[0]])

        assert result.is_fair is False
        assert "insufficient_variants" in result.violations
        assert "at least 2 variants" in result.reason

    def test_bars_hash_mismatch(self, validator, mock_run_results):
        """Test detection of bars hash mismatch."""
        # Modify second result's bars hash
        mock_run_results[1]["checksums"]["bars_norm_hash"] = "different_hash"

        result = validator.validate_fairness(mock_run_results)

        assert result.is_fair is False
        assert any("bars_norm_hash" in v for v in result.violations)

    def test_features_hash_mismatch(self, validator, mock_run_results):
        """Test detection of features hash mismatch."""
        # Modify second result's features hash
        mock_run_results[1]["checksums"]["features_hash"] = "different_hash"

        result = validator.validate_fairness(mock_run_results)

        assert result.is_fair is False
        assert any("features_hash" in v for v in result.violations)

    def test_identical_trade_counts_warning(self, validator, mock_run_results):
        """Test warning for identical trade counts."""
        # Set identical trade counts
        mock_run_results[0]["metrics"]["trading"]["total_trades"] = 10
        mock_run_results[1]["metrics"]["trading"]["total_trades"] = 10

        result = validator.validate_fairness(mock_run_results)

        # Should still be fair but with warning
        assert result.is_fair is True
        assert "identical_trade_counts_across_variants" in result.warnings

    def test_extreme_trade_difference_warning(self, validator, mock_run_results):
        """Test warning for extreme trade count differences."""
        # Set extreme difference
        mock_run_results[0]["metrics"]["trading"]["total_trades"] = 100
        mock_run_results[1]["metrics"]["trading"]["total_trades"] = 1

        result = validator.validate_fairness(mock_run_results)

        # Should still be fair but with warning
        assert result.is_fair is True
        assert "extreme_trade_count_difference" in result.warnings

    def test_data_hash_requirement_relaxed(self, mock_run_results):
        """Test validation when data hash requirement is relaxed."""
        config = FairnessConfig(
            require_identical_data_hashes=False,
        )
        validator = ChecksumValidator(config)

        # Add different config hashes
        mock_run_results[1]["checksums"]["config_hash"] = "different_config_hash"

        result = validator.validate_fairness(mock_run_results)

        # Should still be fair since only base hashes are required
        assert result.is_fair is True


class TestFairnessConfig:
    """Test fairness configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = FairnessConfig()

        assert config.allow_unfair is False
        assert config.require_identical_base_checksums is True
        assert config.require_identical_data_hashes is True
        assert config.max_config_drift == 5

    def test_custom_config(self):
        """Test custom configuration values."""
        config = FairnessConfig(
            allow_unfair=True,
            require_identical_data_hashes=False,
            max_config_drift=10,
        )

        assert config.allow_unfair is True
        assert config.require_identical_base_checksums is True  # Default
        assert config.require_identical_data_hashes is False
        assert config.max_config_drift == 10


class TestFairnessResult:
    """Test fairness result data structure."""

    def test_fair_result_creation(self):
        """Test creation of fair result."""
        result = FairnessResult(
            is_fair=True,
            reason="All checks passed",
            violations=[],
            warnings=["test_warning"],
        )

        assert result.is_fair is True
        assert result.reason == "All checks passed"
        assert len(result.violations) == 0
        assert len(result.warnings) == 1
        assert result.warnings[0] == "test_warning"

    def test_unfair_result_creation(self):
        """Test creation of unfair result."""
        result = FairnessResult(
            is_fair=False,
            reason="Hash mismatch",
            violations=["bars_hash_mismatch"],
            warnings=[],
        )

        assert result.is_fair is False
        assert "Hash mismatch" in result.reason
        assert len(result.violations) == 1
        assert result.violations[0] == "bars_hash_mismatch"
        assert len(result.warnings) == 0