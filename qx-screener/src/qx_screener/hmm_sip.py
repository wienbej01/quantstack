from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from qx_core.contracts import UniverseSelector
from qx_core.hashers import hash_sip_map
from qx_core.validators import validate_bars_dataframe

ET_TZ = "America/New_York"


class HMMSIPConfig(BaseModel):
    """Configuration for HMM SIP universe selection with daily mode support"""

    # Daily mode fields
    mode: Literal["legacy", "daily"] = "legacy"
    rebalance_frequency: Literal["daily", "weekly"] = "daily"
    broadcast_time: str = "09:30:00"  # Market open time

    # Existing fields (maintaining backward compatibility)
    top_k: int = 40
    score_floor: float = 0.0
    universe_file: str | None = None
    external_premarket_root: str = Field(
        default=str(Path.home() / "hybrid-local" / "signals" / "sip" / "universe" / "pre"),
        description="Directory for external premarket HMM files",
    )
    enable_gold_fallback: bool = True
    p_hat_threshold: float | None = None
    min_minutes_in_state: int = 0


class HMMSIPUniverseSelector(UniverseSelector):
    name: str = "hmm_sip"

    def __init__(self, cfg: HMMSIPConfig) -> None:
        self.cfg = cfg
        # Simple in-process LRU cache for external parquet reads
        self._cache: dict[tuple[str, str, float], tuple[pd.DataFrame, float]] = {}
        self._cache_ttl_seconds = 3600  # 1 hour TTL
        self._max_cache_size = 100
        # Cache for minute-level p_hat files
        self._p_hat_cache: dict[tuple[str, str, float], tuple[pd.DataFrame, float]] = {}
        self._p_hat_cache_ttl_seconds = 1800  # 30 minutes TTL for p_hat files
        self._p_hat_max_cache_size = 200  # More entries for minute-level data
        # Cache for Gold symbols discovery (expensive operation)
        self._gold_symbols_cache: tuple[set[str], float] | None = None
        self._gold_symbols_cache_ttl_seconds = 7200  # 2 hours TTL for symbols

        # Initialize daily selector if mode is daily
        if self.cfg.mode == "daily":
            # Import locally to avoid circular import
            from .daily_hmm_sip import DailyHMMSIPSelector

            self._daily_selector: DailyHMMSIPSelector | None = DailyHMMSIPSelector(
                score_floor=self.cfg.score_floor,
                top_k=self.cfg.top_k,
                broadcast_time=self.cfg.broadcast_time,
            )
        else:
            self._daily_selector = None

    def select(self, bars_utc: pd.DataFrame, ref: dict, **params) -> dict[int, set[str]]:
        if self.cfg.mode == "daily":
            return self._select_daily_mode(bars_utc, ref, **params)
        else:
            return self._select_legacy_mode(bars_utc, ref, **params)

    def _select_daily_mode(
        self, bars_utc: pd.DataFrame, ref: dict, **params
    ) -> dict[int, set[str]]:
        """Daily mode: compute universe once per day, broadcast to all intraday timestamps"""
        validate_bars_dataframe(bars_utc)
        target_et_date = ref.get("target_date")
        if not target_et_date:
            raise ValueError("target_date required for HMM_SIP selector")

        print(
            f"  [HMM SIP] Using daily mode with top_k={self.cfg.top_k}, "
            f"score_floor={self.cfg.score_floor}"
        )

        # Select daily universes
        self._daily_selector.select_daily_universes(bars_utc)

        # Convert to timestamp-based format for compatibility
        timestamp_universes = {}
        for ts in bars_utc["ts"].unique():
            ts_datetime = pd.to_datetime(ts, unit="ns", utc=True)
            universe = self._daily_selector.get_universe_for_timestamp(ts_datetime)
            timestamp_universes[int(ts)] = universe

        # this hash will be consumed upstream into inputs_checksum.json
        sip_hash = hash_sip_map(timestamp_universes)
        print(
            f"  [HMM SIP] Daily universe map: {len(timestamp_universes)} timestamps, "
            f"sip_hash: {sip_hash[:8]}..."
        )

        return timestamp_universes

    def _select_legacy_mode(
        self, bars_utc: pd.DataFrame, ref: dict, **params
    ) -> dict[int, set[str]]:
        """Original legacy mode implementation"""
        validate_bars_dataframe(bars_utc)
        target_et_date = ref.get("target_date")
        if not target_et_date:
            raise ValueError("target_date required for HMM_SIP selector")

        # Log selector configuration at startup
        print(
            f"  [HMM SIP] Using legacy mode: top_k={self.cfg.top_k}, score_floor={self.cfg.score_floor}, "
            f"p_hat_threshold={self.cfg.p_hat_threshold}, min_minutes_in_state={self.cfg.min_minutes_in_state}"
        )
        print(f"  [HMM SIP] External root: {self.cfg.external_premarket_root}")
        print(
            f"  [HMM SIP] Gold fallback: {'enabled' if self.cfg.enable_gold_fallback else 'disabled'}"
        )

        shortlist = self._load_external_premarket(target_et_date)
        if shortlist is None or (shortlist is not None and len(shortlist) == 0):
            # Trigger Gold fallback if external file doesn't exist or is empty/filtered out
            if self.cfg.enable_gold_fallback:
                print(f"  [HMM SIP] Using Gold fallback for {target_et_date}")
                shortlist = self._compute_gold_premarket_shortlist(bars_utc, target_et_date)

        if not shortlist:
            print(f"  [HMM SIP] No shortlist available for {target_et_date}")
            return {}

        print(f"  [HMM SIP] Shortlist size: {len(shortlist)} symbols")

        # Load minute-level p_hat data if gating is enabled
        minute_p_hat = None
        if self.cfg.p_hat_threshold is not None:
            minute_p_hat = self._load_minute_p_hat_data(target_et_date, shortlist)
            if minute_p_hat is not None:
                print(f"  [HMM SIP] Loaded {len(minute_p_hat)} p_hat observations")
            else:
                print("  [HMM SIP] No p_hat data available for gating")

        # Broadcast with optional minute-level gating
        universe_map = self._broadcast_with_minute_gating(
            bars_utc, shortlist, target_et_date, minute_p_hat
        )

        # this hash will be consumed upstream into inputs_checksum.json
        sip_hash = hash_sip_map(universe_map)
        print(
            f"  [HMM SIP] Universe map: {len(universe_map)} timestamps, sip_hash: {sip_hash[:8]}..."
        )

        return universe_map

    def _load_external_premarket(self, target_et_date: str) -> list[str] | None:
        """Load external premarket Top-K from hybrid-local signals with caching."""
        external_root = Path(self.cfg.external_premarket_root)
        parquet_path = external_root / f"{target_et_date}_pre.parquet"

        if not parquet_path.exists():
            return None

        try:
            # Check cache first
            cache_key = (
                str(parquet_path),
                target_et_date,
                parquet_path.stat().st_mtime,
            )
            current_time = time.time()

            if cache_key in self._cache:
                cached_df, cache_time = self._cache[cache_key]
                if current_time - cache_time < self._cache_ttl_seconds:
                    # Cache hit
                    print(f"  [CACHE HIT] External file cached: {parquet_path.name}")
                else:
                    # Cache expired
                    del self._cache[cache_key]

            # Cache miss or expired
            if cache_key not in self._cache:
                # Clean up old entries if cache is full
                if len(self._cache) >= self._max_cache_size:
                    oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                    del self._cache[oldest_key]

                df = pd.read_parquet(parquet_path)
                self._cache[cache_key] = (df, current_time)
                print(f"  [CACHE MISS] Loaded external file: {parquet_path.name}")
            else:
                df, _ = self._cache[cache_key]

            if df.empty:
                return None

            # Ensure required columns exist
            if "sym" not in df.columns or "score" not in df.columns:
                return None

            # Filter by score floor
            if self.cfg.score_floor > 0:
                df = df[df["score"] >= self.cfg.score_floor]

            # Sort by score desc, then symbol asc for deterministic ties
            df = df.sort_values(["score", "sym"], ascending=[False, True])

            # Take top K symbols
            shortlist = df["sym"].head(self.cfg.top_k).tolist()

            return [str(symbol).upper() for symbol in shortlist]

        except Exception as e:
            print(f"  [CACHE ERROR] Failed to load external file: {e}")
            # If any error occurs loading, return None to trigger fallback
            return None

    def _get_gold_symbols(self) -> set[str]:
        """Get comprehensive Gold symbols list with caching."""
        current_time = time.time()

        # Check cache first
        if self._gold_symbols_cache is not None:
            cached_symbols, cache_time = self._gold_symbols_cache
            if current_time - cache_time < self._gold_symbols_cache_ttl_seconds:
                print(f"  [CACHE HIT] Using cached Gold symbols: {len(cached_symbols)} symbols")
                return cached_symbols

        # Cache miss - discover symbols
        print("  [CACHE MISS] Discovering Gold symbols...")
        gold_root = "/home/jacobw/gcs-mount"
        stocks_path = os.path.join(gold_root, "stocks")

        gold_symbols = set()
        if os.path.exists(stocks_path):
            for item in os.listdir(stocks_path):
                symbol_path = os.path.join(stocks_path, item)
                if os.path.isdir(symbol_path) and item != "_errors":
                    gold_symbols.add(item)

        # Cache the result
        self._gold_symbols_cache = (gold_symbols, current_time)
        print(f"  [CACHE MISS] Discovered and cached {len(gold_symbols)} Gold symbols")

        return gold_symbols

    def _compute_gold_premarket_shortlist(
        self, bars_utc: pd.DataFrame, target_et_date: str
    ) -> list[str]:
        """Compute premarket shortlist from Gold data only (fallback)."""
        # Use existing data if available, otherwise expand symbol universe
        print(f"  [HMM SIP] Using Gold fallback for {target_et_date}")

        # Start with symbols from input data
        available_symbols = set(bars_utc["symbol"].unique())
        print(f"  [HMM SIP] Input data has {len(available_symbols)} symbols")

        # Load comprehensive universe from Gold data for proper HMM_SIP filtering (cached)
        gold_symbols = self._get_gold_symbols()
        available_symbols.update(gold_symbols)
        print(f"  [HMM SIP] Using comprehensive universe: {len(available_symbols)} total symbols")

        # Use the input data as-is for premarket analysis
        full_bars_df = bars_utc
        print(f"  [HMM SIP] Using {len(full_bars_df):,} bars for premarket analysis")

        # Convert UTC timestamps to ET for slicing
        bars_et = full_bars_df.copy()
        bars_et["ts_et"] = pd.to_datetime(bars_et["ts"], unit="ns", utc=True).dt.tz_convert(ET_TZ)

        # Filter to target ET date
        target_date_parsed = pd.to_datetime(target_et_date).date()
        bars_et = bars_et[bars_et["ts_et"].dt.date == target_date_parsed]

        if bars_et.empty:
            print(f"  [HMM SIP] No data found for {target_et_date}")
            return []

        # Define premarket window (04:00-09:29 ET)
        premarket_mask = (bars_et["ts_et"].dt.hour >= 4) & (
            (bars_et["ts_et"].dt.hour < 9)
            | ((bars_et["ts_et"].dt.hour == 9) & (bars_et["ts_et"].dt.minute < 30))
        )
        premarket_bars = bars_et[premarket_mask]

        if premarket_bars.empty:
            return []

        # Find previous day close for gap calculation
        prev_close_map = self._get_previous_close(bars_utc, target_date)

        # Vectorized calculations for better performance with 1000+ symbols
        # Group by symbol and aggregate premarket data
        premarket_agg = (
            premarket_bars.groupby("symbol").agg({"close": "last", "volume": "sum"}).reset_index()
        )

        # Calculate premarket dollar volume (close * volume)
        premarket_agg["premarket_dv"] = premarket_agg["close"] * premarket_agg["volume"]

        # Get RTH opening prices for each symbol
        rth_open_bars = (
            bars_et[(bars_et["ts_et"].dt.hour >= 9) & (bars_et["ts_et"].dt.hour < 16)]
            .groupby("symbol")
            .first()
            .reset_index()
        )

        # Merge premarket data with RTH opens
        merged = premarket_agg.merge(rth_open_bars[["symbol", "open"]], on="symbol", how="inner")

        # Merge with previous close data
        prev_close_df = pd.DataFrame(
            [{"symbol": symbol, "prev_close": close} for symbol, close in prev_close_map.items()]
        )

        merged = merged.merge(prev_close_df, on="symbol", how="inner")

        # Filter out invalid previous closes
        merged = merged[merged["prev_close"] > 0]

        if merged.empty:
            return []

        # Calculate gap metrics vectorized
        merged["gap_pct"] = (merged["open"] - merged["prev_close"]) / merged["prev_close"]
        merged["gap_abs"] = merged["gap_pct"].abs()

        # Prepare final metrics
        symbol_metrics = merged[["symbol", "gap_pct", "premarket_dv", "gap_abs"]].to_dict("records")

        if not symbol_metrics:
            return []

        # Convert to DataFrame and compute scores
        metrics_df = pd.DataFrame(symbol_metrics)

        # Cross-sectional z-scoring
        metrics_df["gap_abs_z"] = self._cross_sectional_z(metrics_df["gap_abs"])
        metrics_df["premarket_dv_z"] = self._cross_sectional_z(metrics_df["premarket_dv"])

        # Calculate composite score
        metrics_df["score"] = 0.6 * metrics_df["premarket_dv_z"] + 0.4 * metrics_df["gap_abs_z"]

        # Filter by score floor
        if self.cfg.score_floor > 0:
            metrics_df = metrics_df[metrics_df["score"] >= self.cfg.score_floor]

        # Sort and select top K
        metrics_df = metrics_df.sort_values(["score", "symbol"], ascending=[False, True])
        shortlist = metrics_df["symbol"].head(self.cfg.top_k).tolist()

        return [str(symbol).upper() for symbol in shortlist]

    def _get_previous_close(
        self, bars_utc: pd.DataFrame, target_date: pd.Timestamp
    ) -> dict[str, float]:
        """Get previous trading day close for each symbol."""
        # Convert to ET for date logic
        bars_et = bars_utc.copy()
        bars_et["ts_et"] = pd.to_datetime(bars_et["ts"], unit="ns", utc=True).dt.tz_convert(ET_TZ)
        bars_et["date"] = bars_et["ts_et"].dt.date

        # Look back up to 5 days for previous close
        prev_close_map = {}
        for days_back in range(1, 6):
            prev_date = target_date - pd.Timedelta(days=days_back)

            # Filter for previous date and RTH only
            prev_rth = bars_et[
                (bars_et["date"] == prev_date.date())
                & (bars_et["ts_et"].dt.hour >= 9)
                & (bars_et["ts_et"].dt.hour <= 16)
            ]

            if not prev_rth.empty:
                # Get last close per symbol efficiently
                last_closes = prev_rth.groupby("symbol")["close"].last()
                for symbol, close in last_closes.items():
                    if symbol not in prev_close_map:
                        prev_close_map[symbol] = close

        return prev_close_map

    def _cross_sectional_z(self, series: pd.Series) -> pd.Series:
        """Calculate cross-sectional z-scores."""
        mean_val = series.mean()
        std_val = series.std()

        if std_val == 0:
            return pd.Series(0.0, index=series.index)

        return (series - mean_val) / std_val

    def _broadcast_daily_shortlist_to_rth_ts(
        self, bars_utc: pd.DataFrame, shortlist: list[str], target_et_date: str
    ) -> dict[int, set[str]]:
        """Broadcast daily shortlist to all RTH bars for the ET date."""
        # Convert to ET for time filtering (avoid copying entire dataframe for memory efficiency)
        ts_et = pd.to_datetime(bars_utc["ts"], unit="ns", utc=True).dt.tz_convert(ET_TZ)

        # Parse target date
        target_date = pd.Timestamp(target_et_date)

        # Filter to target ET date and RTH only (9:30-16:00 ET)
        rth_mask = (
            (ts_et.dt.date == target_date.date())
            & ((ts_et.dt.hour > 9) | ((ts_et.dt.hour == 9) & (ts_et.dt.minute >= 30)))
            & (ts_et.dt.hour < 16)
        )

        if not rth_mask.any():
            return {}

        # Get unique timestamps in UTC where mask is True
        rth_timestamps = bars_utc.loc[rth_mask, "ts"].unique()
        shortlist_set = set(shortlist)

        # Create mapping from timestamp to symbol set
        universe_map = {}
        for ts in rth_timestamps:
            universe_map[int(ts)] = shortlist_set.copy()

        return universe_map

    def _load_minute_p_hat_data(
        self, target_et_date: str, shortlist: list[str]
    ) -> pd.DataFrame | None:
        """Load minute-level p_hat data for symbols in shortlist with caching."""
        if not self.cfg.p_hat_threshold:
            return None

        # Parse target date
        target_date = pd.Timestamp(target_et_date)
        year = target_date.year
        month_str = target_date.strftime("%Y-%m")

        # Collect all p_hat data for symbols in shortlist
        all_p_hat_data = []

        for symbol in shortlist:
            # Path structure: ~/hybrid-local/signals/sip/1m/<SYM>/<YYYY>/<YYYY-MM>.parquet
            p_hat_path = (
                Path.home()
                / "hybrid-local"
                / "signals"
                / "sip"
                / "1m"
                / symbol
                / str(year)
                / f"{month_str}.parquet"
            )

            if not p_hat_path.exists():
                continue  # Skip symbols without p_hat data

            try:
                # Check cache first
                cache_key = (str(p_hat_path), symbol, p_hat_path.stat().st_mtime)
                current_time = time.time()

                if cache_key in self._p_hat_cache:
                    cached_df, cache_time = self._p_hat_cache[cache_key]
                    if current_time - cache_time < self._p_hat_cache_ttl_seconds:
                        # Cache hit
                        all_p_hat_data.append(cached_df)
                        continue
                    else:
                        # Cache expired
                        del self._p_hat_cache[cache_key]

                # Cache miss or expired
                if cache_key not in self._p_hat_cache:
                    # Clean up old entries if cache is full
                    if len(self._p_hat_cache) >= self._p_hat_max_cache_size:
                        oldest_key = min(
                            self._p_hat_cache.keys(),
                            key=lambda k: self._p_hat_cache[k][1],
                        )
                        del self._p_hat_cache[oldest_key]

                    df = pd.read_parquet(p_hat_path)
                    self._p_hat_cache[cache_key] = (df, current_time)
                    all_p_hat_data.append(df)
                else:
                    df, _ = self._p_hat_cache[cache_key]
                    all_p_hat_data.append(df)

            except Exception as e:
                print(f"  [P_HAT CACHE ERROR] Failed to load p_hat data for {symbol}: {e}")
                continue

        if not all_p_hat_data:
            return None

        # Combine all p_hat data
        combined_p_hat = pd.concat(all_p_hat_data, ignore_index=True)

        # Ensure required columns exist
        if "ts" not in combined_p_hat.columns or "p_hat" not in combined_p_hat.columns:
            return None

        # Filter to target date and ensure UTC timestamps
        combined_p_hat["ts_utc"] = pd.to_datetime(combined_p_hat["ts"], unit="ns", utc=True)
        combined_p_hat["date_utc"] = combined_p_hat["ts_utc"].dt.date

        target_date_utc = target_date.tz_localize(None).date()
        combined_p_hat = combined_p_hat[combined_p_hat["date_utc"] == target_date_utc]

        if combined_p_hat.empty:
            return None

        return combined_p_hat[["ts", "p_hat"]]

    def _broadcast_with_minute_gating(
        self,
        bars_utc: pd.DataFrame,
        shortlist: list[str],
        target_et_date: str,
        minute_p_hat: pd.DataFrame | None,
    ) -> dict[int, set[str]]:
        """Broadcast daily shortlist to RTH bars with optional minute-level p_hat gating."""
        # Convert to ET for time filtering
        ts_et = pd.to_datetime(bars_utc["ts"], unit="ns", utc=True).dt.tz_convert(ET_TZ)

        # Parse target date
        target_date = pd.Timestamp(target_et_date)

        # Filter to target ET date and RTH only (9:30-16:00 ET)
        rth_mask = (
            (ts_et.dt.date == target_date.date())
            & ((ts_et.dt.hour > 9) | ((ts_et.dt.hour == 9) & (ts_et.dt.minute >= 30)))
            & (ts_et.dt.hour < 16)
        )

        if not rth_mask.any():
            return {}

        # Get RTH bars with their timestamps
        rth_bars = bars_utc[rth_mask].copy()
        shortlist_set = set(shortlist)

        # If no minute-level gating, use original broadcast logic
        if minute_p_hat is None:
            rth_timestamps = rth_bars["ts"].unique()
            universe_map = {}
            for ts in rth_timestamps:
                universe_map[int(ts)] = shortlist_set.copy()
            return universe_map

        # Apply minute-level p_hat gating
        print(
            f"  [P_HAT GATING] Applying threshold {self.cfg.p_hat_threshold} to {len(shortlist)} symbols"
        )

        # Merge p_hat data with bars
        merged = rth_bars.merge(minute_p_hat, on="ts", how="left")

        # Initialize universe map
        universe_map = {}

        # Group by timestamp and apply gating
        for ts, group in merged.groupby("ts"):
            eligible_symbols = set()

            # Symbols that pass p_hat threshold at this minute
            if "p_hat" in group.columns:
                # Filter out rows with NaN p_hat values, then apply threshold
                valid_p_hat = group.dropna(subset=["p_hat"])
                passing_symbols = valid_p_hat[valid_p_hat["p_hat"] >= self.cfg.p_hat_threshold][
                    "symbol"
                ].unique()
            else:
                passing_symbols = set()

            # Apply min_minutes_in_state filter if configured
            if self.cfg.min_minutes_in_state > 0 and len(passing_symbols) > 0:
                # Look back to ensure symbol has been passing threshold for minimum minutes
                current_time = pd.to_datetime(ts, unit="ns", utc=True)
                window_start = current_time - pd.Timedelta(minutes=self.cfg.min_minutes_in_state)

                # Get p_hat data for the time window
                window_data = minute_p_hat[
                    (minute_p_hat["ts"] >= int(window_start.timestamp() * 1e9))
                    & (minute_p_hat["ts"] <= ts)
                ]

                # Check which symbols have been consistently above threshold
                for symbol in passing_symbols:
                    symbol_window = window_data[
                        window_data["ts"].isin(group[group["symbol"] == symbol]["ts"])
                    ]

                    if len(symbol_window) >= self.cfg.min_minutes_in_state:
                        if (symbol_window["p_hat"] >= self.cfg.p_hat_threshold).all():
                            eligible_symbols.add(symbol)
            else:
                eligible_symbols = set(passing_symbols)

            # Final eligible set = intersection of shortlist and p_hat-gated symbols
            final_eligible = shortlist_set.intersection(eligible_symbols)

            if final_eligible:  # Only add entries for timestamps with eligible symbols
                universe_map[int(ts)] = final_eligible

        if universe_map:
            avg_symbols = sum(len(s) for s in universe_map.values()) / len(universe_map)
            print(
                f"  [P_HAT GATING] Reduced eligibility from {len(shortlist)} to avg {avg_symbols:.1f} symbols per minute"
            )

        return universe_map
