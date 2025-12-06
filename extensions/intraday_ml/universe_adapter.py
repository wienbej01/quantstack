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
        self._last_screening_report: dict[str, dict] | None = None

    def build_universe(
        self,
        gold_root: str,
        symbols: list[str],
        dates: list[str],
        reference_date: str | None = None,
        date_ranges: dict[str, dict[str, str]] | None = None,
        collect_diagnostics: bool = False,
    ) -> pd.DataFrame:
        """Build universe using existing SIP screener.

        Args:
            gold_root: Path to Gold data root
            symbols: Candidate symbols to screen
            dates: Date range for screening
            reference_date: Reference date for universe selection
            date_ranges: Optional split date ranges used for coverage diagnostics
            collect_diagnostics: Whether to collect per-symbol diagnostics

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

        if reference_date is not None:
            reference_ts = pd.Timestamp(reference_date).value
            bars = bars[bars["ts"] <= reference_ts]

        latest_data = pd.DataFrame()
        filtered_data = pd.DataFrame()
        universe = pd.DataFrame()

        if not bars.empty:
            bars_with_rvol = self.screener._add_relative_volume(bars)
            avg_daily_dollar_volume = self.screener._compute_avg_daily_dollar_volume(
                bars_with_rvol
            )
            latest_data = self.screener._get_latest_per_symbol(bars_with_rvol)
            latest_data = latest_data.join(
                avg_daily_dollar_volume.rename("avg_daily_dollar_volume"), on="symbol"
            )
            filtered_data = self.screener._apply_filters(latest_data)
            ranked_data = self.screener._rank_by_relative_volume(filtered_data)
            universe = ranked_data.head(self.sip_config.top_n)

        if collect_diagnostics:
            symbol_days = (
                pd.DataFrame(
                    {
                        "symbol": bars["symbol"].astype(str).str.upper(),
                        "trade_date": pd.to_datetime(bars["ts"]).dt.normalize(),
                    }
                ).drop_duplicates()
                if not bars.empty
                else pd.DataFrame(columns=["symbol", "trade_date"])
            )
            self._last_screening_report = self._collect_screening_report(
                symbols=symbols,
                latest_data=latest_data,
                filtered_data=filtered_data,
                selected_data=universe,
                symbol_days=symbol_days,
                date_ranges=date_ranges or {},
            )
        else:
            self._last_screening_report = None

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

    def get_last_screening_report(self) -> dict[str, dict] | None:
        """Return the most recent screening diagnostics report, if collected."""
        return self._last_screening_report

    def _collect_screening_report(
        self,
        *,
        symbols: list[str],
        latest_data: pd.DataFrame,
        filtered_data: pd.DataFrame,
        selected_data: pd.DataFrame,
        symbol_days: pd.DataFrame,
        date_ranges: dict[str, dict[str, str]],
    ) -> dict[str, dict]:
        """Compile diagnostics for the screened universe."""

        def _normalize(symbol: str) -> str:
            return str(symbol).upper()

        latest_norm = (
            latest_data.assign(symbol=_normalize_series(latest_data["symbol"]))
            if not latest_data.empty
            else pd.DataFrame(columns=["symbol"])
        )
        latest_lookup = (
            latest_norm.set_index("symbol") if not latest_norm.empty else pd.DataFrame()
        )

        filtered_symbols = (
            {_normalize(sym) for sym in filtered_data["symbol"].tolist()}
            if not filtered_data.empty
            else set()
        )
        selected_symbols = (
            {_normalize(sym) for sym in selected_data["symbol"].tolist()}
            if not selected_data.empty
            else set()
        )

        candidate_pool = {_normalize(sym) for sym in symbols}
        candidate_pool.update(filtered_symbols)
        candidate_pool.update(selected_symbols)
        if not latest_norm.empty:
            candidate_pool.update(latest_norm["symbol"].tolist())
        candidate_list = sorted(candidate_pool)

        total_days = (
            symbol_days.groupby("symbol")["trade_date"].nunique()
            if not symbol_days.empty
            else pd.Series(dtype=int)
        )
        train_days = self._count_days(symbol_days, date_ranges.get("train"))
        val_days = self._count_days(symbol_days, date_ranges.get("val"))
        oos_days = self._count_days(symbol_days, date_ranges.get("oos"))
        excluded_symbols = {_normalize(sym) for sym in self.sip_config.exclude_symbols}

        report: dict[str, dict] = {}
        for symbol in candidate_list:
            entry: dict[str, object] = {}
            row = None
            if not latest_lookup.empty and symbol in latest_lookup.index:
                row = latest_lookup.loc[symbol]

            reasons: list[str] = []
            latest_close = None
            relative_volume = None
            avg_daily_dollar_volume = None
            if row is None or row.empty:
                reasons.append("missing_data")
            else:
                latest_close = _safe_float(row.get("close"))
                relative_volume = _safe_float(row.get("relative_volume"))
                avg_daily_dollar_volume = _safe_float(row.get("avg_daily_dollar_volume"))

                if latest_close is None:
                    reasons.append("missing_close")
                else:
                    if latest_close < self.sip_config.min_price:
                        reasons.append("price_below_min")
                    if latest_close > self.sip_config.max_price:
                        reasons.append("price_above_max")

                if relative_volume is None or relative_volume < self.sip_config.min_relative_volume:
                    reasons.append("low_relative_volume")

                if (
                    avg_daily_dollar_volume is None
                    or avg_daily_dollar_volume < self.sip_config.min_dollar_volume
                ):
                    reasons.append("low_avg_dollar_volume")

            if symbol in excluded_symbols:
                reasons.append("excluded_symbol")

            selected = symbol in selected_symbols
            passed_filters = symbol in filtered_symbols

            if passed_filters and not selected:
                reasons.append("below_top_n_cut")
            elif not passed_filters and not reasons:
                reasons.append("filtered_out")

            entry["coverage"] = {
                "total_days": int(total_days.get(symbol, 0)) if not total_days.empty else 0,
                "train_days": int(train_days.get(symbol, 0)) if not train_days.empty else 0,
                "val_days": int(val_days.get(symbol, 0)) if not val_days.empty else 0,
                "oos_days": int(oos_days.get(symbol, 0)) if not oos_days.empty else 0,
            }
            entry["avg_daily_dollar_volume"] = avg_daily_dollar_volume
            entry["latest_close"] = latest_close
            entry["relative_volume"] = relative_volume
            entry["selected"] = selected
            entry["reasons"] = reasons

            report[symbol] = entry

        return report

    def _count_days(
        self, symbol_days: pd.DataFrame, window: dict[str, str] | None
    ) -> pd.Series:
        """Count trading days per symbol in a date window."""
        if (
            window is None
            or not window
            or "start" not in window
            or "end" not in window
            or symbol_days.empty
        ):
            return pd.Series(dtype=int)

        start = pd.to_datetime(window["start"]).normalize()
        end = pd.to_datetime(window["end"]).normalize()
        mask = (symbol_days["trade_date"] >= start) & (symbol_days["trade_date"] <= end)
        if not mask.any():
            return pd.Series(dtype=int)
        return symbol_days.loc[mask].groupby("symbol")["trade_date"].nunique()


def _normalize_series(series: pd.Series) -> pd.Series:
    """Return uppercase symbol labels for indexing."""
    return series.astype(str).str.upper()


def _safe_float(value: object) -> float | None:
    """Convert pandas scalars to Python floats, preserving None."""
    if value is None or pd.isna(value):
        return None
    return float(value)
