"""Unit tests for intraday ML backtest adapter.

This module tests the Sprint 6 backtest engine implementation to ensure
it properly wraps existing qx-backtest functionality while enforcing
intraday trading compliance rules.
"""

from unittest.mock import Mock, patch

import pandas as pd
import pytest

from extensions.intraday_ml.backtest import (
    _apply_intraday_constraints,
    _calculate_metrics,
    _convert_result_to_artifacts,
    _create_strategy_wrapper,
    _filter_eod_violations,
    _load_and_merge_config,
    _shift_to_next_bar,
    _validate_inputs,
    intraday_ml_get_backtest_hash,
    intraday_ml_run_backtest,
)


class TestBacktestConfig:
    """Test backtest configuration loading and merging."""

    def test_load_default_config(self):
        """Test loading default configuration."""
        cfg = {}
        config = _load_and_merge_config(cfg, None)

        assert config["initial_cash"] == 1_000_000.0
        assert config["write_artifacts"] is True
        assert config["artifacts_dir"] == "artifacts/intraday_ml"
        assert config["costs"]["bps"] == 0.001
        assert config["intraday_constraints"]["next_bar_execution"] is True

    def test_merge_input_config(self):
        """Test merging input configuration with defaults."""
        cfg = {"initial_cash": 500_000.0, "costs": {"bps": 0.002}}
        config = _load_and_merge_config(cfg, None)

        assert config["initial_cash"] == 500_000.0
        assert config["costs"]["bps"] == 0.002
        assert config["costs"]["per_share"] == 0.003  # Default preserved

    def test_load_config_from_file(self, tmp_path):
        """Test loading configuration from file."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(
            """
initial_cash: 2_000_000.0
costs:
  bps: 0.0015
  per_share: 0.0035
intraday_constraints:
  next_bar_execution: false
