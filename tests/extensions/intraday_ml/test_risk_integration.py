"""Tests for ML-powered risk management."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml_risk.ml_risk_manager import (
    MLRiskManager,
    PortfolioRiskMonitor,
    PositionRiskMonitor,
    RiskLevel,
    RiskLimit,
    RiskMetrics,
    RiskModelManager,
)


@pytest.fixture
def sample_features():
    """Create sample features for risk prediction."""
    return {
        "volatility": 0.15,
        "volume_ratio": 1.2,
        "price_momentum": 0.05,
        "market_beta": 1.1,
        "liquidity_score": 0.8,
    }


@pytest.fixture
def sample_risk_limits():
    """Create sample risk limits."""
    return [
        RiskLimit(
            name="max_position_risk",
            metric_name="total_risk_score",
            threshold=0.8,
            operator="lt",
            action="reduce",
        ),
        RiskLimit(
            name="max_drawdown",
            metric_name="max_drawdown",
            threshold=10.0,
            operator="lt",
            action="close",
        ),
        RiskLimit(
            name="min_sharpe_ratio",
            metric_name="sharpe_ratio",
            threshold=-1.0,
            operator="gt",
            action="warn",
        ),
    ]


class TestRiskMetrics:
    """Test RiskMetrics dataclass."""

    def test_risk_metrics_creation(self):
        """Test RiskMetrics creation."""
        timestamp = datetime.now()
        metrics = RiskMetrics(
            timestamp=timestamp,
            position_id="position_1",
            symbol="AAPL",
            risk_level=RiskLevel.MEDIUM,
            var_95=1000.0,
            var_99=1500.0,
            max_drawdown=5.0,
            sharpe_ratio=1.2,
            sortino_ratio=1.5,
            beta=1.1,
            volatility=0.2,
            correlation_risk=0.3,
            concentration_risk=0.4,
            liquidity_risk=0.2,
            total_risk_score=0.6,
        )

        assert metrics.position_id == "position_1"
        assert metrics.symbol == "AAPL"
        assert metrics.risk_level == RiskLevel.MEDIUM
        assert metrics.var_95 == 1000.0
        assert metrics.total_risk_score == 0.6

    def test_risk_level_determination(self):
        """Test risk level determination based on total risk score."""
        timestamp = datetime.now()

        # Test different risk levels
        low_risk = RiskMetrics(
            timestamp=timestamp,
            position_id="test",
            symbol="TEST",
            risk_level=RiskLevel.LOW,
            var_95=0,
            var_99=0,
            max_drawdown=0,
            sharpe_ratio=0,
            sortino_ratio=0,
            beta=0,
            volatility=0,
            correlation_risk=0,
            concentration_risk=0,
            liquidity_risk=0,
            total_risk_score=0.2,  # Low risk
        )

        medium_risk = RiskMetrics(
            timestamp=timestamp,
            position_id="test",
            symbol="TEST",
            risk_level=RiskLevel.MEDIUM,
            var_95=0,
            var_99=0,
            max_drawdown=0,
            sharpe_ratio=0,
            sortino_ratio=0,
            beta=0,
            volatility=0,
            correlation_risk=0,
            concentration_risk=0,
            liquidity_risk=0,
            total_risk_score=0.5,  # Medium risk
        )

        high_risk = RiskMetrics(
            timestamp=timestamp,
            position_id="test",
            symbol="TEST",
            risk_level=RiskLevel.HIGH,
            var_95=0,
            var_99=0,
            max_drawdown=0,
            sharpe_ratio=0,
            sortino_ratio=0,
            beta=0,
            volatility=0,
            correlation_risk=0,
            concentration_risk=0,
            liquidity_risk=0,
            total_risk_score=0.7,  # High risk
        )

        critical_risk = RiskMetrics(
            timestamp=timestamp,
            position_id="test",
            symbol="TEST",
            risk_level=RiskLevel.CRITICAL,
            var_95=0,
            var_99=0,
            max_drawdown=0,
            sharpe_ratio=0,
            sortino_ratio=0,
            beta=0,
            volatility=0,
            correlation_risk=0,
            concentration_risk=0,
            liquidity_risk=0,
            total_risk_score=0.9,  # Critical risk
        )

        assert low_risk.risk_level == RiskLevel.LOW
        assert medium_risk.risk_level == RiskLevel.MEDIUM
        assert high_risk.risk_level == RiskLevel.HIGH
        assert critical_risk.risk_level == RiskLevel.CRITICAL


class TestRiskModelManager:
    """Test RiskModelManager functionality."""

    def setup_method(self):
        """Set up test environment."""
        with patch("extensions.intraday_ml_risk.ml_risk_manager.MLModelRegistry"):
            self.risk_model_manager = RiskModelManager()

    def test_risk_model_manager_initialization(self):
        """Test RiskModelManager initialization."""
        assert self.risk_model_manager.registry is not None
        assert self.risk_model_manager.models == {}
        assert self.risk_model_manager.model_cache_timeout == timedelta(minutes=30)

    @patch("extensions.intraday_ml_risk.ml_risk_manager.MLPredictor")
    @patch("extensions.intraday_ml_risk.ml_risk_manager.MLModelRegistry")
    def test_load_risk_model(self, mock_registry_class, mock_predictor_class):
        """Test loading a risk model."""
        # Setup mocks
        mock_registry = Mock()
        mock_registry_class.return_value = mock_registry
        mock_predictor = Mock()
        mock_predictor_class.return_value = mock_predictor

        # Load model
        result = self.risk_model_manager.load_risk_model("risk_model_1")

        assert result is True
        assert "risk_model_1" in self.risk_model_manager.models
        assert "risk_model_1" in self.risk_model_manager._last_load_time

    @patch("extensions.intraday_ml_risk.ml_risk_manager.MLPredictor")
    @patch("extensions.intraday_ml_risk.ml_risk_manager.MLModelRegistry")
    def test_predict_risk_metrics(
        self, mock_registry_class, mock_predictor_class, sample_features
    ):
        """Test risk metrics prediction."""
        # Setup mocks
        mock_registry = Mock()
        mock_registry_class.return_value = mock_registry
        mock_predictor = Mock()
        mock_predictor_class.return_value = mock_predictor

        # Setup prediction result
        mock_result = Mock()
        mock_result.prediction = np.array([0.6])
        mock_result.prediction_probability = np.array([0.8])
        mock_predictor.predict.return_value = mock_result

        # Load model
        self.risk_model_manager.load_risk_model("risk_model_1")

        # Predict risk metrics
        result = self.risk_model_manager.predict_risk_metrics(
            "risk_model_1", sample_features
        )

        assert result is not None
        assert result["risk_score"] == 0.6
        assert result["confidence"] == 0.8
        assert result["model_id"] == "risk_model_1"
        assert "timestamp" in result

    def test_predict_risk_metrics_model_not_loaded(self, sample_features):
        """Test risk prediction when model is not loaded."""
        result = self.risk_model_manager.predict_risk_metrics(
            "nonexistent_model", sample_features
        )
        assert result is None

    def test_model_cache_timeout(self):
        """Test model cache timeout functionality."""
        # Set a very short timeout for testing
        self.risk_model_manager.model_cache_timeout = timedelta(milliseconds=1)

        with patch(
            "extensions.intraday_ml_risk.ml_risk_manager.MLPredictor"
        ) as mock_predictor_class:
            mock_predictor = Mock()
            mock_predictor_class.return_value = mock_predictor

            # Load model
            self.risk_model_manager.load_risk_model("test_model")
            assert "test_model" in self.risk_model_manager.models

            # Wait for timeout
            time.sleep(0.002)

            # Try to use model - should trigger reload
            with patch.object(
                self.risk_model_manager, "load_risk_model", return_value=False
            ) as mock_load:
                result = self.risk_model_manager.predict_risk_metrics("test_model", {})
                assert result is None
                mock_load.assert_called_once_with("test_model")


class TestPositionRiskMonitor:
    """Test PositionRiskMonitor functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.risk_model_manager = Mock()
        self.position_monitor = PositionRiskMonitor(self.risk_model_manager)

    def test_position_risk_monitor_initialization(self):
        """Test PositionRiskMonitor initialization."""
        assert self.position_monitor.risk_model_manager is not None
        assert self.position_monitor.position_data == {}
        assert self.position_monitor.risk_history == {}

    def test_update_position(self):
        """Test updating a position."""
        position_id = "position_1"
        symbol = "AAPL"
        size = 100.0
        entry_price = 150.0
        current_price = 155.0

        risk_metrics = self.position_monitor.update_position(
            position_id=position_id,
            symbol=symbol,
            size=size,
            entry_price=entry_price,
            current_price=current_price,
        )

        assert risk_metrics.position_id == position_id
        assert risk_metrics.symbol == symbol
        assert risk_metrics.position_id in self.position_monitor.position_data

        # Check position data was stored
        stored_data = self.position_monitor.position_data[position_id]
        assert stored_data["symbol"] == symbol
        assert stored_data["size"] == size
        assert stored_data["entry_price"] == entry_price
        assert stored_data["current_price"] == current_price

        # Check risk history was created
        assert position_id in self.position_monitor.risk_history
        assert len(self.position_monitor.risk_history[position_id]) == 1

    def test_update_position_with_features(self, sample_features):
        """Test updating position with features."""
        position_id = "position_1"
        symbol = "AAPL"
        size = 100.0
        entry_price = 150.0
        current_price = 155.0

        risk_metrics = self.position_monitor.update_position(
            position_id=position_id,
            symbol=symbol,
            size=size,
            entry_price=entry_price,
            current_price=current_price,
            features=sample_features,
            risk_model_id="risk_model_1",
        )

        stored_data = self.position_monitor.position_data[position_id]
        assert stored_data["features"] == sample_features
        assert stored_data["risk_model_id"] == "risk_model_1"

    def test_calculate_position_risk(self):
        """Test position risk calculation."""
        position_id = "position_1"
        symbol = "AAPL"
        size = 100.0
        entry_price = 150.0
        current_price = 155.0

        # Update position (this will calculate risk)
        risk_metrics = self.position_monitor.update_position(
            position_id=position_id,
            symbol=symbol,
            size=size,
            entry_price=entry_price,
            current_price=current_price,
        )

        # Verify basic risk calculations
        assert risk_metrics.position_id == position_id
        assert risk_metrics.symbol == symbol
        assert isinstance(risk_metrics.var_95, float)
        assert isinstance(risk_metrics.var_99, float)
        assert isinstance(risk_metrics.volatility, float)
        assert isinstance(risk_metrics.total_risk_score, float)
        assert risk_metrics.risk_level in RiskLevel

        # Verify PnL calculation
        expected_pnl_pct = (current_price - entry_price) / entry_price * 100
        position_value = size * current_price
        assert risk_metrics.max_drawdown <= 0  # Should be negative or zero for profit

    def test_get_position_risk(self):
        """Test getting risk metrics for a position."""
        position_id = "position_1"

        # Initially no position
        risk = self.position_monitor.get_position_risk(position_id)
        assert risk is None

        # Add position
        self.position_monitor.update_position(
            position_id=position_id,
            symbol="AAPL",
            size=100.0,
            entry_price=150.0,
            current_price=155.0,
        )

        # Get risk metrics
        risk = self.position_monitor.get_position_risk(position_id)
        assert risk is not None
        assert risk.position_id == position_id

    def test_get_risk_history(self):
        """Test getting risk history for a position."""
        position_id = "position_1"

        # Add position multiple times
        for i in range(5):
            self.position_monitor.update_position(
                position_id=position_id,
                symbol="AAPL",
                size=100.0,
                entry_price=150.0,
                current_price=150.0 + i,  # Vary price
            )

        # Get full history
        full_history = self.position_monitor.get_risk_history(position_id)
        assert len(full_history) == 5

        # Get limited history
        limited_history = self.position_monitor.get_risk_history(position_id, limit=3)
        assert len(limited_history) == 3
        assert limited_history == full_history[-3:]

    def test_remove_position(self):
        """Test removing a position."""
        position_id = "position_1"

        # Add position
        self.position_monitor.update_position(
            position_id=position_id,
            symbol="AAPL",
            size=100.0,
            entry_price=150.0,
            current_price=155.0,
        )

        # Verify position exists
        assert position_id in self.position_monitor.position_data
        assert position_id in self.position_monitor.risk_history

        # Remove position
        self.position_monitor.remove_position(position_id)

        # Verify position was removed
        assert position_id not in self.position_monitor.position_data
        assert position_id not in self.position_monitor.risk_history

    def test_concurrent_position_updates(self):
        """Test concurrent position updates."""
        import threading
        import time

        position_id = "position_1"
        results = []

        def update_worker():
            for i in range(10):
                risk = self.position_monitor.update_position(
                    position_id=position_id,
                    symbol="AAPL",
                    size=100.0,
                    entry_price=150.0,
                    current_price=150.0 + i,
                )
                results.append(risk.total_risk_score)
                time.sleep(0.001)

        # Create multiple threads
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=update_worker)
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Verify all updates were processed
        assert len(results) == 30  # 3 threads * 10 updates
        assert position_id in self.position_monitor.position_data

        # Should have last price in position data
        final_price = self.position_monitor.position_data[position_id]["current_price"]
        assert final_price == 159.0  # Last update from last thread

        # Should have multiple risk measurements
        risk_history = self.position_monitor.get_risk_history(position_id)
        assert len(risk_history) > 10  # Multiple measurements per update


