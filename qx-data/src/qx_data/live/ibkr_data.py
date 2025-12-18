"""IBKR Market Data Manager for real-time streaming data."""

import logging
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd
from ib_insync import IB, Stock, util

logger = logging.getLogger(__name__)


class IBKRMarketDataManager:
    """Manages real-time market data from IBKR."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 2):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self.subscribed_symbols = {}
        self.current_data = {}

    def connect(self) -> bool:
        """Connect to IBKR."""
        if self.ib.isConnected():
            return True
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            return self.ib.isConnected()
        except Exception as e:
            logger.error(f"Failed to connect to IBKR: {e}")
            return False

    def disconnect(self):
        """Disconnect from IBKR."""
        if self.ib.isConnected():
            self.ib.disconnect()

    def subscribe_symbols(self, symbols: List[str]):
        """Subscribe to real-time market data."""
        self.ib.reqMarketDataType(3)

        for symbol in symbols:
            try:
                contract = Stock(symbol, "NYSE", "USD")
                self.ib.qualifyContracts(contract)
                ticker = self.ib.reqMktData(
                    contract, "", True, False
                )  # snapshot=True for paper
                self.subscribed_symbols[symbol] = ticker
            except Exception as e:
                logger.warning(f"Failed to subscribe to {symbol}: {e}")

    def get_current_data(self) -> Dict[str, dict]:
        """Get current market data for all subscribed symbols."""
        import math

        self.ib.sleep(0.5)
        data = {}
        for symbol, ticker in self.subscribed_symbols.items():
            last = ticker.last if not math.isnan(ticker.last) else None
            close = ticker.close if not math.isnan(ticker.close) else None
            price = last if last else close
            if price:
                data[symbol] = {
                    "price": price,
                    "volume": ticker.volume if not math.isnan(ticker.volume) else 0,
                    "bid": ticker.bid if not math.isnan(ticker.bid) else price,
                    "ask": ticker.ask if not math.isnan(ticker.ask) else price,
                }
        return data

    def get_all_current_data(self) -> Dict[str, pd.DataFrame]:
        """Get current snapshot data as DataFrames for all subscribed symbols."""
        current = self.get_current_data()
        result = {}
        for symbol, data in current.items():
            result[symbol] = pd.DataFrame([data])
        return result

    def get_historical_bars(
        self, symbol: str, duration: str = "1 D", bar_size: str = "1 min"
    ) -> pd.DataFrame:
        """Get historical bars for a symbol - synchronous version."""
        try:
            contract = Stock(symbol, "NYSE", "USD")
            self.ib.qualifyContracts(contract)

            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )

            if not bars:
                return pd.DataFrame()

            df = util.df(bars)
            df["symbol"] = symbol
            return df

        except Exception as e:
            logger.warning(f"Failed to get bars for {symbol}: {e}")
            return pd.DataFrame()

    def get_all_historical_bars(
        self, symbols: List[str], duration: str = "1 D"
    ) -> Dict[str, pd.DataFrame]:
        """Get historical bars for multiple symbols - sequential to avoid event loop issues."""
        results = {}
        for symbol in symbols:
            df = self.get_historical_bars(symbol, duration)
            if not df.empty:
                results[symbol] = df
        return results

    def compute_cross_sectional_features(
        self, historical_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """Compute cross-sectional features from historical data."""
        if not historical_data:
            return pd.DataFrame()

        features = []
        symbols = list(historical_data.keys())

        for symbol in symbols:
            df = historical_data[symbol]
            if df.empty or len(df) < 20:
                continue

            # Compute features
            returns = df["close"].pct_change()

            feat = {
                "symbol": symbol,
                "price": df["close"].iloc[-1],
                "volume": df["volume"].iloc[-1],
                "ret_1": returns.iloc[-1] if len(returns) > 0 else 0.0,
                "ret_5": df["close"].pct_change(5).iloc[-1] if len(df) >= 5 else 0.0,
                "ret_20": df["close"].pct_change(20).iloc[-1] if len(df) >= 20 else 0.0,
                "vol_ratio": (
                    df["volume"].iloc[-5:].mean() / df["volume"].iloc[-20:].mean()
                    if len(df) >= 20
                    else 1.0
                ),
                "volatility": returns.iloc[-20:].std() if len(returns) >= 20 else 0.0,
            }
            features.append(feat)

        if not features:
            return pd.DataFrame()

        df_features = pd.DataFrame(features)

        # Cross-sectional rankings
        for col in ["ret_1", "ret_5", "ret_20", "vol_ratio"]:
            if col in df_features.columns:
                df_features[f"{col}_rank"] = df_features[col].rank(pct=True)

        return df_features
