"""Intraday ML Universe Adapter

Thin adapter that calls existing screener utilities for universe selection.
Provides configuration-driven universe building for ML pipeline.
"""

import pandas as pd

from qx_data.gold_loader import load_bars
from qx_screener.sip import ScreenerConfig, SipScreener


class IntradayMLUniverseAdapter:
    """Adapter for building ML universe using existing screener utilities."""

    def __init__(self, universe_config: dict):
        """Initialize universe adapter with configuration.

        Args:
            universe_config: Dictionary from universe.yaml
        """
        self.config = universe_config

        # Map intraday_ml config to SIP config
        self.sip_config = ScreenerConfig(
            top_n=self.config.get("max_universe_size", 12),
            min_price=self.config.get("min_price", 5.0),
            max_price=self.config.get("max_price", 50.0),
            min_dollar_volume=self.config.get("min_avg_daily_volume", 1_000_000),
            min_relative_volume=self.config.get("min_relative_volume", 0.8),
            lookback_days=self.config.get("lookback_days", 20),
            volume_window=self.config.get("volume_window", 30),
            exclude_symbols=self.config.get("exclude_symbols", []),
        )

        self.screener = SipScreener(self.sip_config)

    def build_universe(
        self,
        gold_root: str,
        symbols: list[str],
        dates: list[str],
        reference_date: str | None = None,
    ) -> pd.DataFrame:
        """Build universe using existing SIP screener.

        Args:
            gold_root: Path to Gold data root
            symbols: Candidate symbols to screen
            dates: Date range for screening
            reference_date: Reference date for universe selection

        Returns:
            DataFrame with selected universe symbols and metadata
        """
        # Load bars using existing loader
        bars = load_bars(
            root=gold_root,
            family="bars_1m",
            symbols=symbols,
            dates=dates,
            validate=True,
            sort=True,
        )

        # Apply SIP screener
        universe = self.screener.screen_universe(bars, reference_date)

        # Add ML-specific metadata
        universe = self._add_ml_metadata(universe, dates)

        return universe

    def _add_ml_metadata(self, universe: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
        """Add ML-specific metadata to universe DataFrame.

        Args:
            universe: Universe DataFrame from screener
            dates: Date range used for screening

        Returns:
            Enhanced universe DataFrame with ML metadata
        """
        universe = universe.copy()

        # Add screening metadata
        universe["ml_universe_size"] = len(universe)
        universe["ml_screening_dates"] = f"{dates[0]}_to_{dates[-1]}"
        universe["ml_min_price"] = self.config.get("min_price", 5.0)
        universe["ml_max_price"] = self.config.get("max_price", 50.0)
        universe["ml_min_adv"] = self.config.get("min_avg_daily_volume", 1_000_000)

        return universe

    def get_eligibility_counts(self, universe: pd.DataFrame) -> dict:
        """Get eligibility statistics for the universe.

        Args:
            universe: Universe DataFrame from build_universe

        Returns:
            Dictionary with eligibility counts and statistics
        """
        stats = {
            "total_symbols_screened": len(universe),
            "eligible_symbols": len(universe),
            "price_range": [
                float(universe["close"].min()),
                float(universe["close"].max()),
            ],
            "avg_dollar_volume": (
                float(universe["dollar_volume"].mean())
                if "dollar_volume" in universe.columns
                else None
            ),
            "avg_relative_volume": (
                float(universe["relative_volume"].mean())
                if "relative_volume" in universe.columns
                else None
            ),
        }

        return stats
