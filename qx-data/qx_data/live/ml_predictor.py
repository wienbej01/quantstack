"""ML model integration for live trading."""

import logging
import pickle
from pathlib import Path
from typing import Any, Optional

import numpy as np
from ib_insync import MarketOrder

from qx_broker.ibkr import (
    ContractFactory,
    IBKRAccount,
    IBKRConnectionConfig,
    IBKROrderConfig,
    IBKROrderManager,
    IBKRSession,
    IBKRSessionConfig,
)


class RegimeAwarePredictor:
    """Wrapper for regime-aware ML models."""

    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self.models = {}
        self.logger = logging.getLogger(__name__)
        self._load_models()

    def _load_models(self):
        """Load trained regime-aware models."""
        try:
            # Look for regime-specific models
            model_files = list(self.model_path.glob("*_model.pkl"))

            if not model_files:
                self.logger.warning(f"No models found in {self.model_path}")
                return

            for model_file in model_files:
                regime = model_file.stem.replace("_model", "")
                with open(model_file, "rb") as f:
                    self.models[regime] = pickle.load(f)
                self.logger.info(f"Loaded {regime} model")

        except Exception as e:
            self.logger.error(f"Failed to load models: {e}")

    def detect_regime(self, market_data: dict[str, Any]) -> str:
        """Detect current market regime based on market volatility."""
        volatility = market_data.get("market_volatility", 0.02)
        market_ret = market_data.get("market_ret", 0.0)

        # Bull: positive returns, moderate volatility
        if market_ret > 0.005 and volatility < 0.03:
            return "bull"
        # Bear: negative returns, high volatility
        elif market_ret < -0.005 or volatility > 0.04:
            return "bear"
        # Sideways: low returns, low volatility
        else:
            return "sideways"

    def predict(self, symbol: str, features: dict[str, Any]) -> Optional[float]:
        """Make prediction for symbol."""
        try:
            # Detect regime
            regime = self.detect_regime(features)

            if regime not in self.models:
                self.logger.warning(f"No model for regime: {regime}")
                return None

            # Extract 11 cross-sectional features from real market data
            feature_vector = self._extract_features(features)

            if feature_vector is None:
                return None

            # Make prediction
            model = self.models[regime]
            prediction = model.predict_proba([feature_vector])[0][
                1
            ]  # Probability of positive return

            self.logger.debug(
                f"{symbol} prediction: {prediction:.3f} (regime: {regime})"
            )
            return float(prediction)

        except Exception as e:
            self.logger.error(f"Prediction failed for {symbol}: {e}")
            return None

    def _extract_features(self, data: dict[str, Any]) -> Optional[np.ndarray]:
        """Extract 11 cross-sectional features from real market data."""
        try:
            # Cross-sectional features (from training)
            features = [
                data.get("cross_rank_ret", 0.5),  # Cross-sectional return rank
                data.get("cross_rank_vol", 0.5),  # Cross-sectional volume rank
                data.get("sector_momentum", 0.0),  # Sector momentum
                data.get("cross_dispersion", 0.0),  # Cross-sectional dispersion
                data.get("market_breadth", 0.5),  # Market breadth
                data.get("up_down_ratio", 1.0),  # Up/down ratio
                data.get("rel_strength_5", 0.0),  # 5-period relative strength
                data.get("rel_strength_10", 0.0),  # 10-period relative strength
                data.get("rel_strength_20", 0.0),  # 20-period relative strength
                data.get("market_ret_5", 0.0),  # 5-period market return
                data.get("market_ret_10", 0.0),  # 10-period market return
            ]

            return np.array(features)

        except Exception as e:
            self.logger.error(f"Feature extraction failed: {e}")
            return None


class PaperTrader:
    """Paper trading execution via IBKR."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 400,
        account_id: str | None = None,
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account_id = account_id
        self.logger = logging.getLogger(__name__)

        connection = IBKRConnectionConfig(host=host, port=port, client_id=client_id)
        session_cfg = IBKRSessionConfig(system_name="INTRADAY_PAPER", connection=connection)
        self.session = IBKRSession(session_cfg)
        self.contracts = ContractFactory(self.session)
        self.account = IBKRAccount(self.session)
        self.orders = IBKROrderManager(
            self.session,
            IBKROrderConfig(order_ref_prefix="INTRADAY_PAPER", account=account_id),
        )

    def connect(self) -> bool:
        """Connect to IBKR."""
        if not self.session.connect():
            self.logger.error("IBKR connection failed")
            return False

        if not self.account_id:
            self.account_id = self._resolve_account_id()
        self.logger.info("Connected to IBKR for paper trading")
        return True

    def _resolve_account_id(self) -> str | None:
        try:
            accounts = self.session.call(self.session.ib.managedAccounts, timeout=5)
            if accounts:
                return accounts[0]
        except Exception as exc:
            self.logger.warning("managedAccounts lookup failed: %s", exc)

        try:
            summary = self.session.call(self.session.ib.accountSummary, timeout=10)
            if summary:
                return summary[0].account
        except Exception as exc:
            self.logger.warning("accountSummary lookup failed: %s", exc)

        return None

    def place_order(self, symbol: str, action: str, quantity: int = 100) -> bool:
        """Place paper trade order."""
        if not self.session.is_connected():
            self.logger.error("Not connected to IBKR")
            return False

        try:
            contract = self.contracts.stock(symbol, "SMART", "USD")
            contract = self.contracts.qualify(contract)
            order = MarketOrder(action, quantity)
            if self.account_id:
                order.account = self.account_id
            self.orders.place_order(contract, order)
            self.logger.info("Paper trade placed: %s %s %s", action, quantity, symbol)
            return True
        except Exception as exc:
            self.logger.error("Order placement failed: %s", exc)
            return False

    def get_positions(self) -> dict[str, Any]:
        """Get current positions."""
        if not self.session.is_connected():
            return {}

        try:
            positions = self.account.positions()
            return {pos.contract.symbol: pos.position for pos in positions}
        except Exception as exc:
            self.logger.error("Failed to get positions: %s", exc)
            return {}

    def disconnect(self) -> None:
        """Disconnect from IBKR."""
        self.session.disconnect()
        self.logger.info("Disconnected from IBKR")
