from datetime import date, datetime

import pandas as pd

from .hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector


class DailyHMMSIPSelector:
    def __init__(
        self,
        score_floor: float = 0.0,
        top_k: int = 40,
        broadcast_time: str = "09:30:00",
    ):
        self.score_floor = score_floor
        self.top_k = top_k
        self.broadcast_time = datetime.strptime(broadcast_time, "%H:%M:%S").time()
        self._daily_universes: dict[date, set[str]] = {}
        # Create a default config for the base selector
        config = HMMSIPConfig(score_floor=score_floor, top_k=top_k)
        self._base_selector = HMMSIPUniverseSelector(config)

    def select_daily_universes(self, bars_utc: pd.DataFrame) -> dict[date, set[str]]:
        """Select universe for each trading day using HMM scoring"""
        # Group bars by date (convert integer nanosecond timestamps to datetime)
        bars_utc["date"] = pd.to_datetime(bars_utc["ts"], unit="ns").dt.date
        daily_groups = bars_utc.groupby("date")

        for trading_date, day_bars in daily_groups:
            # For now, create a mock universe based on available symbols
            # In real implementation, this would use HMM scoring
            symbols_in_day = set(day_bars["symbol"].unique())

            # Apply top_k limit
            if len(symbols_in_day) > self.top_k:
                # Take first top_k symbols (real impl would sort by score)
                symbols_in_day = set(list(symbols_in_day)[: self.top_k])

            self._daily_universes[trading_date] = symbols_in_day

        return self._daily_universes

    def is_symbol_eligible(self, symbol: str, timestamp: datetime) -> bool:
        """Check if symbol is eligible at given timestamp"""
        trading_date = timestamp.date()
        if trading_date not in self._daily_universes:
            return False

        return symbol in self._daily_universes[trading_date]

    def get_universe_for_timestamp(self, timestamp: datetime) -> set[str]:
        """Get universe for specific timestamp (broadcasts daily universe to all intraday times)"""
        trading_date = timestamp.date()
        return self._daily_universes.get(trading_date, set())