class TestPortfolioRiskMonitor:
    """Test PortfolioRiskMonitor functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.position_monitor = Mock()
        self.portfolio_monitor = PortfolioRiskMonitor(self.position_monitor)

    def test_portfolio_risk_monitor_initialization(self):
        """Test PortfolioRiskMonitor initialization."""
        assert self.portfolio_monitor.position_monitor is not None
        assert self.portfolio_monitor.portfolio_risk_history == []

    def test_calculate_portfolio_risk_empty(self):
        """Test portfolio risk calculation with no positions."""
        # Mock empty position data
        self.position_monitor.position_data = {}
        self.position_monitor.risk_history = {}

        portfolio_risk = self.portfolio_monitor.calculate_portfolio_risk()

        assert portfolio_risk.symbol == "PORTFOLIO"
        assert portfolio_risk.position_id is None
        assert portfolio_risk.risk_level == RiskLevel.LOW
        assert portfolio_risk.var_95 == 0.0
        assert portfolio_risk.total_risk_score == 0.0

    def test_calculate_portfolio_risk_with_positions(self):
        """Test portfolio risk calculation with positions."""
        # Mock position monitor with positions
        position_data = {
            "pos1": {"current_price": 155.0},
            "pos2": {"current_price": 160.0},
        }
        self.position_monitor.position_data = position_data

        # Mock position risks
        risk1 = Mock()
        risk1.var_95 = 1000.0
        risk1.var_99 = 1500.0
        risk1.volatility = 0.2
        risk1.max_drawdown = 5.0
        risk1.sharpe_ratio = 1.2
        risk1.sortino_ratio = 1.5
        risk1.beta = 1.1
        risk1.correlation_risk = 0.3
        risk1.concentration_risk = 0.4
        risk1.liquidity_risk = 0.2

        risk2 = Mock()
        risk2.var_95 = 800.0
        risk2.var_99 = 1200.0
        risk2.volatility = 0.15
        risk2.max_drawdown = 3.0
        risk2.sharpe_ratio = 1.0
        risk2.sortino_ratio = 1.3
        risk2.beta = 0.9
        risk2.correlation_risk = 0.2
        risk2.concentration_risk = 0.3
        risk2.liquidity_risk = 0.25

        self.position_monitor.get_position_risk = Mock(
            side_effect=lambda pid: {"pos1": risk1, "pos2": risk2}.get(pid)
        )

        portfolio_risk = self.portfolio_monitor.calculate_portfolio_risk()

        # Verify portfolio-level metrics
        assert portfolio_risk.symbol == "PORTFOLIO"
        assert portfolio_risk.var_95 == 1800.0  # 1000 + 800
        assert portfolio_risk.var_99 == 2700.0  # 1500 + 1200
        assert portfolio_risk.max_drawdown == 5.0  # Max of 5.0 and 3.0

        # Verify aggregated metrics
        assert 0.175 <= portfolio_risk.volatility <= 0.2  # Average of 0.2 and 0.15
        assert 1.4 <= portfolio_risk.sortino_ratio <= 1.5  # Average of 1.5 and 1.3
        assert 1.0 <= portfolio_risk.beta <= 1.1  # Average of 1.1 and 0.9

    def test_get_portfolio_risk_history(self):
        """Test getting portfolio risk history."""
        # Mock empty history initially
        history = self.portfolio_monitor.get_portfolio_risk_history()
        assert isinstance(history, list)
        assert len(history) == 0

        # Mock some history
        mock_history = [
            Mock(total_risk_score=0.3),
            Mock(total_risk_score=0.4),
            Mock(total_risk_score=0.5),
        ]
        self.portfolio_monitor.portfolio_risk_history = mock_history

        # Get history
        history = self.portfolio_monitor.get_portfolio_risk_history()
        assert len(history) == 3

        # Get limited history
        limited_history = self.portfolio_monitor.get_portfolio_risk_history(limit=2)
        assert len(limited_history) == 2
        assert limited_history == mock_history[-2:]


class TestMLRiskManager:
    """Test MLRiskManager functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.risk_limits = [
            RiskLimit(
                name="max_risk_score",
                metric_name="total_risk_score",
                threshold=0.8,
                operator="lt",
                action="warn",
            )
        ]
        with patch("extensions.intraday_ml_risk.ml_risk_manager.MLModelRegistry"):
            self.risk_manager = MLRiskManager(risk_limits=self.risk_limits)

    def test_risk_manager_initialization(self):
        """Test MLRiskManager initialization."""
        assert self.risk_manager.registry is not None
        assert self.risk_manager.risk_model_manager is not None
        assert self.risk_manager.position_monitor is not None
        assert self.risk_manager.portfolio_monitor is not None
        assert len(self.risk_manager.risk_limits) == 1

    def test_add_position(self):
        """Test adding a position to risk monitoring."""
        position_id = "position_1"
        symbol = "AAPL"
        size = 100.0
        entry_price = 150.0
        current_price = 155.0

        risk_metrics = self.risk_manager.add_position(
            position_id=position_id,
            symbol=symbol,
            size=size,
            entry_price=entry_price,
            current_price=current_price,
        )

        assert risk_metrics.position_id == position_id
        assert risk_metrics.symbol == symbol

        # Verify position was added to position monitor
        stored_risk = self.risk_manager.position_monitor.get_position_risk(position_id)
        assert stored_risk is not None
        assert stored_risk.position_id == position_id

    def test_update_position(self):
        """Test updating an existing position."""
        position_id = "position_1"

        # Add initial position
        self.risk_manager.add_position(
            position_id=position_id,
            symbol="AAPL",
            size=100.0,
            entry_price=150.0,
            current_price=155.0,
        )

        # Update position
        updated_risk = self.risk_manager.update_position(
            position_id=position_id, current_price=160.0
        )

        assert updated_risk.position_id == position_id
        assert updated_risk.symbol == "AAPL"

    def test_remove_position(self):
        """Test removing a position."""
        position_id = "position_1"

        # Add position
        self.risk_manager.add_position(
            position_id=position_id,
            symbol="AAPL",
            size=100.0,
            entry_price=150.0,
            current_price=155.0,
        )

        # Verify position exists
        assert self.risk_manager.get_position_risk(position_id) is not None

        # Remove position
        self.risk_manager.remove_position(position_id)

        # Verify position was removed
        assert self.risk_manager.get_position_risk(position_id) is None

    def test_get_portfolio_risk(self):
        """Test getting portfolio risk metrics."""
        # Mock portfolio monitor
        mock_portfolio_risk = Mock()
        mock_portfolio_risk.total_risk_score = 0.6
        mock_portfolio_risk.var_95 = 5000.0
        self.risk_manager.portfolio_monitor.calculate_portfolio_risk.return_value = (
            mock_portfolio_risk
        )

        portfolio_risk = self.risk_manager.get_portfolio_risk()
        assert portfolio_risk is mock_portfolio_risk

    def test_get_risk_summary(self):
        """Test getting comprehensive risk summary."""
        # Mock components
        mock_portfolio_risk = Mock()
        mock_portfolio_risk.to_dict.return_value = {
            "risk_level": "medium",
            "total_risk_score": 0.6,
        }

        mock_position_risk = Mock()
        mock_position_risk.risk_level = RiskLevel.MEDIUM.value

        self.risk_manager.portfolio_monitor.calculate_portfolio_risk.return_value = (
            mock_portfolio_risk
        )
        self.risk_manager.position_monitor.get_position_risk.return_value = (
            mock_position_risk
        )
        self.risk_manager.position_monitor.position_data = {"pos1": {}, "pos2": {}}

        summary = self.risk_manager.get_risk_summary()

        assert "portfolio_risk" in summary
        assert "position_count" in summary
        assert "risk_level_distribution" in summary
        assert "active_violations" in summary
        assert "total_violations_last_hour" in summary

        assert summary["position_count"] == 2
        assert summary["risk_level_distribution"]["medium"] == 1

    def test_load_risk_model(self):
        """Test loading a risk model."""
        with patch.object(
            self.risk_manager.risk_model_manager, "load_risk_model"
        ) as mock_load:
            mock_load.return_value = True

            result = self.risk_manager.load_risk_model("risk_model_1")

            assert result is True
            mock_load.assert_called_once_with("risk_model_1")

    def test_get_available_risk_models(self):
        """Test getting available risk models."""
        # Mock some loaded models
        self.risk_manager.risk_model_manager.models = {
            "risk_model_1": Mock(),
            "risk_model_2": Mock(),
        }

        models = self.risk_manager.get_available_risk_models()
        assert len(models) == 2
        assert "risk_model_1" in models
        assert "risk_model_2" in models

    def test_default_risk_limits(self):
        """Test default risk limits creation."""
        manager = MLRiskManager()  # Uses default limits
        limits = manager.risk_limits

        # Check that default limits exist
        limit_names = [limit.name for limit in limits]
        assert "max_position_risk" in limit_names
        assert "max_portfolio_var" in limit_names
        assert "max_drawdown" in limit_names
        assert "min_sharpe_ratio" in limit_names

        # Check limit properties
        max_risk_limit = next(
            limit for limit in limits if limit.name == "max_position_risk"
        )
        assert max_risk_limit.metric_name == "total_risk_score"
        assert max_risk_limit.threshold == 0.8
        assert max_risk_limit.operator == "lt"
        assert max_risk_limit.action == "reduce"

    def test_custom_risk_limits(self, sample_risk_limits):
        """Test custom risk limits."""
        manager = MLRiskManager(risk_limits=sample_risk_limits)
        assert len(manager.risk_limits) == 3
        assert manager.risk_limits[0].name == "max_position_risk"

    def test_check_limit_violations(self, sample_risk_limits):
        """Test limit violation checking."""
        manager = MLRiskManager(risk_limits=sample_risk_limits)

        # Test no violation
        assert manager._check_limit_violation(0.5, 0.8, "lt") == False
        assert manager._check_limit_violation(0.8, 0.8, "lt") == False
        assert manager._check_limit_violation(0.6, 0.8, "gt") == True

        # Test violation
        assert manager._check_limit_violation(0.9, 0.8, "lt") == True
        assert manager._check_limit_violation(0.7, 0.8, "gt") == False


if __name__ == "__main__":
    pytest.main([__file__])
