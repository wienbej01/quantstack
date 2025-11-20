"""SIP (Symbol Selection by Independent Popularity) screener implementation.

This module provides deterministic universe selection based on relative volume
ranking with cross-sectional filtering for quantitative trading strategies.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qx_data.gold_loader import load_bars
from qx_features.core_basics import rel_volume_m


@dataclass
class ScreenerConfig:
    """Configuration for SIP screener."""

    top_n: int = 10
    min_relative_volume: float = 1.0
    min_price: float = 10.0
    max_price: float = 1000.0
    min_dollar_volume: float = 1_000_000  # $1M average daily dollar volume minimum
    lookback_days: int = 20
    volume_window: int = 30
    exclude_symbols: list[str] = None

    def __post_init__(self):
        if self.exclude_symbols is None:
            self.exclude_symbols = []


class SipScreener:
    """SIP screener for deterministic universe selection."""

    def __init__(self, config: ScreenerConfig | None = None):
        """Initialize SIP screener.

        Args:
            config: Screener configuration, defaults to reasonable values
        """
        self.config = config or ScreenerConfig()

    def screen_universe(
        self, bars: pd.DataFrame, reference_date: str | None = None
    ) -> pd.DataFrame:
        """Screen universe based on SIP criteria.

        Args:
            bars: DataFrame with OHLCV data
            reference_date: Reference date for ranking (YYYY-MM-DD format)

        Returns:
            DataFrame with screened symbols and rankings
        """
        if bars.empty:
            return pd.DataFrame()

        # Ensure required columns
        required_cols = ["ts", "symbol", "open", "high", "low", "close", "volume"]
        missing_cols = [col for col in required_cols if col not in bars.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")

        # Filter by reference date if provided
        if reference_date is not None:
            reference_ts = pd.Timestamp(reference_date).value
            bars = bars[bars["ts"] <= reference_ts]

        # Calculate relative volume
        bars_with_rvol = self._add_relative_volume(bars)

        avg_daily_dollar_volume = self._compute_avg_daily_dollar_volume(bars_with_rvol)

        # Get latest data per symbol
        latest_data = self._get_latest_per_symbol(bars_with_rvol)
        latest_data = latest_data.join(
            avg_daily_dollar_volume.rename("avg_daily_dollar_volume"), on="symbol"
        )

        # Apply filters
        filtered_data = self._apply_filters(latest_data)

        # Rank by relative volume
        ranked_data = self._rank_by_relative_volume(filtered_data)

        # Select top N
        selected_data = ranked_data.head(self.config.top_n)

        return selected_data

    def _add_relative_volume(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Add relative volume to bars DataFrame."""
        bars = bars.copy()

        # Calculate relative volume per symbol
        rvol_series = []
        for _symbol, group in bars.groupby("symbol"):
            symbol_rvol = rel_volume_m(group, self.config.volume_window)
            rvol_series.append(symbol_rvol)

        if rvol_series:
            bars["relative_volume"] = pd.concat(rvol_series).sort_index()
        else:
            bars["relative_volume"] = 1.0

        return bars

    def _get_latest_per_symbol(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Get latest bar data per symbol."""
        # Sort by timestamp descending and take first per symbol
        bars_sorted = bars.sort_values(["symbol", "ts"], ascending=[True, False])
        latest_per_symbol = bars_sorted.groupby("symbol").head(1)
        return latest_per_symbol

    def _compute_avg_daily_dollar_volume(self, bars: pd.DataFrame) -> pd.Series:
        """Compute average daily dollar volume per symbol over the lookback window."""
        if bars.empty:
            return pd.Series(dtype=float)

        bars = bars.copy()
        bars["trade_date"] = pd.to_datetime(bars["ts"]).dt.normalize()
        bars["minute_dollar_volume"] = bars["close"] * bars["volume"]

        daily_dv = (
            bars.groupby(["symbol", "trade_date"])["minute_dollar_volume"]
            .sum()
            .rename("daily_dollar_volume")
        )
        avg_daily_dv = daily_dv.groupby("symbol").mean()
        return avg_daily_dv

    def _apply_filters(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply screening filters."""
        filtered = data.copy()

        # Price filters
        filtered = filtered[
            (filtered["close"] >= self.config.min_price)
            & (filtered["close"] <= self.config.max_price)
        ]

        # Relative volume filter
        filtered = filtered[filtered["relative_volume"] >= self.config.min_relative_volume]

        # Dollar volume filters
        filtered["dollar_volume"] = filtered["close"] * filtered["volume"]
        filtered["avg_daily_dollar_volume"] = filtered["avg_daily_dollar_volume"].fillna(0.0)
        filtered = filtered[filtered["avg_daily_dollar_volume"] >= self.config.min_dollar_volume]

        # Exclude specific symbols
        if self.config.exclude_symbols:
            filtered = filtered[~filtered["symbol"].isin(self.config.exclude_symbols)]

        return filtered

    def _rank_by_relative_volume(self, data: pd.DataFrame) -> pd.DataFrame:
        """Rank symbols by relative volume (descending)."""
        ranked = data.copy()
        ranked["rvol_rank"] = ranked["relative_volume"].rank(ascending=False, method="min")
        ranked = ranked.sort_values("rvol_rank")
        return ranked


def compute_relative_volume_rank(
    bars: pd.DataFrame, window: int = 30, reference_date: str | None = None
) -> pd.DataFrame:
    """Compute relative volume ranking for all symbols.

    Args:
        bars: DataFrame with OHLCV data
        window: Lookback window for relative volume calculation
        reference_date: Reference date for ranking

    Returns:
        DataFrame with symbols and their relative volume ranks
    """
    screener = SipScreener(ScreenerConfig(volume_window=window))

    if reference_date is not None:
        reference_ts = pd.Timestamp(reference_date).value
        bars = bars[bars["ts"] <= reference_ts]

    # Add relative volume
    bars_with_rvol = screener._add_relative_volume(bars)

    # Get latest relative volume per symbol
    latest_per_symbol = screener._get_latest_per_symbol(bars_with_rvol)

    # Rank by relative volume
    ranked = screener._rank_by_relative_volume(latest_per_symbol)

    # Return only relevant columns
    result = ranked[["symbol", "relative_volume", "rvol_rank", "close", "volume"]].copy()
    result["dollar_volume"] = result["close"] * result["volume"]

    return result


def select_top_symbols(
    bars: pd.DataFrame,
    top_n: int = 10,
    min_relative_volume: float = 1.0,
    min_price: float = 10.0,
    max_price: float = 1000.0,
    min_dollar_volume: float = 1_000_000,
    reference_date: str | None = None,
) -> list[str]:
    """Select top N symbols based on SIP criteria.

    Args:
        bars: DataFrame with OHLCV data
        top_n: Number of symbols to select
        min_relative_volume: Minimum relative volume threshold
        min_price: Minimum price threshold
        max_price: Maximum price threshold
        min_dollar_volume: Minimum daily dollar volume
        reference_date: Reference date for selection

    Returns:
        List of selected symbol names
    """
    config = ScreenerConfig(
        top_n=top_n,
        min_relative_volume=min_relative_volume,
        min_price=min_price,
        max_price=max_price,
        min_dollar_volume=min_dollar_volume,
    )

    screener = SipScreener(config)
    screened_data = screener.screen_universe(bars, reference_date)

    return screened_data["symbol"].tolist()


def load_and_screen(
    gold_root: str,
    symbols: list[str],
    dates: list[str],
    config: ScreenerConfig | None = None,
) -> pd.DataFrame:
    """Load bars from Gold layer and apply SIP screening.

    Args:
        gold_root: Root path to Gold layer data
        symbols: List of symbols to load
        dates: List of dates to load
        config: Screener configuration

    Returns:
        DataFrame with screened symbols
    """
    # Load bars from Gold layer
    bars = load_bars(
        root=gold_root,
        family="equities",
        symbols=symbols,
        dates=dates,
        validate=True,
        sort=True,
    )

    if bars.empty:
        return pd.DataFrame()

    # Apply screening
    screener = SipScreener(config)
    reference_date = dates[-1] if dates else None  # Use latest date as reference
    screened_data = screener.screen_universe(bars, reference_date)

    return screened_data


def screen(
    df: pd.DataFrame, rvol_col: str, top_n: int = 5, whitelist: list[str] | None = None
) -> dict[int, set[str]]:
    """Legacy screen function for backward compatibility.

    Args:
        df: DataFrame with ts, symbol, and rvol_col
        rvol_col: Column name for relative volume
        top_n: Number of top symbols to select per timestamp
        whitelist: Optional list of allowed symbols

    Returns:
        Dict mapping timestamp to set of selected symbols
    """
    universe = {}
    for ts, group in df.groupby("ts"):
        # Sort by rvol descending, then symbol ascending for deterministic ties
        sorted_group = group.sort_values([rvol_col, "symbol"], ascending=[False, True])
        candidates = sorted_group["symbol"].head(top_n).tolist()

        # Apply whitelist if provided
        if whitelist:
            candidates = [s for s in candidates if s in whitelist]

        universe[ts] = set(candidates)

    return universe


def create_sample_universe_data() -> pd.DataFrame:
    """Create sample universe data for testing.

    Returns:
        DataFrame with sample bar data for multiple symbols
    """
    np.random.seed(42)  # For reproducible results

    symbols = [
        "AAPL",
        "GOOGL",
        "MSFT",
        "AMZN",
        "TSLA",
        "META",
        "NVDA",
        "NFLX",
        "AMD",
        "INTC",
    ]
    dates = pd.date_range("2023-01-01", "2023-01-20", freq="D")

    bars = []
    for symbol in symbols:
        for date in dates:
            # Skip weekends for more realistic data
            if date.weekday() >= 5:
                continue

            # Base price varies by symbol
            base_price = np.random.uniform(50, 500)

            # Generate OHLC data
            close = base_price * (1 + np.random.normal(0, 0.02))
            high = close * (1 + abs(np.random.normal(0, 0.01)))
            low = close * (1 - abs(np.random.normal(0, 0.01)))
            open_price = low + (high - low) * np.random.uniform(0, 1)

            # Volume varies by symbol and has some correlation with price movement
            base_volume = np.random.uniform(100_000, 10_000_000)
            volume_multiplier = (
                1 + (close - base_price) / base_price * 2
            )  # Higher volume on bigger moves
            volume = int(base_volume * volume_multiplier)

            ts = pd.Timestamp(date).value

            bars.append(
                {
                    "ts": ts,
                    "symbol": symbol,
                    "open": round(open_price, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": volume,
                }
            )

    df = pd.DataFrame(bars)
    return df.sort_values(["symbol", "ts"]).reset_index(drop=True)