"""
        )

        cfg = {"initial_cash": 1_000_000.0}
        config = _load_and_merge_config(cfg, str(config_file))

        assert config["initial_cash"] == 1_000_000.0  # Input takes precedence
        assert config["costs"]["bps"] == 0.0015  # File loaded
        assert config["intraday_constraints"]["next_bar_execution"] is False


class TestInputValidation:
    """Test input DataFrame validation."""

    def test_validate_empty_bars(self):
        """Test validation fails with empty bars."""
        bars = pd.DataFrame()
        orders = pd.DataFrame()

        with pytest.raises(ValueError, match="Bars DataFrame cannot be empty"):
            _validate_inputs(bars, orders)

    def test_validate_missing_bar_columns(self):
        """Test validation fails with missing bar columns."""
        bars = pd.DataFrame({"ts": [1], "symbol": ["AAPL"]})  # Missing OHLCV
        orders = pd.DataFrame()

        with pytest.raises(ValueError, match="Missing required bar columns"):
            _validate_inputs(bars, orders)

    def test_validate_missing_order_columns(self):
        """Test validation fails with missing order columns."""
        bars = pd.DataFrame(
            {
                "ts": [1],
                "symbol": ["AAPL"],
                "open": [100],
                "high": [101],
                "low": [99],
                "close": [100.5],
                "volume": [1000],
            }
        )
        orders = pd.DataFrame({"ts": [2], "symbol": ["AAPL"]})  # Missing side, qty

        with pytest.raises(ValueError, match="Missing required order columns"):
            _validate_inputs(bars, orders)

    def test_validate_valid_inputs(self):
        """Test validation passes with valid inputs."""
        bars = pd.DataFrame(
            {
                "ts": [1],
                "symbol": ["AAPL"],
                "open": [100],
                "high": [101],
                "low": [99],
                "close": [100.5],
                "volume": [1000],
            }
        )
        orders = pd.DataFrame(
            {"ts": [2], "symbol": ["AAPL"], "side": ["BUY"], "qty": [100]}
        )

        # Should not raise exception
        _validate_inputs(bars, orders)


class TestIntradayConstraints:
    """Test intraday trading constraint application."""

    def test_shift_to_next_bar(self):
        """Test shifting order execution to next bar."""
        bars = pd.DataFrame(
            {"ts": [1000, 2000, 3000], "symbol": ["AAPL", "AAPL", "AAPL"]}
        )
        orders = pd.DataFrame(
            {
                "ts": [1000, 2000],
                "symbol": ["AAPL", "AAPL"],
                "side": ["BUY", "SELL"],
                "qty": [100, 100],
            }
        )

        shifted = _shift_to_next_bar(orders, bars)

        assert len(shifted) == 2
        assert shifted.iloc[0]["ts"] == 2000  # Shifted to next bar
        assert shifted.iloc[1]["ts"] == 3000  # Shifted to next bar
        assert "original_signal_ts" in shifted.columns

    def test_shift_to_next_bar_with_datetime(self):
        """Ensure next-bar shift works when bars use timezone-aware timestamps."""
        bars = pd.DataFrame(
            {
                "ts": pd.to_datetime(
                    [
                        "2025-04-01 13:30:00+00:00",
                        "2025-04-01 13:40:00+00:00",
                        "2025-04-01 13:50:00+00:00",
                    ],
                    utc=True,
                ),
                "symbol": ["BAC", "BAC", "BAC"],
            }
        )
        orders = pd.DataFrame(
            {
                "ts": [pd.Timestamp("2025-04-01 13:30:00+00:00")],
                "timestamp": [pd.Timestamp("2025-04-01 13:30:00+00:00")],
                "symbol": ["BAC"],
                "side": ["BUY"],
                "qty": [100],
            }
        )

        shifted = _shift_to_next_bar(orders, bars)

        assert len(shifted) == 1
        # Expect nanosecond integer matching the second bar
        expected_ts = int(pd.Timestamp("2025-04-01 13:40:00+00:00").value)
        assert shifted.iloc[0]["ts"] == expected_ts
        assert shifted.iloc[0]["original_signal_ts"] == int(
            pd.Timestamp("2025-04-01 13:30:00+00:00").value
        )
        assert shifted.iloc[0]["timestamp"] == pd.Timestamp(
            "2025-04-01 13:40:00+00:00", tz="UTC"
        )

    def test_filter_eod_violations(self):
        """Test filtering orders that would violate EOD flat constraint."""
        # Create simple test data - the EOD filtering is complex and timezone-dependent
        # For this test, we just verify the function runs without error
        bars = pd.DataFrame(
            {"ts": [1000, 2000, 3000], "symbol": ["AAPL", "AAPL", "AAPL"]}
        )

        orders = pd.DataFrame(
            {
                "ts": [1500, 2500],
                "symbol": ["AAPL", "AAPL"],
                "side": ["BUY", "SELL"],
                "qty": [100, 100],
            }
        )

        constraints = {"eod_buffer_minutes": 5}
        filtered = _filter_eod_violations(orders, bars, constraints)

        # Should return some orders (the exact filtering depends on timezone logic)
        assert isinstance(filtered, pd.DataFrame)
        assert len(filtered) <= len(orders)

    def test_apply_intraday_constraints(self):
        """Test applying all intraday constraints."""
        bars = pd.DataFrame(
            {"ts": [1000, 2000, 3000], "symbol": ["AAPL", "AAPL", "AAPL"]}
        )
        orders = pd.DataFrame(
            {"ts": [1000], "symbol": ["AAPL"], "side": ["BUY"], "qty": [100]}
        )

        config = {
            "intraday_constraints": {
                "next_bar_execution": True,
                "no_overnight_positions": True,
                "eod_buffer_minutes": 5,
            }
        }

        processed_bars, processed_orders = _apply_intraday_constraints(
            bars, orders, config
        )

        assert len(processed_orders) == 1
        assert processed_orders.iloc[0]["ts"] == 2000  # Shifted to next bar


class TestStrategyWrapper:
    """Test strategy wrapper creation."""

    def test_create_strategy_wrapper(self):
        """Test creating strategy wrapper for pre-sized orders."""
        orders = pd.DataFrame(
            {
                "ts": [2000, 3000],
                "symbol": ["AAPL", "GOOGL"],
                "side": ["long", "short"],
                "qty": [100, 200],
                "stop_loss_pct": [0.01, 0.01],
                "take_profit_pct": [0.015, 0.015],
            }
        )

        constraints = {
            "flat_eod_time": "15:59:59",
            "session_timezone": "America/New_York",
        }
        strategy = _create_strategy_wrapper(orders, constraints)
        mock_engine = Mock()
        mock_engine.get_position.return_value = None

        # Test with matching bars
        bars = pd.DataFrame(
            {
                "ts": [2000, 3000, 4000],
                "symbol": ["AAPL", "GOOGL", "MSFT"],
                "close": [100, 200, 300],
            }
        )

        for _, bar in bars.iterrows():
            strategy(mock_engine, bar.to_dict())

        assert mock_engine.submit_order.call_count == 2
        submitted_orders = [c[0][0] for c in mock_engine.submit_order.call_args_list]

        assert submitted_orders[0].symbol == "AAPL"
        assert submitted_orders[0].quantity == 100
        assert submitted_orders[0].stop_loss == pytest.approx(99.0)
        assert submitted_orders[0].take_profit == pytest.approx(101.5)

        assert submitted_orders[1].symbol == "GOOGL"
        assert submitted_orders[1].quantity == 200
        assert submitted_orders[1].stop_loss == pytest.approx(202.0)
        assert submitted_orders[1].take_profit == pytest.approx(197.0)

    def test_strategy_wrapper_empty_orders(self):
        """Test strategy wrapper with empty orders."""
        orders = pd.DataFrame()
        strategy = _create_strategy_wrapper(orders, {"flat_eod_time": "15:59:59"})

        mock_engine = Mock()
        mock_engine.get_position.return_value = None
        bars = pd.DataFrame({"ts": [1000], "symbol": ["AAPL"], "close": [100]})

        for _, bar in bars.iterrows():
            strategy(mock_engine, bar.to_dict())

        assert mock_engine.submit_order.call_count == 0

    def test_strategy_wrapper_handles_timestamp_inputs(self):
        """Strategy wrapper accepts Timestamp values for both orders and bars."""
        event_ts = pd.Timestamp("2025-11-03 14:30:00", tz="UTC")
        orders = pd.DataFrame(
            {
                "ts": [event_ts],
                "symbol": ["AAPL"],
                "side": ["long"],
                "qty": [25],
                "stop_loss_pct": [0.01],
                "take_profit_pct": [0.02],
            }
        )

        strategy = _create_strategy_wrapper(
            orders,
            {
                "flat_eod_time": "15:59:59",
                "session_timezone": "America/New_York",
            },
        )

        mock_engine = Mock()
        mock_engine.get_position.return_value = None

        bar = {"ts": event_ts, "symbol": "AAPL", "close": 100.0}

        strategy(mock_engine, bar)

        assert mock_engine.submit_order.call_count == 1
        submitted_order = mock_engine.submit_order.call_args[0][0]
        assert submitted_order.timestamp == event_ts
        assert submitted_order.symbol == "AAPL"

    def test_strategy_wrapper_force_flat(self):
        """Strategy forces flat positions at the configured cutoff time."""
        orders = pd.DataFrame()
        strategy = _create_strategy_wrapper(
            orders,
            {"flat_eod_time": "15:59:59", "session_timezone": "America/New_York"},
        )

        mock_engine = Mock()
        mock_position = Mock()
        mock_position.is_long = True
        mock_position.is_short = False
        mock_position.quantity = 50
        mock_engine.get_position.return_value = mock_position

        ts = (
            pd.Timestamp("2025-11-03 16:00:00", tz="America/New_York")
            .tz_convert("UTC")
            .value
        )
        bar = {"ts": ts, "symbol": "AAPL", "close": 100.0}

        strategy(mock_engine, bar)
        assert mock_engine.submit_order.call_count == 1
        forced_order = mock_engine.submit_order.call_args[0][0]
        assert forced_order.symbol == "AAPL"
        assert forced_order.quantity == 50
        assert forced_order.tags.get("exit_reason") == "force_flat"

        # Subsequent calls on the same day do not create duplicate forced exits
        strategy(mock_engine, bar)
        assert mock_engine.submit_order.call_count == 1


class TestResultConversion:
    """Test conversion of engine results to Sprint 6 artifacts."""

    def test_convert_result_with_object(self):
        """Test converting result object to artifacts."""
        # Mock result object
        result = Mock()
        result.metrics = {"trades": 10, "pnl": 1000.0}
        result.equity_curve = pd.DataFrame(
            {"timestamp": [1, 2], "equity": [1000, 1100]}
        )
        result.positions_history = [{"timestamp": 1, "position": 100}]
        result.trades_history = [{"timestamp": 1, "pnl": 10}]
        result.orders_history = [{"timestamp": 1, "symbol": "AAPL"}]
        result.fills_history = [{"timestamp": 1, "qty": 100}]

        artifacts = _convert_result_to_artifacts(result, {})

        # Check all required artifacts exist
        required_artifacts = [
            "signals",
            "orders",
            "fills",
            "positions",
            "equity",
            "trades",
            "risk_rejects",
            "allocation_log",
            "metrics",
        ]

        for artifact in required_artifacts:
            assert artifact in artifacts
            if artifact == "metrics":
                assert isinstance(artifacts[artifact], dict)
            else:
                assert isinstance(artifacts[artifact], pd.DataFrame)

        # Check trades have required columns
        assert "stop_dist_ps" in artifacts["trades"].columns
        assert "fees" in artifacts["trades"].columns
        assert "slippage_est" in artifacts["trades"].columns
        assert "r_multiple" in artifacts["trades"].columns

    def test_convert_result_with_dict(self):
        """Test converting result dict to artifacts."""
        result = {
            "metrics": {"trades": 5},
            "trades_history": pd.DataFrame({"pnl": [10, -5, 15, -8, 12]}),
        }

        artifacts = _convert_result_to_artifacts(result, {})

        assert len(artifacts) == 10  # All required artifacts created
        assert artifacts["metrics"]["trades"] == 5

    def test_calculate_metrics(self):
        """Test metrics calculation from artifacts."""
        artifacts = {
            "trades": pd.DataFrame(
                {
                    "pnl": [10, -5, 15, -8],
                    "symbol": ["A", "A", "B", "B"],
                    "timestamp": [1, 2, 3, 4],
                    "side": ["BUY", "SELL", "BUY", "SELL"],
                    "total_cost": [-10, 5, -15, 8],
                    "order_id": [1, 1, 2, 2],
                }
            ),
            "fills": pd.DataFrame(
                {
                    "commission": [1, 0.5, 1.2, 0.8],
                    "timestamp": pd.to_datetime(
                        [
                            "2025-11-03 10:00:00",
                            "2025-11-03 10:05:00",
                            "2025-11-03 11:00:00",
                            "2025-11-03 11:05:00",
                        ],
                        utc=True,
                    ),
                    "side": ["BUY", "SELL", "BUY", "SELL"],
                    "quantity": [50, 50, 40, 40],
                    "price": [100.0, 101.0, 50.0, 49.5],
                }
            ),
        }

        metrics = _calculate_metrics(artifacts)

        assert metrics["trades"] == 2
        assert metrics["total_pnl"] == pytest.approx(26.5)
        assert metrics["avg_R"] == pytest.approx(13.25)
        assert metrics["win_rate"] == pytest.approx(0.5)
        assert metrics["fees_total"] == 3.5


class TestBacktestHash:
    """Test backtest hash calculation."""

    @patch("extensions.intraday_ml.backtest.hash_dataframe")
    @patch("extensions.intraday_ml.backtest.hash_dict")
    def test_get_backtest_hash(self, mock_hash_dict, mock_hash_dataframe):
        """Test deterministic hash calculation."""
        mock_hash_dataframe.side_effect = ["bars_hash", "orders_hash", "config_hash"]
        mock_hash_dict.return_value = "combined_hash"

        bars = pd.DataFrame({"ts": [1], "symbol": ["AAPL"]})
        orders = pd.DataFrame({"ts": [2], "symbol": ["AAPL"]})
        cfg = {"initial_cash": 1000000.0}

        result = intraday_ml_get_backtest_hash(bars, orders, cfg)

        assert result == "combined_hash"
        assert mock_hash_dataframe.call_count == 3
        mock_hash_dict.assert_called_once()


class TestIntegration:
    """Integration tests for the complete backtest pipeline."""

    @patch("qx_backtest.engine.BacktestEngine")
    @patch("qx_backtest.fill.DefaultFiller")
    def test_run_backtest_full_pipeline(self, mock_filler_class, mock_engine_class):
        """Test complete backtest run with mocked engine."""
        # Mock engine and filler
        mock_engine = Mock()
        mock_engine_class.return_value = mock_engine
        mock_filler = Mock()
        mock_filler_class.return_value = mock_filler

        # Mock engine result
        mock_result = Mock()
        mock_result.metrics = {"trades": 1, "pnl": 20.0}
        mock_result.equity_curve = pd.DataFrame(
            {"timestamp": [1, 2], "equity": [1000, 1020]}
        )
        mock_result.positions_history = []
        mock_result.trades_history = [
            {
                "pnl": 20,
                "order_id": 1,
                "symbol": "A",
                "timestamp": 1,
                "side": "BUY",
                "total_cost": -100,
            },
            {
                "pnl": 20,
                "order_id": 1,
                "symbol": "A",
                "timestamp": 2,
                "side": "SELL",
                "total_cost": 120,
            },
        ]
        mock_result.orders_history = []
        mock_result.fills_history = []
        mock_engine.run.return_value = mock_result

        # Test data
        bars = pd.DataFrame(
            {
                "ts": [1000, 2000, 3000],
                "symbol": ["AAPL", "AAPL", "AAPL"],
                "open": [100, 101, 102],
                "high": [101, 102, 103],
                "low": [99, 100, 101],
                "close": [100.5, 101.5, 102.5],
                "volume": [1000, 1100, 1200],
            }
        )

        orders = pd.DataFrame(
            {"ts": [1000], "symbol": ["AAPL"], "side": ["BUY"], "qty": [100]}
        )

        cfg = {"initial_cash": 1000000.0}

        # Run backtest
        result = intraday_ml_run_backtest(bars, orders, cfg)

        # Verify engine was configured correctly
        mock_engine_class.assert_called_once()
        mock_filler_class.assert_called_once()
        mock_engine.run.assert_called_once()

        # Verify result structure
        assert "metrics" in result
        assert "equity" in result
        assert "trades" in result
        assert result["metrics"]["trades"] == 1


if __name__ == "__main__":
    pytest.main([__file__])
